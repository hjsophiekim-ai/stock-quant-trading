from __future__ import annotations

from dataclasses import dataclass, field
import logging
from datetime import datetime, timezone
from typing import Any

from app.brokers.base_broker import BaseBroker, Fill, OpenOrder, OrderRequest, OrderResult, OrderStatus, PositionView
from app.clients.kis_client import KISClient, KISClientError
from app.clients.kis_mask import format_masked_payload_json
from app.clients.kis_parsers import (
    fills_from_overseas_ccnl_payload,
    open_orders_from_overseas_nccs_payload,
    overseas_balance_cash_usd,
    positions_from_overseas_balance_payload,
)


def _us_symbol_to_ovrs_excg_cd(symbol: str, hint: str | None) -> str:
    """주문·잔고 API용 OVRS_EXCG_CD. hint 가 있으면 우선 (잔고 output1 의 ovrs_excg_cd)."""
    if hint and str(hint).strip().upper() in ("NASD", "NYSE", "AMEX"):
        return str(hint).strip().upper()
    return "NASD"


@dataclass
class KisUsPaperBroker(BaseBroker):
    """
    KIS 모의투자(openapivts) 해외주식(미국) REST.
    경로·TR·필드명: koreainvestment/open-trading-api `overseas_stock_functions.py` 기준.
    """

    kis_client: KISClient
    account_no: str
    account_product_code: str
    default_ovrs_excg_cd: str = "NASD"
    tr_crcy_cd: str = "USD"
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("app.brokers.kis_us_paper"))
    _symbol_ovrs: dict[str, str] = field(init=False, default_factory=dict)
    _order_symbols: dict[str, str] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        base = (self.kis_client.base_url or "").rstrip("/")
        if not base.startswith("https://openapivts"):
            raise ValueError("KisUsPaperBroker는 모의투자 API 호스트(https://openapivts...)에서만 동작합니다.")

    def _refresh_symbol_map_from_balance(self) -> None:
        try:
            payload = self.kis_client.get_overseas_inquire_balance(
                account_no=self.account_no,
                account_product_code=self.account_product_code,
                ovrs_excg_cd=self.default_ovrs_excg_cd,
                tr_crcy_cd=self.tr_crcy_cd,
            )
        except KISClientError:
            return
        from app.clients.kis_parsers import output1_rows, _row_pick

        for row in output1_rows(payload):
            sym = str(_row_pick(row, "ovrs_pdno", "OVRS_PDNO", "pdno", "PDNO") or "").strip().upper()
            exc = str(_row_pick(row, "ovrs_excg_cd", "OVRS_EXCG_CD") or "").strip().upper()
            if sym and exc in ("NASD", "NYSE", "AMEX"):
                self._symbol_ovrs[sym] = exc

    def get_cash(self) -> float:
        payload = self.kis_client.get_overseas_inquire_balance(
            account_no=self.account_no,
            account_product_code=self.account_product_code,
            ovrs_excg_cd=self.default_ovrs_excg_cd,
            tr_crcy_cd=self.tr_crcy_cd,
        )
        return overseas_balance_cash_usd(payload)

    def get_positions(self) -> list[PositionView]:
        payload = self.kis_client.get_overseas_inquire_balance(
            account_no=self.account_no,
            account_product_code=self.account_product_code,
            ovrs_excg_cd=self.default_ovrs_excg_cd,
            tr_crcy_cd=self.tr_crcy_cd,
        )
        pos = positions_from_overseas_balance_payload(payload)
        for p in pos:
            self._symbol_ovrs.setdefault(p.symbol, self.default_ovrs_excg_cd)
        return pos

    def place_order(self, order: OrderRequest) -> OrderResult:
        if order.quantity <= 0:
            return OrderResult(order_id="", accepted=False, message="Quantity must be positive", status=OrderStatus.FAILED)
        sym = str(order.symbol or "").strip().upper()
        ovrs = _us_symbol_to_ovrs_excg_cd(sym, self._symbol_ovrs.get(sym))
        unpr = f"{float(order.price):.2f}" if order.price and float(order.price) > 0 else "0"
        ord_dvsn = "00" if order.price and float(order.price) > 0 else "00"
        if unpr == "0" or float(unpr) <= 0:
            return OrderResult(
                order_id="",
                accepted=False,
                message="US overseas order requires positive limit price (ord_dvsn 00, OVRS_ORD_UNPR) per KIS sample.",
                status=OrderStatus.FAILED,
            )
        try:
            payload = self.kis_client.place_overseas_order(
                account_no=self.account_no,
                account_product_code=self.account_product_code,
                ovrs_excg_cd=ovrs,
                pdno=sym,
                ord_qty=str(int(order.quantity)),
                ovrs_ord_unpr=unpr,
                ord_dv=order.side,
                ctac_tlno="",
                mgco_aptm_odno="",
                ord_svr_dvsn_cd="0",
                ord_dvsn=ord_dvsn,
            )
        except KISClientError as exc:
            self.logger.warning("KIS US mock order rejected: %s", exc)
            return OrderResult(order_id="", accepted=False, message=str(exc), status=OrderStatus.FAILED)

        output = payload.get("output")
        odno = ""
        if isinstance(output, dict):
            odno = str(output.get("ODNO") or output.get("odno") or "").strip()
        oid = odno
        masked = format_masked_payload_json(payload)
        self.logger.info(
            "KIS US mock order submitted side=%s symbol=%s qty=%s price=%s id=%s masked=%s",
            order.side,
            sym,
            order.quantity,
            unpr,
            oid,
            masked[:500],
        )
        if oid:
            self._order_symbols[oid] = sym
        return OrderResult(
            order_id=oid,
            accepted=True,
            message="KIS overseas mock order submitted",
            status=OrderStatus.SUBMITTED,
            metadata={"masked_broker_response": masked},
        )

    def cancel_order(self, order_id: str) -> OrderResult:
        if not order_id:
            return OrderResult(order_id=order_id, accepted=False, message="Invalid order id", status=OrderStatus.FAILED)
        sym = self._order_symbols.get(order_id, "")
        ovrs = self.default_ovrs_excg_cd
        if not sym:
            for o in self.get_open_orders():
                if o.order_id == order_id:
                    sym = o.symbol
                    ovrs = _us_symbol_to_ovrs_excg_cd(sym, self._symbol_ovrs.get(sym))
                    break
        if not sym:
            return OrderResult(order_id=order_id, accepted=False, message="Unknown symbol for cancel", status=OrderStatus.FAILED)
        try:
            self.kis_client.cancel_overseas_order(
                account_no=self.account_no,
                account_product_code=self.account_product_code,
                ovrs_excg_cd=ovrs,
                pdno=sym,
                orgn_odno=order_id,
                rvse_cncl_dvsn_cd="02",
                ord_qty="0",
                ovrs_ord_unpr="0",
            )
        except KISClientError as exc:
            return OrderResult(order_id=order_id, accepted=False, message=str(exc), status=OrderStatus.FAILED)
        return OrderResult(order_id=order_id, accepted=True, message="KIS overseas cancel submitted", status=OrderStatus.CANCELLED)

    def get_open_orders(self) -> list[OpenOrder]:
        try:
            payload = self.kis_client.get_overseas_inquire_nccs(
                account_no=self.account_no,
                account_product_code=self.account_product_code,
                ovrs_excg_cd=self.default_ovrs_excg_cd,
            )
        except KISClientError as exc:
            self.logger.warning("overseas inquire_nccs failed: %s", exc)
            return []
        return open_orders_from_overseas_nccs_payload(payload)

    def get_fills(self) -> list[Fill]:
        from datetime import datetime as dt

        today = dt.now(timezone.utc).strftime("%Y%m%d")
        try:
            payload = self.kis_client.get_overseas_inquire_ccnl(
                account_no=self.account_no,
                account_product_code=self.account_product_code,
                pdno="",
                ord_strt_dt=today,
                ord_end_dt=today,
                sll_buy_dvsn="00",
                ccld_nccs_dvsn="01",
                ovrs_excg_cd=self.default_ovrs_excg_cd,
                sort_sqn="DS",
            )
        except KISClientError as exc:
            self.logger.warning("overseas inquire_ccnl failed: %s", exc)
            return []
        return fills_from_overseas_ccnl_payload(payload)
