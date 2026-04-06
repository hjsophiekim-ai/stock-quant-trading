from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from app.orders.models import OrderRequest


@dataclass(frozen=True)
class RiskSnapshot:
    daily_pnl_pct: float
    total_pnl_pct: float
    equity: float
    market_filter_ok: bool
    position_values: dict[str, float]
    cooldown_until: dict[str, datetime] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskLimits:
    min_position_weight: float = 0.10
    max_position_weight: float = 0.15
    max_positions: int = 5
    daily_loss_limit_pct: float = 3.0
    total_loss_limit_pct: float = 10.0
    reentry_cooldown_minutes: int = 60
    default_stop_loss_pct: float = 4.0


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason_code: str
    reason: str
    is_hard_stop: bool = False


class RiskRules:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()

    def can_trade(self, snapshot: RiskSnapshot) -> bool:
        return self.evaluate_global_guard(snapshot).approved

    def validate_stop_loss(self, stop_loss_pct: float | None) -> bool:
        if stop_loss_pct is None:
            return False
        return stop_loss_pct > 0

    def evaluate_global_guard(self, snapshot: RiskSnapshot) -> RiskDecision:
        if snapshot.total_pnl_pct <= -abs(self.limits.total_loss_limit_pct):
            return RiskDecision(
                approved=False,
                reason_code="SYSTEM_OFF_TOTAL_LOSS",
                reason="Account total loss limit reached (-10%): system OFF",
                is_hard_stop=True,
            )
        if snapshot.daily_pnl_pct <= -abs(self.limits.daily_loss_limit_pct):
            return RiskDecision(
                approved=False,
                reason_code="HALT_DAILY_LOSS",
                reason="Daily loss limit reached (-3%): trading halted for today",
                is_hard_stop=True,
            )
        return RiskDecision(approved=True, reason_code="OK", reason="Global risk guard passed")

    def approve_order(
        self,
        *,
        order: OrderRequest,
        snapshot: RiskSnapshot,
        now: datetime | None = None,
    ) -> RiskDecision:
        now_utc = now or datetime.now(timezone.utc)

        global_guard = self.evaluate_global_guard(snapshot)
        if not global_guard.approved:
            return global_guard

        if order.side == "sell":
            # Sell must pass even when market filters are bad, because stop-loss is absolute priority.
            return RiskDecision(approved=True, reason_code="OK_SELL", reason="Sell order allowed for risk reduction")

        if not snapshot.market_filter_ok:
            return RiskDecision(
                approved=False,
                reason_code="BLOCK_BAD_MARKET_FILTER",
                reason="Market filter is bad: new buy orders are blocked",
            )

        if not self.validate_stop_loss(order.stop_loss_pct):
            return RiskDecision(
                approved=False,
                reason_code="MISSING_STOP_LOSS",
                reason="Stop-loss is required and must be positive",
            )

        cooldown = snapshot.cooldown_until.get(order.symbol)
        if cooldown is not None and now_utc < cooldown:
            return RiskDecision(
                approved=False,
                reason_code="REENTRY_COOLDOWN",
                reason=f"Symbol re-entry cooldown active until {cooldown.isoformat()}",
            )

        if order.price is None or order.price <= 0:
            return RiskDecision(
                approved=False,
                reason_code="INVALID_ORDER_PRICE",
                reason="Buy order requires positive price for risk sizing checks",
            )

        weight_decision = self._validate_buy_weight(order, snapshot)
        if not weight_decision.approved:
            return weight_decision

        return RiskDecision(approved=True, reason_code="OK_BUY", reason="Buy order approved by risk engine")

    def mark_symbol_exit(self, snapshot: RiskSnapshot, symbol: str, now: datetime | None = None) -> RiskSnapshot:
        now_utc = now or datetime.now(timezone.utc)
        updated = dict(snapshot.cooldown_until)
        updated[symbol] = now_utc + timedelta(minutes=self.limits.reentry_cooldown_minutes)
        return RiskSnapshot(
            daily_pnl_pct=snapshot.daily_pnl_pct,
            total_pnl_pct=snapshot.total_pnl_pct,
            equity=snapshot.equity,
            market_filter_ok=snapshot.market_filter_ok,
            position_values=dict(snapshot.position_values),
            cooldown_until=updated,
        )

    def _validate_buy_weight(self, order: OrderRequest, snapshot: RiskSnapshot) -> RiskDecision:
        if snapshot.equity <= 0:
            return RiskDecision(approved=False, reason_code="INVALID_EQUITY", reason="Equity must be positive")

        current_positions = {k: v for k, v in snapshot.position_values.items() if v > 0}
        new_position_count = len(current_positions)
        if order.symbol not in current_positions:
            new_position_count += 1
        if new_position_count > self.limits.max_positions:
            return RiskDecision(
                approved=False,
                reason_code="MAX_POSITIONS_EXCEEDED",
                reason="Maximum 5 holdings exceeded",
            )

        current_value = float(current_positions.get(order.symbol, 0.0))
        order_value = float(order.quantity) * float(order.price)
        new_value = current_value + order_value
        weight = new_value / snapshot.equity

        if weight > self.limits.max_position_weight:
            return RiskDecision(
                approved=False,
                reason_code="POSITION_WEIGHT_TOO_HIGH",
                reason="Position weight exceeds 15% limit",
            )

        if weight < self.limits.min_position_weight:
            return RiskDecision(
                approved=False,
                reason_code="POSITION_WEIGHT_TOO_LOW",
                reason="Position weight must be at least 10%",
            )

        return RiskDecision(approved=True, reason_code="OK_WEIGHT", reason="Position sizing check passed")
