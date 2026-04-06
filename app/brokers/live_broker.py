from dataclasses import dataclass
import os
from typing import Any

from app.brokers.base_broker import BaseBroker, Fill, OpenOrder, PositionView
from app.clients.kis_client import KISClient
from app.orders.models import OrderRequest, OrderResult


@dataclass
class LiveBroker(BaseBroker):
    kis_client: KISClient
    account_no: str
    account_product_code: str
    live_trading_enabled: bool = False

    @classmethod
    def from_env(cls, kis_client: KISClient, account_no: str, account_product_code: str) -> "LiveBroker":
        enabled = os.getenv("LIVE_TRADING", "false").lower() == "true"
        return cls(
            kis_client=kis_client,
            account_no=account_no,
            account_product_code=account_product_code,
            live_trading_enabled=enabled,
        )

    def get_cash(self) -> float:
        payload = self.kis_client.get_balance(self.account_no, self.account_product_code)
        return self._extract_cash(payload)

    def get_positions(self) -> list[PositionView]:
        payload = self.kis_client.get_positions(self.account_no, self.account_product_code)
        return self._extract_positions(payload)

    def place_order(self, order: OrderRequest) -> OrderResult:
        if not self.live_trading_enabled:
            return OrderResult(order_id="", accepted=False, message="Live trading is disabled (LIVE_TRADING!=true)")

        price = int(order.price) if order.price is not None else 0
        response = self.kis_client.place_order(
            account_no=self.account_no,
            account_product_code=self.account_product_code,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
        )
        order_id = self._extract_order_id(response)
        return OrderResult(order_id=order_id, accepted=True, message="Live order submitted")

    def cancel_order(self, order_id: str) -> OrderResult:
        if not self.live_trading_enabled:
            return OrderResult(order_id=order_id, accepted=False, message="Live trading is disabled (LIVE_TRADING!=true)")
        response = self.kis_client.cancel_order(
            account_no=self.account_no,
            account_product_code=self.account_product_code,
            original_order_no=order_id,
            quantity=0,
            symbol="",
        )
        canceled_order_id = self._extract_order_id(response, fallback=order_id)
        return OrderResult(order_id=canceled_order_id, accepted=True, message="Live order cancel submitted")

    def get_open_orders(self) -> list[OpenOrder]:
        # KIS open-order endpoint wiring can be added in KISClient later.
        return []

    def get_fills(self) -> list[Fill]:
        # KIS fill-history endpoint wiring can be added in KISClient later.
        return []

    @staticmethod
    def _extract_cash(payload: dict[str, Any]) -> float:
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

    @staticmethod
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

    @staticmethod
    def _extract_order_id(payload: dict[str, Any], fallback: str = "") -> str:
        output = payload.get("output")
        if isinstance(output, dict):
            candidate = output.get("ODNO") or output.get("odno")
            if isinstance(candidate, str) and candidate:
                return candidate
        for key in ("ODNO", "odno", "order_id"):
            candidate = payload.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        return fallback
