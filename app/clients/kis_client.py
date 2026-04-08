from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from datetime import datetime
from typing import Any, Callable

import requests

from app.clients.kis_contract import DomesticStockPaths, DomesticTrIds, is_paper_host, pick_tr
from app.clients.kis_parsers import business_error_detail, rt_cd_ok


class KISClientError(RuntimeError):
    pass


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
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=data,
                    headers=headers,
                    timeout=self.timeout_sec,
                )
                self._raise_for_status(response, method=method, url=url)
                return self._safe_json(response)
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                sleep_s = self.retry_backoff_sec * (2**attempt)
                self.logger.warning(
                    "KIS request retrying due to network/timeout",
                    extra={"method": method, "path": path, "attempt": attempt + 1},
                )
                time.sleep(sleep_s)
            except KISClientError:
                raise

        raise KISClientError(
            f"KIS request failed after {self.max_retries + 1} attempts: method={method} path={path}"
        ) from last_error

    def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        tr_id: str | None = None,
        bearer_token: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            path,
            params=params,
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

    def _raise_for_status(self, response: requests.Response, *, method: str, url: str) -> None:
        if response.status_code < 400:
            return
        status = response.status_code
        body_preview = response.text[:400] if response.text else ""
        self.logger.error(
            "KIS HTTP error",
            extra={"status_code": status, "method": method, "url": url.split("?")[0]},
        )
        raise KISClientError(f"KIS HTTP {status} {method} — 응답 본문 일부: {body_preview}")

    @staticmethod
    def _safe_json(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise KISClientError("KIS response is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise KISClientError("KIS response JSON payload is not object")
        return payload

    @staticmethod
    def _validate_kis_business_success(payload: dict[str, Any]) -> None:
        if rt_cd_ok(payload):
            return
        raise KISClientError(f"KIS business error: {business_error_detail(payload)}")

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
        params = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
        }
        tr_id = self._resolve_tr_id(paper_tr_id=self.tr_ids.balance_paper, live_tr_id=self.tr_ids.balance_live)
        payload = self._get(self.endpoints.get_balance, params=params, tr_id=tr_id)
        self._validate_kis_business_success(payload)
        return payload

    def get_quote(self, symbol: str) -> dict[str, Any]:
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
        }
        tr_id = self._resolve_tr_id(paper_tr_id=self.tr_ids.quote_paper, live_tr_id=self.tr_ids.quote_live)
        payload = self._get(self.endpoints.get_quote, params=params, tr_id=tr_id)
        self._validate_kis_business_success(payload)
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
        ORD_DVSN: 00 지정가, 01 시장가 — 시장가 조회 시 ORD_UNPR 는 공란.
        """
        ord_unpr = "" if order_div == "01" or order_price is None else str(int(order_price))
        params: dict[str, Any] = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "PDNO": symbol,
            "ORD_UNPR": ord_unpr,
            "ORD_DVSN": order_div,
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        tr_id = self._resolve_tr_id(paper_tr_id=self.tr_ids.psbl_order_paper, live_tr_id=self.tr_ids.psbl_order_live)
        payload = self._get(self.endpoints.inquire_psbl_order, params=params, tr_id=tr_id)
        self._validate_kis_business_success(payload)
        return payload

    def inquire_nccs(
        self,
        *,
        account_no: str,
        account_product_code: str,
        symbol: str = "",
    ) -> dict[str, Any]:
        """미체결 내역 조회."""
        params = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "INQR_DVSN": "00",
            "PDNO": symbol,
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        tr_id = self._resolve_tr_id(paper_tr_id=self.tr_ids.nccs_paper, live_tr_id=self.tr_ids.nccs_live)
        payload = self._get(self.endpoints.inquire_nccs, params=params, tr_id=tr_id)
        self._validate_kis_business_success(payload)
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
        """
        today = datetime.now().strftime("%Y%m%d")
        start = start_yyyymmdd or today
        end = end_yyyymmdd or today
        params = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "INQR_STRT_DT": start,
            "INQR_END_DT": end,
            "SLL_BUY_DVSN_CD": sell_buy_code,
            "INQR_DVSN": "00",
            "PDNO": symbol,
            "CCLD_DVSN": ccld_div,
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "INQR_DVSN_2": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        tr_id = self._resolve_tr_id(paper_tr_id=self.tr_ids.daily_ccld_paper, live_tr_id=self.tr_ids.daily_ccld_live)
        payload = self._get(self.endpoints.inquire_daily_ccld, params=params, tr_id=tr_id)
        self._validate_kis_business_success(payload)
        return payload

    def request_hashkey(self, body: dict[str, Any]) -> str:
        payload = self._post(self.endpoints.hashkey, data=body, tr_id=None)
        if not rt_cd_ok(payload):
            raise KISClientError(f"hashkey issuance failed: {business_error_detail(payload)}")
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
        self._validate_kis_business_success(payload)
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
        self._validate_kis_business_success(payload)
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
        self._validate_kis_business_success(payload)
        return payload
