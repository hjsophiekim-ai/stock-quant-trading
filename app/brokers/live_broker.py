from dataclasses import dataclass
import logging
from typing import Any

from app.brokers.base_broker import BaseBroker, Fill, OpenOrder, PositionView
from app.clients.kis_client import KISClient
from app.config import Settings, get_settings
from app.orders.models import OrderRequest, OrderResult


@dataclass
class LiveBroker(BaseBroker):
    kis_client: KISClient
    account_no: str
    account_product_code: str
    live_trading_enabled: bool = False
    live_trading_confirm: bool = False
    trading_mode: str = "paper"
    dry_run_log_enabled: bool = True
    logger: logging.Logger = logging.getLogger("app.brokers.live_broker")

    @classmethod
    def from_env(cls, kis_client: KISClient, account_no: str, account_product_code: str, settings: Settings | None = None) -> "LiveBroker":
        cfg = settings or get_settings()
        return cls(
            kis_client=kis_client,
            account_no=account_no,
            account_product_code=account_product_code,
            live_trading_enabled=cfg.resolved_live_trading_enabled,
            live_trading_confirm=cfg.live_trading_confirm,
            trading_mode=cfg.trading_mode,
            dry_run_log_enabled=cfg.live_order_dry_run_log,
        )

    def get_cash(self) -> float:
        payload = self.kis_client.get_balance(self.account_no, self.account_product_code)
        return self._extract_cash(payload)

    def get_positions(self) -> list[PositionView]:
        payload = self.kis_client.get_positions(self.account_no, self.account_product_code)
        return self._extract_positions(payload)

    def place_order(self, order: OrderRequest) -> OrderResult:
        guard = self._validate_live_order_guard()
        if guard is not None:
            return guard
        if self.dry_run_log_enabled:
            self._log_dry_run(order)

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
        guard = self._validate_live_order_guard()
        if guard is not None:
            return OrderResult(order_id=order_id, accepted=False, message=guard.message)
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

    def _validate_live_order_guard(self) -> OrderResult | None:
        if self.trading_mode != "live":
            return OrderResult(order_id="", accepted=False, message="Live order blocked: TRADING_MODE is not live")
        if not self.live_trading_enabled:
            return OrderResult(order_id="", accepted=False, message="Live order blocked: LIVE_TRADING is not true")
        if not self.live_trading_confirm:
            return OrderResult(order_id="", accepted=False, message="Live order blocked: LIVE_TRADING_CONFIRM is not true")
        if not self.account_no or not self.account_product_code:
            return OrderResult(order_id="", accepted=False, message="Live order blocked: account info is missing")
        return None

    def _log_dry_run(self, order: OrderRequest) -> None:
        # Do not log secrets or full account number.
        masked_account = f"***{self.account_no[-4:]}" if len(self.account_no) >= 4 else "***"
        self.logger.warning(
            "[DRY-RUN BEFORE LIVE ORDER] mode=%s account=%s side=%s symbol=%s qty=%s price=%s strategy=%s",
            self.trading_mode,
            masked_account,
            order.side,
            order.symbol,
            order.quantity,
            order.price,
            order.strategy_id,
        )
