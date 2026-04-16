from __future__ import annotations

from dataclasses import dataclass, field
import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable

import requests

from app.clients.kis_contract import (
    TIME_ITEMCHART_FID_ETC_CLS_CODE,
    DomesticStockPaths,
    DomesticTrIds,
    OverseasPricePaths,
    OverseasStockPaths,
    OverseasTrIds,
    is_paper_host,
    pick_tr,
)
from app.clients.kis_parsers import business_error_detail, is_kis_rate_limit, rt_cd_ok

# 호스트(모의/실전 base URL)별 최소 요청 간격 — KIS EGW00201(초당 거래건수) 완화
_host_next_allowed: dict[str, float] = {}
_host_throttle_lock = threading.Lock()


def _throttle_kis_host(host_key: str, min_interval_sec: float) -> None:
    if min_interval_sec <= 0:
        return
    with _host_throttle_lock:
        now = time.monotonic()
        earliest = _host_next_allowed.get(host_key, 0.0)
        if now < earliest:
            time.sleep(earliest - now)
        _host_next_allowed[host_key] = time.monotonic() + min_interval_sec


def sanitize_kis_params_for_log(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """로그·진단용: 계좌·종목 등 민감 필드 마스킹."""
    if not params:
        return params
    out: dict[str, Any] = {}
    for k, v in params.items():
        ks = str(k).upper()
        if ks in ("CANO", "ACNT_PRDT_CD"):
            s = str(v) if v is not None else ""
            out[k] = (s[:2] + "****" + s[-2:]) if len(s) > 4 else "****"
        elif ks == "PDNO" and isinstance(v, str) and len(v) > 3:
            out[k] = v[:3] + "**"
        else:
            out[k] = v
    return out


def prune_empty_get_params(
    params: dict[str, Any] | None,
    *,
    keep_zero: bool = True,
    allow_empty_keys: frozenset[str] | set[str] | None = None,
) -> dict[str, Any] | None:
    """
    KIS GET 쿼리 정리: None·빈 문자열·공백만 있는 문자열은 제외(OPSQ2001 등 예방).
    숫자 0·문자열 '0'·'00' 은 유효 값으로 유지.
    allow_empty_keys: 특정 키만 빈 문자열도 그대로 보내야 할 때(드묾).
    """
    if params is None:
        return None
    allow = allow_empty_keys or frozenset()
    out: dict[str, Any] = {}
    for k, v in params.items():
        if k in allow:
            out[k] = v
            continue
        if v is None:
            continue
        if isinstance(v, str):
            if not v.strip():
                continue
            out[k] = v
            continue
        if isinstance(v, bool):
            out[k] = v
            continue
        if isinstance(v, (int, float)):
            if keep_zero or v != 0:
                out[k] = v
            continue
        out[k] = v
    return out


def omit_empty_ctx_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """하위 호환: 전체 GET 파라미터 prune 과 동일(CTX 포함)."""
    return prune_empty_get_params(params)


class KISClientError(RuntimeError):
    def __init__(self, message: str, *, kis_context: dict[str, Any] | None = None):
        super().__init__(message)
        self.kis_context = kis_context or {}


class KISLiveTradingLockedError(KISClientError):
    """실전 호스트에서 주문·취소가 잠금된 경우."""


@dataclass(frozen=True)
class KISEndpoints:
    """하위 호환: 기존 코드가 필드명을 참조할 수 있게 유지."""

    get_balance: str = DomesticStockPaths.balance
    get_quote: str = DomesticStockPaths.quote
    get_positions: str = DomesticStockPaths.balance
    place_order: str = DomesticStockPaths.order_cash
    cancel_order: str = DomesticStockPaths.order_cancel
    hashkey: str = DomesticStockPaths.hashkey
    daily_itemchart: str = DomesticStockPaths.daily_itemchart
    time_itemchart: str = DomesticStockPaths.time_itemchart
    time_itemconclusion: str = DomesticStockPaths.time_itemconclusion
    inquire_psbl_order: str = DomesticStockPaths.inquire_psbl_order
    inquire_nccs: str = DomesticStockPaths.inquire_nccs
    inquire_daily_ccld: str = DomesticStockPaths.inquire_daily_ccld


@dataclass
class KISClient:
    base_url: str
    timeout_sec: int = 10
    max_retries: int = 2
    retry_backoff_sec: float = 0.4
    """동일 호스트로 연속 요청 시 최소 간격(ms). 0이면 스로틀 없음."""
    kis_min_request_interval_ms: int = 250
    """EGW00201 등 rate limit 응답 시 추가 재시도 상한(지수 백오프)."""
    kis_rate_limit_max_retries: int = 6
    kis_rate_limit_backoff_base_sec: float = 0.5
    kis_rate_limit_backoff_cap_sec: float = 30.0
    token_provider: Callable[[], str] | None = None
    app_key: str | None = None
    app_secret: str | None = None
    custtype: str = "P"
    """실전 주문/취소 허용 시 True (다중 환경 플래그와 함께 사용)."""
    live_execution_unlocked: bool = False
    endpoints: KISEndpoints = field(default_factory=KISEndpoints)
    tr_ids: DomesticTrIds = field(default_factory=DomesticTrIds)
    overseas_paths: OverseasStockPaths = field(default_factory=OverseasStockPaths)
    overseas_price_paths: OverseasPricePaths = field(default_factory=OverseasPricePaths)
    overseas_tr_ids: OverseasTrIds = field(default_factory=OverseasTrIds)
    session: requests.Session = field(default_factory=requests.Session)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("app.clients.kis_client"))

    def _build_headers(
        self,
        *,
        tr_id: str | None = None,
        bearer_token: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        headers: dict[str, str] = {
            "content-type": "application/json; charset=UTF-8",
            "accept": "application/json",
            "custtype": self.custtype,
        }
        if self.app_key:
            headers["appkey"] = self.app_key
        if self.app_secret:
            headers["appsecret"] = self.app_secret
        token = bearer_token or (self.token_provider() if self.token_provider else "")
        if token:
            headers["authorization"] = f"Bearer {token}"
        if tr_id:
            headers["tr_id"] = tr_id
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _resolve_tr_id(self, *, paper_tr_id: str, live_tr_id: str) -> str:
        return pick_tr(paper=paper_tr_id, live=live_tr_id, base_url=self.base_url)

    def _host_throttle_key(self) -> str:
        return self.base_url.rstrip("/").lower()

    @staticmethod
    def _response_json_object(response: requests.Response) -> dict[str, Any] | None:
        try:
            if not response.content:
                return None
            payload = response.json()
            return payload if isinstance(payload, dict) else None
        except ValueError:
            return None

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        tr_id: str | None = None,
        bearer_token: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        headers = self._build_headers(tr_id=tr_id, bearer_token=bearer_token, extra_headers=extra_headers)
        min_int_sec = max(0.0, float(self.kis_min_request_interval_ms) / 1000.0)
        max_total = max(
            20,
            (self.max_retries + 1) + max(8, self.kis_rate_limit_max_retries + 4),
        )
        last_net_error: Exception | None = None
        rate_backoff_idx = 0

        for attempt in range(max_total):
            _throttle_kis_host(self._host_throttle_key(), min_int_sec)
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=data,
                    headers=headers,
                    timeout=self.timeout_sec,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_net_error = exc
                if attempt >= max_total - 1:
                    break
                sleep_s = self.retry_backoff_sec * (2 ** min(attempt, 6))
                self.logger.warning(
                    "KIS request retrying due to network/timeout",
                    extra={"method": method, "path": path, "attempt": attempt + 1},
                )
                time.sleep(sleep_s)
                continue

            text = response.text or ""
            payload = self._response_json_object(response)

            if response.status_code >= 400:
                if is_kis_rate_limit(payload=payload, http_body=text, http_status=response.status_code):
                    sleep_s = min(
                        float(self.kis_rate_limit_backoff_cap_sec),
                        float(self.kis_rate_limit_backoff_base_sec) * (2 ** min(rate_backoff_idx, 8)),
                    )
                    rate_backoff_idx += 1
                    rl_ctx: dict[str, Any] = {
                        "rate_limit": True,
                        "retry_after_sec": sleep_s,
                        "method": method,
                        "path": path,
                        "tr_id": tr_id,
                        "params": sanitize_kis_params_for_log(params if method == "GET" else None),
                        "body_keys": sorted(data.keys()) if isinstance(data, dict) else None,
                        "http_status": response.status_code,
                    }
                    self.logger.warning(
                        "KIS rate limit (HTTP %s), backoff %.2fs path=%s",
                        response.status_code,
                        sleep_s,
                        path,
                    )
                    time.sleep(sleep_s)
                    if rate_backoff_idx > max(3, self.kis_rate_limit_max_retries):
                        raise KISClientError(
                            f"KIS rate limit persists after retries: HTTP {response.status_code} path={path}",
                            kis_context=rl_ctx,
                        )
                    continue
                ctx = {
                    "method": method,
                    "path": path,
                    "tr_id": tr_id,
                    "params": sanitize_kis_params_for_log(params if method == "GET" else None),
                    "body_keys": sorted(data.keys()) if isinstance(data, dict) else None,
                    "http_status": response.status_code,
                    "rate_limit": False,
                }
                self.logger.error(
                    "KIS HTTP error",
                    extra={
                        "status_code": response.status_code,
                        "method": method,
                        "url": url.split("?")[0],
                        "tr_id": tr_id,
                    },
                )
                body_preview = text[:400] if text else ""
                raise KISClientError(
                    f"KIS HTTP {response.status_code} {method} - 응답 본문 일부: {body_preview}",
                    kis_context=ctx,
                )

            if payload is None:
                raise KISClientError("KIS response is not valid JSON object")

            if not rt_cd_ok(payload):
                if is_kis_rate_limit(payload=payload, http_body=text):
                    sleep_s = min(
                        float(self.kis_rate_limit_backoff_cap_sec),
                        float(self.kis_rate_limit_backoff_base_sec) * (2 ** min(rate_backoff_idx, 8)),
                    )
                    rate_backoff_idx += 1
                    rl_ctx2: dict[str, Any] = {
                        "rate_limit": True,
                        "retry_after_sec": sleep_s,
                        "method": method,
                        "path": path,
                        "tr_id": tr_id,
                        "params": sanitize_kis_params_for_log(params if method == "GET" else None),
                        "body_keys": sorted(data.keys()) if isinstance(data, dict) else None,
                        "http_status": response.status_code,
                    }
                    self.logger.warning(
                        "KIS business rate limit (rt_cd≠0), backoff %.2fs path=%s detail=%s",
                        sleep_s,
                        path,
                        business_error_detail(payload)[:200],
                    )
                    time.sleep(sleep_s)
                    if rate_backoff_idx > max(3, self.kis_rate_limit_max_retries):
                        raise KISClientError(
                            f"KIS rate limit persists after retries: path={path}",
                            kis_context=rl_ctx2,
                        )
                    continue
                self._validate_kis_business_success(
                    payload,
                    method=method,
                    path=path,
                    tr_id=tr_id,
                    params=params,
                    data=data,
                )

            return payload

        ctx = {
            "method": method,
            "path": path,
            "tr_id": tr_id,
            "params": sanitize_kis_params_for_log(params if method == "GET" else None),
            "body_keys": sorted(data.keys()) if isinstance(data, dict) else None,
            "error_type": type(last_net_error).__name__ if last_net_error else "unknown",
            "rate_limit": False,
        }
        self.logger.error(
            "KIS request exhausted retries",
            extra={"method": method, "path": path, "tr_id": tr_id},
        )
        raise KISClientError(
            f"KIS request failed after retries: method={method} path={path}",
            kis_context=ctx,
        ) from last_net_error

    def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        tr_id: str | None = None,
        bearer_token: str | None = None,
        extra_headers: dict[str, str] | None = None,
        allow_empty_param_keys: frozenset[str] | None = None,
    ) -> dict[str, Any]:
        q = prune_empty_get_params(params, allow_empty_keys=allow_empty_param_keys)
        return self._request(
            "GET",
            path,
            params=q,
            tr_id=tr_id,
            bearer_token=bearer_token,
            extra_headers=extra_headers,
        )

    def _post(
        self,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        tr_id: str | None = None,
        bearer_token: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            path,
            data=data,
            tr_id=tr_id,
            bearer_token=bearer_token,
            extra_headers=extra_headers,
        )

    def _raise_for_status(
        self,
        response: requests.Response,
        *,
        method: str,
        url: str,
        path: str,
        tr_id: str | None,
        params: dict[str, Any] | None,
        data: dict[str, Any] | None = None,
    ) -> None:
        if response.status_code < 400:
            return
        status = response.status_code
        body_preview = response.text[:400] if response.text else ""
        ctx = {
            "method": method,
            "path": path,
            "tr_id": tr_id,
            "params": sanitize_kis_params_for_log(params if method == "GET" else None),
            "body_keys": sorted(data.keys()) if isinstance(data, dict) else None,
            "http_status": status,
        }
        self.logger.error(
            "KIS HTTP error",
            extra={"status_code": status, "method": method, "url": url.split("?")[0], "tr_id": tr_id},
        )
        raise KISClientError(
            f"KIS HTTP {status} {method} - 응답 본문 일부: {body_preview}",
            kis_context=ctx,
        )

    @staticmethod
    def _safe_json(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise KISClientError("KIS response is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise KISClientError("KIS response JSON payload is not object")
        return payload

    def _validate_kis_business_success(
        self,
        payload: dict[str, Any],
        *,
        method: str,
        path: str,
        tr_id: str | None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        if rt_cd_ok(payload):
            return
        detail = business_error_detail(payload)
        params_for_log = prune_empty_get_params(dict(params)) if params else None
        ctx: dict[str, Any] = {
            "method": method,
            "path": path,
            "tr_id": tr_id,
            "params": sanitize_kis_params_for_log(params_for_log),
            "data_keys": sorted(data.keys()) if isinstance(data, dict) else None,
            "rate_limit": False,
            "http_status": 200,
            "rt_cd": str(payload.get("rt_cd") or payload.get("RT_CD") or ""),
            "msg_cd": str(payload.get("msg_cd") or payload.get("MSG_CD") or ""),
            "msg1": str(payload.get("msg1") or payload.get("MSG1") or ""),
        }
        self.logger.error(
            "KIS business error",
            extra={
                "kis_path": path,
                "kis_tr_id": tr_id,
                "detail": detail[:800],
                "params": ctx.get("params"),
            },
        )
        raise KISClientError(f"KIS business error: {detail}", kis_context=ctx)

    def _ensure_order_execution_allowed(self) -> None:
        if is_paper_host(self.base_url):
            return
        if not self.live_execution_unlocked:
            raise KISLiveTradingLockedError(
                "실전 주문 경로는 잠겨 있습니다. TRADING_MODE=live 및 LIVE_TRADING 관련 "
                "확인 플래그가 모두 켜진 경우에만 live_execution_unlocked=True 로 해제하세요."
            )

    # --- 조회 ---

    def get_balance(self, account_no: str, account_product_code: str) -> dict[str, Any]:
        # OFL_YN: KIS 잔고조회(OPSQ2001) 필수 — 미전송 시 INPUT_FIELD_NAME OFL_YN 오류
        params = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "OFL_YN": "N",
            "AFHR_FLPR_YN": "N",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        tr_id = self._resolve_tr_id(paper_tr_id=self.tr_ids.balance_paper, live_tr_id=self.tr_ids.balance_live)
        ctx_keys = frozenset({"CTX_AREA_FK100", "CTX_AREA_NK100"})
        payload = self._get(
            self.endpoints.get_balance,
            params=params,
            tr_id=tr_id,
            allow_empty_param_keys=ctx_keys,
        )
        self._validate_kis_business_success(
            payload,
            method="GET",
            path=self.endpoints.get_balance,
            tr_id=tr_id,
            params=params,
        )
        return payload

    def get_quote(self, symbol: str) -> dict[str, Any]:
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
        }
        tr_id = self._resolve_tr_id(paper_tr_id=self.tr_ids.quote_paper, live_tr_id=self.tr_ids.quote_live)
        payload = self._get(self.endpoints.get_quote, params=params, tr_id=tr_id)
        self._validate_kis_business_success(
            payload,
            method="GET",
            path=self.endpoints.get_quote,
            tr_id=tr_id,
            params=params,
        )
        return payload

    def get_positions(self, account_no: str, account_product_code: str) -> dict[str, Any]:
        return self.get_balance(account_no=account_no, account_product_code=account_product_code)

    def inquire_psbl_order(
        self,
        *,
        account_no: str,
        account_product_code: str,
        symbol: str,
        order_price: int | None = None,
        order_div: str = "01",
        cma_evlu_amt_icld_yn: str = "N",
        ovrs_icld_yn: str = "N",
    ) -> dict[str, Any]:
        """
        매수가능조회 (주문가능현금·가능수량 등).
        ORD_DVSN: 00 지정가, 01 시장가.
        - 시장가(01): 모의/실전 API가 ORD_UNPR 를 필수로 검사함 → "0" 전송(주문 시와 동일).
        - 지정가(00): ORD_UNPR 에 가격 문자열 전송.
        - CMA_EVLU_AMT_ICLD_YN / OVRS_ICLD_YN: KIS 공식 필수(샘플은 보통 N/N).
        - 첫 페이지: CTX_AREA_* 키 없음(연속조회 시에만 API 응답 ctx로 채움).
        """
        params: dict[str, Any] = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "PDNO": symbol,
            "ORD_DVSN": order_div,
            "CMA_EVLU_AMT_ICLD_YN": str(cma_evlu_amt_icld_yn).strip() or "N",
            "OVRS_ICLD_YN": str(ovrs_icld_yn).strip() or "N",
        }
        if str(order_div).strip() == "01":
            params["ORD_UNPR"] = "0"
        elif order_price is not None:
            params["ORD_UNPR"] = str(int(order_price))
        tr_id = self._resolve_tr_id(paper_tr_id=self.tr_ids.psbl_order_paper, live_tr_id=self.tr_ids.psbl_order_live)
        payload = self._get(self.endpoints.inquire_psbl_order, params=params, tr_id=tr_id)
        self._validate_kis_business_success(
            payload,
            method="GET",
            path=self.endpoints.inquire_psbl_order,
            tr_id=tr_id,
            params=prune_empty_get_params(params),
        )
        return payload

    def inquire_nccs(
        self,
        *,
        account_no: str,
        account_product_code: str,
        symbol: str = "",
    ) -> dict[str, Any]:
        """
        미체결 내역 조회.

        과거 전용 URL(/trading/inquire-nccs, VTTC8003R)은 모의 서버에서 HTTP 404가 나는 경우가 있어,
        공식 샘플과 동일하게 **주식일별주문체결조회**에 CCLD_DVSN=02(미체결)로 위임한다.
        """
        return self.inquire_daily_ccld(
            account_no=account_no,
            account_product_code=account_product_code,
            symbol=symbol,
            sell_buy_code="00",
            ccld_div="02",
        )

    def inquire_daily_ccld(
        self,
        *,
        account_no: str,
        account_product_code: str,
        start_yyyymmdd: str | None = None,
        end_yyyymmdd: str | None = None,
        symbol: str = "",
        sell_buy_code: str = "00",
        ccld_div: str = "00",
    ) -> dict[str, Any]:
        """
        주식일별주문체결조회 (당일·기간 체결/미체결 포함).
        SLL_BUY_DVSN_CD: 00 전체, 01 매도, 02 매수
        CCLD_DVSN: 00 전체, 01 체결, 02 미체결
        INQR_DVSN_3: 스펙상 구분값(00) 전송.
        INQR_DVSN_1/2·빈 ORD_*·CTX: 첫 페이지는 전송하지 않음(모의 OPSQ2001 예방).
        PDNO: 종목 지정 시만 전송.
        """
        today = datetime.now().strftime("%Y%m%d")
        start = start_yyyymmdd or today
        end = end_yyyymmdd or today
        params: dict[str, Any] = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "INQR_STRT_DT": start,
            "INQR_END_DT": end,
            "SLL_BUY_DVSN_CD": sell_buy_code,
            "INQR_DVSN": "00",
            "CCLD_DVSN": ccld_div,
            "INQR_DVSN_3": "00",
        }
        if symbol and str(symbol).strip():
            params["PDNO"] = str(symbol).strip()
        tr_id = self._resolve_tr_id(paper_tr_id=self.tr_ids.daily_ccld_paper, live_tr_id=self.tr_ids.daily_ccld_live)
        payload = self._get(self.endpoints.inquire_daily_ccld, params=params, tr_id=tr_id)
        self._validate_kis_business_success(
            payload,
            method="GET",
            path=self.endpoints.inquire_daily_ccld,
            tr_id=tr_id,
            params=prune_empty_get_params(params),
        )
        return payload

    def request_hashkey(self, body: dict[str, Any]) -> str:
        payload = self._post(self.endpoints.hashkey, data=body, tr_id=None)
        if not rt_cd_ok(payload):
            raise KISClientError(
                f"hashkey issuance failed: {business_error_detail(payload)}",
                kis_context={
                    "method": "POST",
                    "path": self.endpoints.hashkey,
                    "tr_id": None,
                    "body_keys": sorted(body.keys()),
                },
            )
        h = payload.get("HASH") or payload.get("hash")
        if not isinstance(h, str) or not h.strip():
            raise KISClientError("hashkey response missing HASH")
        return h.strip()

    def get_daily_itemchartprice(
        self,
        *,
        market_div_code: str,
        symbol: str,
        start_date_yyyymmdd: str,
        end_date_yyyymmdd: str,
        period_div_code: str = "D",
        org_adj_prc: str = "1",
    ) -> dict[str, Any]:
        params = {
            "FID_COND_MRKT_DIV_CODE": market_div_code,
            "FID_INPUT_ISCD": symbol,
            "FID_INPUT_DATE_1": start_date_yyyymmdd,
            "FID_INPUT_DATE_2": end_date_yyyymmdd,
            "FID_PERIOD_DIV_CODE": period_div_code,
            "FID_ORG_ADJ_PRC": org_adj_prc,
        }
        tr_id = self._resolve_tr_id(paper_tr_id=self.tr_ids.daily_chart_paper, live_tr_id=self.tr_ids.daily_chart_live)
        payload = self._get(self.endpoints.daily_itemchart, params=params, tr_id=tr_id)
        self._validate_kis_business_success(
            payload,
            method="GET",
            path=self.endpoints.daily_itemchart,
            tr_id=tr_id,
            params=params,
        )
        return payload

    def get_time_itemchartprice(
        self,
        *,
        market_div_code: str,
        symbol: str,
        input_hour_hhmmss: str,
        include_past_data: str = "Y",
        etc_cls_code: str = TIME_ITEMCHART_FID_ETC_CLS_CODE,
    ) -> dict[str, Any]:
        """
        주식당일분봉조회. 한 호출당 최대 약 30건(공식 안내).
        FID_INPUT_HOUR_1: 조회 기준 시각(HHMMSS). 연속 조회 시 이전 응답의 더 과거 시각을 넣어 페이징.
        FID_PW_DATA_INCU_YN: 과거 데이터 포함(Y/N).
        FID_ETC_CLS_CODE: 국내 주식 1분봉 기본값 TIME_ITEMCHART_FID_ETC_CLS_CODE("00"). 빈 문자열은 GET prune 으로 제거되어 OPSQ2001 발생.
        """
        params = {
            "FID_COND_MRKT_DIV_CODE": market_div_code,
            "FID_INPUT_ISCD": symbol,
            "FID_INPUT_HOUR_1": input_hour_hhmmss,
            "FID_PW_DATA_INCU_YN": include_past_data,
            "FID_ETC_CLS_CODE": etc_cls_code,
        }
        tr_id = self._resolve_tr_id(
            paper_tr_id=self.tr_ids.time_itemchart_paper,
            live_tr_id=self.tr_ids.time_itemchart_live,
        )
        payload = self._get(self.endpoints.time_itemchart, params=params, tr_id=tr_id)
        self._validate_kis_business_success(
            payload,
            method="GET",
            path=self.endpoints.time_itemchart,
            tr_id=tr_id,
            params=params,
        )
        return payload

    def get_time_itemconclusion(
        self,
        *,
        market_div_code: str,
        symbol: str,
        input_hour_hhmmss: str,
    ) -> dict[str, Any]:
        """주식현재가 당일시간대별체결 (거래대금·체결 흐름 등 시세분석 보조)."""
        params = {
            "FID_COND_MRKT_DIV_CODE": market_div_code,
            "FID_INPUT_ISCD": symbol,
            "FID_INPUT_HOUR_1": input_hour_hhmmss,
        }
        tr_id = self._resolve_tr_id(
            paper_tr_id=self.tr_ids.time_itemconclusion_paper,
            live_tr_id=self.tr_ids.time_itemconclusion_live,
        )
        payload = self._get(self.endpoints.time_itemconclusion, params=params, tr_id=tr_id)
        self._validate_kis_business_success(
            payload,
            method="GET",
            path=self.endpoints.time_itemconclusion,
            tr_id=tr_id,
            params=params,
        )
        return payload

    # --- 주문 (실전 호스트는 잠금) ---

    def place_order(
        self,
        *,
        account_no: str,
        account_product_code: str,
        symbol: str,
        side: str,
        quantity: int,
        price: int = 0,
    ) -> dict[str, Any]:
        self._ensure_order_execution_allowed()
        side_norm = side.lower().strip()
        if side_norm == "buy":
            tr_id = self._resolve_tr_id(paper_tr_id=self.tr_ids.buy_paper, live_tr_id=self.tr_ids.buy_live)
        elif side_norm == "sell":
            tr_id = self._resolve_tr_id(paper_tr_id=self.tr_ids.sell_paper, live_tr_id=self.tr_ids.sell_live)
        else:
            raise KISClientError(f"Unsupported order side: {side}")

        if price > 0:
            ord_dvsn = "00"
            ord_unpr = str(int(price))
        else:
            ord_dvsn = "01"
            ord_unpr = "0"

        body = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "PDNO": symbol,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(int(quantity)),
            "ORD_UNPR": ord_unpr,
        }
        hashkey = self.request_hashkey(body)
        extra = {"hashkey": hashkey}
        payload = self._post(self.endpoints.place_order, data=body, tr_id=tr_id, extra_headers=extra)
        self._validate_kis_business_success(
            payload,
            method="POST",
            path=self.endpoints.place_order,
            tr_id=tr_id,
            data=body,
        )
        return payload

    def cancel_order(
        self,
        *,
        account_no: str,
        account_product_code: str,
        original_order_no: str,
        quantity: int,
        symbol: str,
        order_div: str = "01",
        krx_fwdg_ord_orgno: str = "",
        cancel_all: bool = False,
    ) -> dict[str, Any]:
        self._ensure_order_execution_allowed()
        tr_id = self._resolve_tr_id(paper_tr_id=self.tr_ids.cancel_paper, live_tr_id=self.tr_ids.cancel_live)
        qty_all = "Y" if cancel_all or quantity <= 0 else "N"
        ord_qty = "0" if cancel_all else str(int(max(quantity, 0)))
        body = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "KRX_FWDG_ORD_ORGNO": krx_fwdg_ord_orgno,
            "ORGN_ODNO": original_order_no,
            "ORD_DVSN": order_div,
            "RVSE_CNCL_DVSN_CD": "02",
            "ORD_QTY": ord_qty,
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": qty_all,
            "PDNO": symbol,
        }
        hashkey = self.request_hashkey(body)
        extra = {"hashkey": hashkey}
        payload = self._post(self.endpoints.cancel_order, data=body, tr_id=tr_id, extra_headers=extra)
        self._validate_kis_business_success(
            payload,
            method="POST",
            path=self.endpoints.cancel_order,
            tr_id=tr_id,
            data=body,
        )
        return payload

    # --- 해외주식 (공식 예제 path/TR/params: overseas_stock_functions.py) ---

    def get_overseas_price_quotation(self, *, excd: str, symb: str, auth: str = "") -> dict[str, Any]:
        """해외주식 현재체결가 — GET quotations/price, TR HHDFS00000300."""
        params = {"AUTH": auth, "EXCD": excd, "SYMB": symb}
        tr_id = self.overseas_tr_ids.price
        path = self.overseas_price_paths.price
        payload = self._get(path, params=params, tr_id=tr_id)
        self._validate_kis_business_success(payload, method="GET", path=path, tr_id=tr_id, params=params)
        return payload

    def get_overseas_search_info(self, *, prdt_type_cd: str, pdno: str) -> dict[str, Any]:
        """해외주식 상품기본정보 — GET search-info, TR CTPF1702R."""
        params = {"PRDT_TYPE_CD": prdt_type_cd, "PDNO": pdno}
        tr_id = self.overseas_tr_ids.search_info
        path = self.overseas_price_paths.search_info
        payload = self._get(path, params=params, tr_id=tr_id)
        self._validate_kis_business_success(payload, method="GET", path=path, tr_id=tr_id, params=params)
        return payload

    def get_overseas_time_itemchartprice(
        self,
        *,
        auth: str,
        excd: str,
        symb: str,
        nmin: str,
        pinc: str,
        next_flag: str,
        nrec: str,
        fill: str,
        keyb: str,
    ) -> dict[str, Any]:
        """해외주식분봉조회 — GET inquire-time-itemchartprice, TR HHDFS76950200."""
        params = {
            "AUTH": auth,
            "EXCD": excd,
            "SYMB": symb,
            "NMIN": nmin,
            "PINC": pinc,
            "NEXT": next_flag,
            "NREC": nrec,
            "FILL": fill,
            "KEYB": keyb,
        }
        tr_id = self.overseas_tr_ids.time_itemchart
        path = self.overseas_price_paths.inquire_time_itemchartprice
        payload = self._get(path, params=params, tr_id=tr_id)
        self._validate_kis_business_success(payload, method="GET", path=path, tr_id=tr_id, params=params)
        return payload

    def get_overseas_inquire_balance(
        self,
        *,
        account_no: str,
        account_product_code: str,
        ovrs_excg_cd: str,
        tr_crcy_cd: str,
        ctx_fk200: str = "",
        ctx_nk200: str = "",
    ) -> dict[str, Any]:
        """해외주식 잔고 — GET trading/inquire-balance, TR TTTS3012R / VTTS3012R."""
        params = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "OVRS_EXCG_CD": ovrs_excg_cd,
            "TR_CRCY_CD": tr_crcy_cd,
            "CTX_AREA_FK200": ctx_fk200,
            "CTX_AREA_NK200": ctx_nk200,
        }
        tr_id = self._resolve_tr_id(
            paper_tr_id=self.overseas_tr_ids.balance_paper,
            live_tr_id=self.overseas_tr_ids.balance_live,
        )
        path = self.overseas_paths.inquire_balance
        allow = frozenset({"CTX_AREA_FK200", "CTX_AREA_NK200"})
        payload = self._get(path, params=params, tr_id=tr_id, allow_empty_param_keys=allow)
        self._validate_kis_business_success(
            payload,
            method="GET",
            path=path,
            tr_id=tr_id,
            params=params,
        )
        return payload

    def get_overseas_inquire_nccs(
        self,
        *,
        account_no: str,
        account_product_code: str,
        ovrs_excg_cd: str,
        sort_sqn: str = "DS",
        ctx_fk200: str = "",
        ctx_nk200: str = "",
    ) -> dict[str, Any]:
        """해외주식 미체결내역 — GET trading/inquire-nccs, TR TTTS3018R / VTTS3018R."""
        params = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "OVRS_EXCG_CD": ovrs_excg_cd,
            "SORT_SQN": sort_sqn,
            "CTX_AREA_FK200": ctx_fk200,
            "CTX_AREA_NK200": ctx_nk200,
        }
        tr_id = self._resolve_tr_id(
            paper_tr_id=self.overseas_tr_ids.nccs_paper,
            live_tr_id=self.overseas_tr_ids.nccs_live,
        )
        path = self.overseas_paths.inquire_nccs
        allow = frozenset({"CTX_AREA_FK200", "CTX_AREA_NK200"})
        payload = self._get(path, params=params, tr_id=tr_id, allow_empty_param_keys=allow)
        self._validate_kis_business_success(payload, method="GET", path=path, tr_id=tr_id, params=params)
        return payload

    def get_overseas_inquire_ccnl(
        self,
        *,
        account_no: str,
        account_product_code: str,
        pdno: str,
        ord_strt_dt: str,
        ord_end_dt: str,
        sll_buy_dvsn: str,
        ccld_nccs_dvsn: str,
        ovrs_excg_cd: str,
        sort_sqn: str,
        ord_dt: str = "",
        ord_gno_brno: str = "",
        odno: str = "",
        ctx_nk200: str = "",
        ctx_fk200: str = "",
    ) -> dict[str, Any]:
        """해외주식 주문체결내역 — GET trading/inquire-ccnl, TR TTTS3035R / VTTS3035R."""
        params = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "PDNO": pdno,
            "ORD_STRT_DT": ord_strt_dt,
            "ORD_END_DT": ord_end_dt,
            "SLL_BUY_DVSN": sll_buy_dvsn,
            "CCLD_NCCS_DVSN": ccld_nccs_dvsn,
            "OVRS_EXCG_CD": ovrs_excg_cd,
            "SORT_SQN": sort_sqn,
            "ORD_DT": ord_dt,
            "ORD_GNO_BRNO": ord_gno_brno,
            "ODNO": odno,
            "CTX_AREA_NK200": ctx_nk200,
            "CTX_AREA_FK200": ctx_fk200,
        }
        tr_id = self._resolve_tr_id(
            paper_tr_id=self.overseas_tr_ids.ccnl_paper,
            live_tr_id=self.overseas_tr_ids.ccnl_live,
        )
        path = self.overseas_paths.inquire_ccnl
        allow = frozenset(
            {
                "CTX_AREA_NK200",
                "CTX_AREA_FK200",
                "ORD_DT",
                "ORD_GNO_BRNO",
                "ODNO",
            }
        )
        payload = self._get(path, params=params, tr_id=tr_id, allow_empty_param_keys=allow)
        self._validate_kis_business_success(payload, method="GET", path=path, tr_id=tr_id, params=params)
        return payload

    def place_overseas_order(
        self,
        *,
        account_no: str,
        account_product_code: str,
        ovrs_excg_cd: str,
        pdno: str,
        ord_qty: str,
        ovrs_ord_unpr: str,
        ord_dv: str,
        ctac_tlno: str = "",
        mgco_aptm_odno: str = "",
        ord_svr_dvsn_cd: str = "0",
        ord_dvsn: str = "00",
    ) -> dict[str, Any]:
        """
        해외주식 주문 — POST trading/order.
        미국 NASD/NYSE/AMEX: 매수 TTTT1002U·매도 TTTT1006U (모의 V...).
        공식 예제 order() 본문 필드와 동일.
        """
        self._ensure_order_execution_allowed()
        side = ord_dv.lower().strip()
        if side == "buy":
            if ovrs_excg_cd not in ("NASD", "NYSE", "AMEX"):
                raise KISClientError(f"US buy order: unsupported OVRS_EXCG_CD={ovrs_excg_cd}")
            tr_id = self._resolve_tr_id(
                paper_tr_id=self.overseas_tr_ids.us_buy_paper,
                live_tr_id=self.overseas_tr_ids.us_buy_live,
            )
            sll_type = ""
        elif side == "sell":
            if ovrs_excg_cd not in ("NASD", "NYSE", "AMEX"):
                raise KISClientError(f"US sell order: unsupported OVRS_EXCG_CD={ovrs_excg_cd}")
            tr_id = self._resolve_tr_id(
                paper_tr_id=self.overseas_tr_ids.us_sell_paper,
                live_tr_id=self.overseas_tr_ids.us_sell_live,
            )
            sll_type = "00"
        else:
            raise KISClientError("ord_dv must be 'buy' or 'sell'")

        body = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "OVRS_EXCG_CD": ovrs_excg_cd,
            "PDNO": pdno,
            "ORD_QTY": ord_qty,
            "OVRS_ORD_UNPR": ovrs_ord_unpr,
            "CTAC_TLNO": ctac_tlno,
            "MGCO_APTM_ODNO": mgco_aptm_odno,
            "SLL_TYPE": sll_type,
            "ORD_SVR_DVSN_CD": ord_svr_dvsn_cd,
            "ORD_DVSN": ord_dvsn,
        }
        path = self.overseas_paths.order
        payload = self._post(path, data=body, tr_id=tr_id)
        self._validate_kis_business_success(payload, method="POST", path=path, tr_id=tr_id, data=body)
        return payload

    def cancel_overseas_order(
        self,
        *,
        account_no: str,
        account_product_code: str,
        ovrs_excg_cd: str,
        pdno: str,
        orgn_odno: str,
        rvse_cncl_dvsn_cd: str,
        ord_qty: str,
        ovrs_ord_unpr: str,
        mgco_aptm_odno: str = "",
        ord_svr_dvsn_cd: str = "0",
    ) -> dict[str, Any]:
        """해외주식 정정취소주문 — POST order-rvsecncl, TR TTTT1004U / VTTT1004U."""
        self._ensure_order_execution_allowed()
        tr_id = self._resolve_tr_id(
            paper_tr_id=self.overseas_tr_ids.us_order_rvsecncl_paper,
            live_tr_id=self.overseas_tr_ids.us_order_rvsecncl_live,
        )
        body = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "OVRS_EXCG_CD": ovrs_excg_cd,
            "PDNO": pdno,
            "ORGN_ODNO": orgn_odno,
            "RVSE_CNCL_DVSN_CD": rvse_cncl_dvsn_cd,
            "ORD_QTY": ord_qty,
            "OVRS_ORD_UNPR": ovrs_ord_unpr,
            "MGCO_APTM_ODNO": mgco_aptm_odno,
            "ORD_SVR_DVSN_CD": ord_svr_dvsn_cd,
        }
        path = self.overseas_paths.order_rvsecncl
        payload = self._post(path, data=body, tr_id=tr_id)
        self._validate_kis_business_success(payload, method="POST", path=path, tr_id=tr_id, data=body)
        return payload
