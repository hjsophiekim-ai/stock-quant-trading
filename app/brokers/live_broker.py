from dataclasses import dataclass, field
import logging
from typing import Any

from app.brokers.base_broker import AccountEquitySnapshot, BaseBroker, Fill, OpenOrder, PositionView
from app.clients.kis_client import KISClient, KISClientError
from app.clients.kis_parsers import (
    normalized_fills_from_ccld_payload,
    open_orders_from_nccs_payload,
    parse_kis_ord_datetime_to_utc,
)
from app.config import Settings, get_settings
from app.orders.models import OrderRequest, OrderResult


@dataclass
class LiveBroker(BaseBroker):
    kis_client: KISClient
    account_no: str
    account_product_code: str
    live_trading_enabled: bool = False
    live_trading_confirm: bool = False
    live_trading_extra_confirm: bool = False
    trading_mode: str = "paper"
    dry_run_log_enabled: bool = True
    logger: logging.Logger = logging.getLogger("app.brokers.live_broker")
    startup_safety_passed: bool = False
    startup_safety_reason: str = "Startup safety validation not executed"
    _order_symbols: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, kis_client: KISClient, account_no: str, account_product_code: str, settings: Settings | None = None) -> "LiveBroker":
        cfg = settings or get_settings()
        # REST 클라이언트 실전 주문 잠금: 다중 플래그 통과 시에만 해제
        kis_client.live_execution_unlocked = bool(cfg.is_live_order_allowed)
        return cls(
            kis_client=kis_client,
            account_no=account_no,
            account_product_code=account_product_code,
            live_trading_enabled=cfg.resolved_live_trading_enabled,
            live_trading_confirm=cfg.live_trading_confirm,
            live_trading_extra_confirm=cfg.live_trading_extra_confirm,
            trading_mode=cfg.trading_mode,
            dry_run_log_enabled=cfg.live_order_dry_run_log,
        )

    def __post_init__(self) -> None:
        ok, reason = self.validate_startup_safety()
        self.startup_safety_passed = ok
        self.startup_safety_reason = reason
        level = logging.INFO if ok else logging.ERROR
        self.logger.log(level, "[LIVE STARTUP SAFETY] passed=%s reason=%s", ok, reason)

    def get_cash(self) -> float:
        payload = self.kis_client.get_balance(self.account_no, self.account_product_code)
        return self._extract_cash(payload)

    def get_account_equity_snapshot(self) -> AccountEquitySnapshot:
        cash = float(self.get_cash() or 0.0)
        return AccountEquitySnapshot(
            orderable_cash=cash,
            cash_total=cash,
            reserved_cash_open_buys=0.0,
            positions_market_value=None,
            source_of_truth="live",
            open_buy_order_count=0,
            open_buy_order_missing_price_count=0,
            reserved_cash_estimation_method="none",
            raw_balance_summary={},
        )

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
        try:
            payload = self.kis_client.inquire_nccs(
                account_no=self.account_no,
                account_product_code=self.account_product_code,
                symbol="",
            )
        except KISClientError as exc:
            self.logger.warning("live inquire_nccs (open orders) failed: %s", exc)
            return []
        orders = open_orders_from_nccs_payload(payload)
        for o in orders:
            self._order_symbols[o.order_id] = o.symbol
        return orders

    def get_fills(self) -> list[Fill]:
        try:
            payload = self.kis_client.inquire_daily_ccld(
                account_no=self.account_no,
                account_product_code=self.account_product_code,
                symbol="",
                sell_buy_code="00",
                ccld_div="01",
            )
        except KISClientError as exc:
            self.logger.warning("live inquire_daily_ccld (fills) failed: %s", exc)
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
        if not self.startup_safety_passed:
            return OrderResult(
                order_id="",
                accepted=False,
                message=f"Live order blocked: startup safety validation failed ({self.startup_safety_reason})",
            )
        if self.trading_mode != "live":
            return OrderResult(order_id="", accepted=False, message="Live order blocked: TRADING_MODE is not live")
        if not self.live_trading_enabled:
            return OrderResult(order_id="", accepted=False, message="Live order blocked: LIVE_TRADING is not true")
        if not self.live_trading_confirm:
            return OrderResult(order_id="", accepted=False, message="Live order blocked: LIVE_TRADING_CONFIRM is not true")
        if not self.live_trading_extra_confirm:
            return OrderResult(order_id="", accepted=False, message="Live order blocked: LIVE_TRADING_EXTRA_CONFIRM is not true")
        if not self.account_no or not self.account_product_code:
            return OrderResult(order_id="", accepted=False, message="Live order blocked: account info is missing")
        return None

    def _log_dry_run(self, order: OrderRequest) -> None:
        # Do not log secrets or full account number.
        masked_account = f"***{self.account_no[-4:]}" if len(self.account_no) >= 4 else "***"
        self.logger.warning(
            "[DRY-RUN BEFORE LIVE ORDER] mode=%s account=%s side=%s symbol=%s qty=%s price=%s strategy=%s startup_ok=%s",
            self.trading_mode,
            masked_account,
            order.side,
            order.symbol,
            order.quantity,
            order.price,
            order.strategy_id,
            self.startup_safety_passed,
        )

    def validate_startup_safety(self) -> tuple[bool, str]:
        if self.trading_mode not in {"paper", "live"}:
            return False, "TRADING_MODE must be 'paper' or 'live'"
        if self.trading_mode != "live":
            return False, "TRADING_MODE is not live"
        if not self.live_trading_enabled:
            return False, "LIVE_TRADING is not true"
        if not self.live_trading_confirm:
            return False, "LIVE_TRADING_CONFIRM is not true"
        if not self.live_trading_extra_confirm:
            return False, "LIVE_TRADING_EXTRA_CONFIRM is not true"
        if not self.account_no or not self.account_product_code:
            return False, "KIS account fields are missing"
        return True, "Startup live safety validation passed"
