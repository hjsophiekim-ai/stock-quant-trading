from __future__ import annotations

from dataclasses import dataclass, field
import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable

import requests

from app.clients.kis_contract import DomesticStockPaths, DomesticTrIds, is_paper_host, pick_tr
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
                    f"KIS HTTP {response.status_code} {method} — 응답 본문 일부: {body_preview}",
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
    ) -> dict[str, Any]:
        q = prune_empty_get_params(params)
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
            f"KIS HTTP {status} {method} — 응답 본문 일부: {body_preview}",
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
        # OFL_YN 등 빈 기본값은 넣지 않음 — prune으로 제거되나 아예 생략이 명확함
        params = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "AFHR_FLPR_YN": "N",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
        }
        tr_id = self._resolve_tr_id(paper_tr_id=self.tr_ids.balance_paper, live_tr_id=self.tr_ids.balance_live)
        payload = self._get(self.endpoints.get_balance, params=params, tr_id=tr_id)
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
    ) -> dict[str, Any]:
        """
        매수가능조회 (주문가능현금·가능수량 등).
        ORD_DVSN: 00 지정가, 01 시장가.
        - 시장가(01): ORD_UNPR 키 자체를 보내지 않음(빈 문자열 GET 금지).
        - 지정가(00): ORD_UNPR 에 가격 문자열 전송.
        - 첫 페이지: CTX_AREA_* 키 없음(연속조회 시에만 API 응답 ctx로 채움).
        """
        params: dict[str, Any] = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "PDNO": symbol,
            "ORD_DVSN": order_div,
        }
        if order_div != "01" and order_price is not None:
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
        - PDNO: 종목 지정 시만 전송(전체 조회는 키 생략).
        - ORD_GNO_BRNO/ODNO: 특정 주문 조회 시에만; 첫 페이지는 미전송.
        - CTX_AREA_*: 연속조회 시에만; 첫 페이지는 미전송.
        """
        params: dict[str, Any] = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "INQR_DVSN": "00",
        }
        if symbol and str(symbol).strip():
            params["PDNO"] = str(symbol).strip()
        tr_id = self._resolve_tr_id(paper_tr_id=self.tr_ids.nccs_paper, live_tr_id=self.tr_ids.nccs_live)
        payload = self._get(self.endpoints.inquire_nccs, params=params, tr_id=tr_id)
        self._validate_kis_business_success(
            payload,
            method="GET",
            path=self.endpoints.inquire_nccs,
            tr_id=tr_id,
            params=prune_empty_get_params(params),
        )
        return payload

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
