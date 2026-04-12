from __future__ import annotations

from dataclasses import dataclass, field
import logging
from datetime import datetime, timezone
from typing import Any

from app.brokers.base_broker import BaseBroker, Fill, OpenOrder, PositionView
from app.clients.kis_client import KISClient, KISClientError
from app.clients.kis_parsers import (
    normalized_fills_from_ccld_payload,
    open_orders_from_nccs_payload,
    parse_kis_ord_datetime_to_utc,
)
from app.clients.kis_mask import format_masked_payload_json
from app.orders.models import OrderRequest, OrderResult, OrderStatus


def _split_composite_order_id(order_id: str) -> tuple[str, str]:
    if "|" in order_id:
        org, odno = order_id.split("|", 1)
        return org.strip(), odno.strip()
    return "", order_id.strip()


@dataclass
class KisPaperBroker(BaseBroker):
    """
    Executes orders against the KIS **모의투자** REST host only (`openapivts`).
    잔고/포지션은 KIS 조회 API를 사용합니다. 실전 도메인과는 분리됩니다.
    """

    kis_client: KISClient
    account_no: str
    account_product_code: str
    # SchedulerJobs 일일 리포트용 기준(실제 모의 잔고와 다를 수 있음 — 정확 손익은 KIS/포트폴리오 sync 권장).
    initial_cash: float = 10_000_000.0
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("app.brokers.kis_paper"))
    _order_symbols: dict[str, str] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        base = (self.kis_client.base_url or "").rstrip("/")
        if not base.startswith("https://openapivts"):
            raise ValueError(
                "KisPaperBroker는 모의투자 API 호스트(https://openapivts...)에서만 동작합니다. "
                "실전 주문 경로와 혼합하지 마세요."
            )

    def get_cash(self) -> float:
        payload = self.kis_client.get_balance(self.account_no, self.account_product_code)
        return _extract_ord_psbl_cash(payload)

    def get_positions(self) -> list[PositionView]:
        payload = self.kis_client.get_positions(self.account_no, self.account_product_code)
        return _extract_positions(payload)

    def place_order(self, order: OrderRequest) -> OrderResult:
        if order.quantity <= 0:
            return OrderResult(order_id="", accepted=False, message="Quantity must be positive", status=OrderStatus.FAILED)

        price_int = int(order.price) if order.price is not None and order.price > 0 else 0
        try:
            payload = self.kis_client.place_order(
                account_no=self.account_no,
                account_product_code=self.account_product_code,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                price=price_int,
            )
        except KISClientError as exc:
            self.logger.warning("KIS mock order rejected: %s", exc)
            return OrderResult(order_id="", accepted=False, message=str(exc), status=OrderStatus.FAILED)

        oid = _format_composite_order_id(payload)
        if oid:
            self._order_symbols[oid] = order.symbol
        masked = format_masked_payload_json(payload)
        self.logger.info(
            "KIS mock order submitted side=%s symbol=%s qty=%s price_int=%s id=%s masked_response=%s",
            order.side,
            order.symbol,
            order.quantity,
            price_int,
            oid,
            masked[:500],
        )
        return OrderResult(
            order_id=oid,
            accepted=True,
            message="KIS mock order submitted (체결 여부는 잔고/미체결 조회로 확인)",
            status=OrderStatus.SUBMITTED,
            metadata={"masked_broker_response": masked},
        )

    def cancel_order(self, order_id: str) -> OrderResult:
        org, odno = _split_composite_order_id(order_id)
        if not odno:
            return OrderResult(order_id=order_id, accepted=False, message="Invalid order id", status=OrderStatus.FAILED)
        symbol = self._order_symbols.get(order_id, "")
        try:
            self.kis_client.cancel_order(
                account_no=self.account_no,
                account_product_code=self.account_product_code,
                original_order_no=odno,
                quantity=0,
                symbol=symbol,
                krx_fwdg_ord_orgno=org,
                cancel_all=True,
            )
        except KISClientError as exc:
            return OrderResult(order_id=order_id, accepted=False, message=str(exc), status=OrderStatus.FAILED)
        return OrderResult(order_id=order_id, accepted=True, message="KIS mock cancel submitted", status=OrderStatus.CANCELLED)

    def get_open_orders(self) -> list[OpenOrder]:
        try:
            payload = self.kis_client.inquire_nccs(
                account_no=self.account_no,
                account_product_code=self.account_product_code,
                symbol="",
            )
        except KISClientError as exc:
            self.logger.warning("inquire_nccs failed: %s", exc)
            return []
        orders = open_orders_from_nccs_payload(payload)
        for o in orders:
            self._order_symbols[o.order_id] = o.symbol
        return orders

    def get_fills(self) -> list[Fill]:
        """당일 체결 분(CCLD_DVSN=01). 기간·전략 매핑은 backend portfolio sync_engine 사용."""
        try:
            payload = self.kis_client.inquire_daily_ccld(
                account_no=self.account_no,
                account_product_code=self.account_product_code,
                symbol="",
                sell_buy_code="00",
                ccld_div="01",
            )
        except KISClientError as exc:
            self.logger.warning("inquire_daily_ccld failed: %s", exc)
            return []
        rows = normalized_fills_from_ccld_payload(payload)
        out: list[Fill] = []
        for r in rows:
            odt = str(r.get("ord_dt") or "")
            otm = str(r.get("ord_tmd") or "")
            filled_at = parse_kis_ord_datetime_to_utc(odt, otm)
            oid = str(r.get("order_no") or "")
            out.append(
                Fill(
                    fill_id=str(r.get("exec_id") or oid),
                    order_id=oid,
                    symbol=str(r.get("symbol") or ""),
                    side="sell" if str(r.get("side")) == "sell" else "buy",
                    quantity=int(r.get("quantity") or 0),
                    fill_price=float(r.get("price") or 0.0),
                    filled_at=filled_at,
                )
            )
        return out


def _format_composite_order_id(payload: dict[str, Any]) -> str:
    output = payload.get("output")
    odno = ""
    org = ""
    if isinstance(output, dict):
        odno = str(output.get("ODNO") or output.get("odno") or "").strip()
        org = str(output.get("KRX_FWDG_ORD_ORGNO") or output.get("krx_fwdg_ord_orgno") or "").strip()
    if org and odno:
        return f"{org}|{odno}"
    return odno


def _extract_ord_psbl_cash(payload: dict[str, Any]) -> float:
    out = payload.get("output")
    if isinstance(out, dict):
        for key in ("ord_psbl_cash", "nrcvb_buy_amt", "dnca_tot_amt"):
            raw = out.get(key)
            if raw is not None and str(raw).strip() != "":
                try:
                    return float(raw)
                except (TypeError, ValueError):
                    continue
    return _extract_cash_fallback_output2(payload)


def _extract_cash_fallback_output2(payload: dict[str, Any]) -> float:
    output2 = payload.get("output2")
    if isinstance(output2, list) and output2:
        candidate = output2[0].get("tot_evlu_amt") or output2[0].get("dnca_tot_amt")
        try:
            return float(candidate)
        except (TypeError, ValueError):
            return 0.0
    if isinstance(output2, dict):
        candidate = output2.get("tot_evlu_amt") or output2.get("dnca_tot_amt")
        try:
            return float(candidate)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _extract_positions(payload: dict[str, Any]) -> list[PositionView]:
    raw = payload.get("output1")
    if not isinstance(raw, list):
        return []
    positions: list[PositionView] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("pdno", ""))
        try:
            qty = int(float(row.get("hldg_qty", 0)))
            avg = float(row.get("pchs_avg_pric", 0.0))
        except (TypeError, ValueError):
            continue
        if symbol and qty > 0:
            positions.append(PositionView(symbol=symbol, quantity=qty, average_price=avg))
    return positions
