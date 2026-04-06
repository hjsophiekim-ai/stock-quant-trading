from dataclasses import dataclass, field
import logging
import time
from typing import Any, Callable

import requests


class KISClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class KISEndpoints:
    get_balance: str = "/uapi/domestic-stock/v1/trading/inquire-balance"
    get_quote: str = "/uapi/domestic-stock/v1/quotations/inquire-price"
    get_positions: str = "/uapi/domestic-stock/v1/trading/inquire-balance"
    place_order: str = "/uapi/domestic-stock/v1/trading/order-cash"
    cancel_order: str = "/uapi/domestic-stock/v1/trading/order-rvsecncl"


@dataclass
class KISClient:
    base_url: str
    timeout_sec: int = 10
    max_retries: int = 2
    retry_backoff_sec: float = 0.4
    token_provider: Callable[[], str] | None = None
    app_key: str | None = None
    app_secret: str | None = None
    endpoints: KISEndpoints = field(default_factory=KISEndpoints)
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
        return paper_tr_id if self.base_url.startswith("https://openapivts") else live_tr_id

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
                    extra={"method": method, "url": url, "attempt": attempt + 1},
                )
                time.sleep(sleep_s)
            except KISClientError:
                raise

        raise KISClientError(f"KIS request failed after retries: method={method} path={path}") from last_error

    def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        tr_id: str | None = None,
        bearer_token: str | None = None,
    ) -> dict[str, Any]:
        return self._request("GET", path, params=params, tr_id=tr_id, bearer_token=bearer_token)

    def _post(
        self,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        tr_id: str | None = None,
        bearer_token: str | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", path, data=data, tr_id=tr_id, bearer_token=bearer_token)

    def _raise_for_status(self, response: requests.Response, *, method: str, url: str) -> None:
        if response.status_code < 400:
            return
        status = response.status_code
        body_preview = response.text[:400] if response.text else ""
        # Do not log auth headers or secrets.
        self.logger.error(
            "KIS API request failed",
            extra={"status_code": status, "method": method, "url": url},
        )
        raise KISClientError(f"KIS API error status={status}, method={method}, url={url}, body={body_preview}")

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
        rt_cd = str(payload.get("rt_cd", "0"))
        if rt_cd not in {"0", ""}:
            msg = str(payload.get("msg1", "Unknown KIS API error"))
            raise KISClientError(f"KIS business error: {msg}")

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
        tr_id = self._resolve_tr_id(paper_tr_id="VTTC8434R", live_tr_id="TTTC8434R")
        payload = self._get(self.endpoints.get_balance, params=params, tr_id=tr_id)
        self._validate_kis_business_success(payload)
        return payload

    def get_quote(self, symbol: str) -> dict[str, Any]:
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
        }
        tr_id = self._resolve_tr_id(paper_tr_id="FHKST01010100", live_tr_id="FHKST01010100")
        payload = self._get(self.endpoints.get_quote, params=params, tr_id=tr_id)
        self._validate_kis_business_success(payload)
        return payload

    def get_positions(self, account_no: str, account_product_code: str) -> dict[str, Any]:
        # KIS balance API already returns position list in `output1`; keep alias method for readability.
        return self.get_balance(account_no=account_no, account_product_code=account_product_code)

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
        body = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "PDNO": symbol,
            "ORD_DVSN": "01",  # TODO: Confirm order type code.
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(price),
            # TODO: Map side to KIS buy/sell TR ID and fields.
        }
        tr_id = "TODO_BUY_OR_SELL_TR_ID" if side.lower() == "buy" else "TODO_BUY_OR_SELL_TR_ID"
        return self._post(self.endpoints.place_order, data=body, tr_id=tr_id)

    def cancel_order(
        self,
        *,
        account_no: str,
        account_product_code: str,
        original_order_no: str,
        quantity: int,
        symbol: str,
    ) -> dict[str, Any]:
        body = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product_code,
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO": original_order_no,
            "ORD_DVSN": "01",
            "RVSE_CNCL_DVSN_CD": "02",  # 01:정정, 02:취소
            "ORD_QTY": str(quantity),
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "N",
            "PDNO": symbol,
        }
        # TODO: Set proper TR ID for paper/live mode.
        return self._post(self.endpoints.cancel_order, data=body, tr_id="TODO_CANCEL_TR_ID")
