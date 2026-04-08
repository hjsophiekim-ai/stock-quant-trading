from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from app.orders.models import OrderRequest
from app.risk.reason_codes import RiskReasonCode

MarketRegime = Literal["bullish_trend", "bearish_trend", "sideways", "high_volatility_risk"]


@dataclass(frozen=True)
class RiskSnapshot:
    daily_pnl_pct: float
    total_pnl_pct: float
    equity: float
    market_filter_ok: bool
    position_values: dict[str, float]
    market_regime: MarketRegime = "sideways"
    recent_trade_pnls: tuple[float, ...] = ()
    consecutive_losses: int = 0
    latest_entry_score: float | None = None
    todays_new_entries: int = 0
    trading_cooldown_until: datetime | None = None
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
    bearish_max_positions: int = 2
    bearish_max_position_weight: float = 0.08
    bearish_min_position_weight: float = 0.03
    bearish_max_stop_loss_pct: float = 2.5
    bearish_max_new_entries_per_day: int = 1
    bearish_min_entry_price: float = 0.0
    high_vol_new_entry_blocked: bool = True
    rolling_loss_window_trades: int = 10
    rolling_loss_limit_pct: float = 4.0
    adaptive_loss_streak_threshold: int = 3
    adaptive_new_entries_limit: int = 1
    adaptive_position_weight_multiplier: float = 0.7
    adaptive_stop_loss_tighten_multiplier: float = 0.8
    adaptive_trading_cooldown_minutes: int = 120
    adaptive_performance_floor_pct: float = -1.0
    adaptive_min_entry_score: float = 0.65
    adaptive_enable_entry_filter: bool = True
    """단일 매수 주문의 최대 명목가(자기자본 대비 %). 주문 실수·과도한 단일 베팅 방지."""
    max_single_order_notional_pct: float = 25.0
    """비어 있으면 화이트리스트 미사용. 값이 있으면 해당 종목만 매수 허용."""
    allowed_symbols: tuple[str, ...] = ()


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason_code: str
    reason: str
    is_hard_stop: bool = False


@dataclass(frozen=True)
class AdaptiveGuard:
    max_new_entries: int
    position_weight_multiplier: float
    stop_loss_tighten_multiplier: float
    cooldown_required: bool
    loss_streak_triggered: bool
    performance_deteriorating: bool
    require_stronger_entry: bool
    min_entry_score: float


class RiskRules:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()

    def can_trade(self, snapshot: RiskSnapshot) -> bool:
        return self.evaluate_global_guard(snapshot).approved

    def can_open_new_risk(self, snapshot: RiskSnapshot) -> bool:
        """신규 매수·리스크 증가 허용 여부(청산·매도와 구분)."""
        return self.evaluate_global_guard(snapshot).approved

    def validate_stop_loss(self, stop_loss_pct: float | None) -> bool:
        if stop_loss_pct is None:
            return False
        return stop_loss_pct > 0

    def evaluate_global_guard(self, snapshot: RiskSnapshot) -> RiskDecision:
        if snapshot.trading_cooldown_until is not None and datetime.now(timezone.utc) < snapshot.trading_cooldown_until:
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.TRADING_COOLDOWN_ACTIVE.value,
                reason=f"Trading cooldown active until {snapshot.trading_cooldown_until.isoformat()}",
                is_hard_stop=False,
            )
        if snapshot.total_pnl_pct <= -abs(self.limits.total_loss_limit_pct):
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.SYSTEM_OFF_TOTAL_LOSS.value,
                reason="Account total loss limit reached: system risk_off (신규 리스크 중단)",
                is_hard_stop=True,
            )
        if snapshot.daily_pnl_pct <= -abs(self.limits.daily_loss_limit_pct):
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.HALT_DAILY_LOSS.value,
                reason="Daily loss limit reached: 신규 매수 중단 (청산·매도는 별도 허용)",
                is_hard_stop=True,
            )
        rolling = rolling_trade_pnl_pct(snapshot.recent_trade_pnls, self.limits.rolling_loss_window_trades, snapshot.equity)
        if rolling <= -abs(self.limits.rolling_loss_limit_pct):
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.HALT_ROLLING_LOSS_LIMIT.value,
                reason=f"Rolling loss limit reached ({rolling:.2f}% <= -{self.limits.rolling_loss_limit_pct:.2f}%)",
                is_hard_stop=False,
            )
        return RiskDecision(approved=True, reason_code=RiskReasonCode.OK.value, reason="Global risk guard passed")

    def approve_order(
        self,
        *,
        order: OrderRequest,
        snapshot: RiskSnapshot,
        now: datetime | None = None,
    ) -> RiskDecision:
        now_utc = now or datetime.now(timezone.utc)

        # 손절·리스크 축소 매도는 일일/총 손실 한도보다 우선(자동 청산 유지).
        if order.side == "sell":
            return RiskDecision(
                approved=True,
                reason_code=RiskReasonCode.OK_SELL.value,
                reason="Sell order allowed: stop-loss / risk reduction priority",
            )

        global_guard = self.evaluate_global_guard(snapshot)
        if not global_guard.approved:
            return global_guard

        if order.quantity <= 0:
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.ORDER_QUANTITY_INVALID.value,
                reason="Order quantity must be positive",
            )

        if self.limits.allowed_symbols and order.symbol not in self.limits.allowed_symbols:
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.SYMBOL_NOT_ALLOWED.value,
                reason="Symbol not in allowed universe for automated buys",
            )

        adaptive = self._build_adaptive_guard(snapshot)
        if adaptive.cooldown_required:
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.TRADING_COOLDOWN_REQUIRED_ADAPTIVE.value,
                reason="Loss adaptation triggered cooldown due to deteriorating recent performance",
            )
        if snapshot.todays_new_entries >= adaptive.max_new_entries:
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.ADAPTIVE_NEW_ENTRY_LIMIT.value,
                reason=f"Adaptive defense: max new entries reached ({adaptive.max_new_entries})",
            )
        if (
            adaptive.require_stronger_entry
            and snapshot.latest_entry_score is not None
            and snapshot.latest_entry_score < adaptive.min_entry_score
        ):
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.ADAPTIVE_ENTRY_FILTER_BLOCK.value,
                reason=(
                    f"Adaptive defense: entry score {snapshot.latest_entry_score:.2f} "
                    f"below required {adaptive.min_entry_score:.2f}"
                ),
            )

        if snapshot.market_regime == "high_volatility_risk" and self.limits.high_vol_new_entry_blocked:
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.BLOCK_REGIME_HIGH_VOLATILITY_NEW_ENTRY.value,
                reason="High volatility regime: new entries are blocked, only position management allowed",
            )
        if snapshot.market_regime == "bearish_trend" and snapshot.todays_new_entries >= self.limits.bearish_max_new_entries_per_day:
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.BLOCK_REGIME_BEARISH_NEW_ENTRY_LIMIT.value,
                reason=(
                    f"Bearish regime daily new entry limit reached "
                    f"({self.limits.bearish_max_new_entries_per_day})"
                ),
            )

        if not snapshot.market_filter_ok:
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.BLOCK_BAD_MARKET_FILTER.value,
                reason="Market filter is bad: new buy orders are blocked",
            )

        if not self.validate_stop_loss(order.stop_loss_pct):
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.MISSING_STOP_LOSS.value,
                reason="Stop-loss is required and must be positive",
            )

        if snapshot.market_regime == "bearish_trend" and order.stop_loss_pct is not None:
            max_stop_loss = self.limits.bearish_max_stop_loss_pct * adaptive.stop_loss_tighten_multiplier
            if order.stop_loss_pct > max_stop_loss:
                return RiskDecision(
                    approved=False,
                    reason_code=RiskReasonCode.BLOCK_REGIME_BEARISH_STOP_LOSS_TOO_WIDE.value,
                    reason=f"Bearish regime requires tighter stop-loss <= {max_stop_loss:.2f}%",
                )

        cooldown = snapshot.cooldown_until.get(order.symbol)
        if cooldown is not None and now_utc < cooldown:
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.REENTRY_COOLDOWN.value,
                reason=f"Symbol re-entry cooldown active until {cooldown.isoformat()}",
            )

        if order.price is None or order.price <= 0:
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.INVALID_ORDER_PRICE.value,
                reason="Buy order requires positive price for risk sizing checks",
            )

        notional = float(order.quantity) * float(order.price)
        max_notional = snapshot.equity * (self.limits.max_single_order_notional_pct / 100.0)
        if max_notional > 0 and notional > max_notional:
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.ORDER_NOTIONAL_EXCEEDS_CAP.value,
                reason=(
                    f"Single order notional {notional:,.0f} exceeds cap {max_notional:,.0f} "
                    f"({self.limits.max_single_order_notional_pct}% of equity)"
                ),
            )

        weight_decision = self._validate_buy_weight(order, snapshot, adaptive_weight_multiplier=adaptive.position_weight_multiplier)
        if not weight_decision.approved:
            return weight_decision

        if snapshot.market_regime == "bearish_trend":
            return RiskDecision(
                approved=True,
                reason_code=RiskReasonCode.OK_REGIME_BEARISH_BUY_CONSERVATIVE.value,
                reason="Bearish regime buy approved with conservative limits",
            )
        return RiskDecision(approved=True, reason_code=RiskReasonCode.OK_BUY.value, reason="Buy order approved by risk engine")

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
            market_regime=snapshot.market_regime,
            recent_trade_pnls=snapshot.recent_trade_pnls,
            consecutive_losses=snapshot.consecutive_losses,
            latest_entry_score=snapshot.latest_entry_score,
            todays_new_entries=snapshot.todays_new_entries,
            trading_cooldown_until=snapshot.trading_cooldown_until,
            cooldown_until=updated,
        )

    def _validate_buy_weight(self, order: OrderRequest, snapshot: RiskSnapshot, *, adaptive_weight_multiplier: float) -> RiskDecision:
        if snapshot.equity <= 0:
            return RiskDecision(approved=False, reason_code=RiskReasonCode.INVALID_EQUITY.value, reason="Equity must be positive")

        current_positions = {k: v for k, v in snapshot.position_values.items() if v > 0}
        new_position_count = len(current_positions)
        if order.symbol not in current_positions:
            new_position_count += 1
        max_positions = self.limits.max_positions
        if snapshot.market_regime == "bearish_trend":
            max_positions = min(max_positions, self.limits.bearish_max_positions)

        if new_position_count > max_positions:
            code = RiskReasonCode.MAX_POSITIONS_EXCEEDED.value
            msg = f"Maximum {max_positions} holdings exceeded"
            if snapshot.market_regime == "bearish_trend":
                code = RiskReasonCode.BLOCK_REGIME_BEARISH_MAX_POSITIONS.value
                msg = f"Bearish regime max holdings exceeded ({max_positions})"
            return RiskDecision(
                approved=False,
                reason_code=code,
                reason=msg,
            )

        current_value = float(current_positions.get(order.symbol, 0.0))
        order_value = float(order.quantity) * float(order.price)
        new_value = current_value + order_value
        weight = new_value / snapshot.equity

        max_weight = self.limits.max_position_weight
        if snapshot.market_regime == "bearish_trend":
            max_weight = min(max_weight, self.limits.bearish_max_position_weight)
        max_weight = max_weight * adaptive_weight_multiplier

        if weight > max_weight:
            code = RiskReasonCode.POSITION_WEIGHT_TOO_HIGH.value
            msg = f"Position weight exceeds {max_weight*100:.1f}% limit"
            if snapshot.market_regime == "bearish_trend":
                code = RiskReasonCode.BLOCK_REGIME_BEARISH_POSITION_WEIGHT.value
                msg = f"Bearish regime position weight exceeds {max_weight*100:.1f}% limit"
            return RiskDecision(
                approved=False,
                reason_code=code,
                reason=msg,
            )

        if snapshot.market_regime == "bearish_trend":
            eff_min = min(self.limits.bearish_min_position_weight, max_weight * 0.99)
        else:
            eff_min = min(self.limits.min_position_weight, max_weight * 0.99)

        if weight < eff_min:
            return RiskDecision(
                approved=False,
                reason_code=RiskReasonCode.POSITION_WEIGHT_TOO_LOW.value,
                reason=f"Position weight below minimum ({eff_min*100:.1f}% required for policy)",
            )

        return RiskDecision(approved=True, reason_code=RiskReasonCode.OK_WEIGHT.value, reason="Position sizing check passed")

    def _build_adaptive_guard(self, snapshot: RiskSnapshot) -> AdaptiveGuard:
        loss_streak_triggered = snapshot.consecutive_losses >= self.limits.adaptive_loss_streak_threshold
        rolling = rolling_trade_pnl_pct(snapshot.recent_trade_pnls, self.limits.rolling_loss_window_trades, snapshot.equity)
        performance_deteriorating = rolling < self.limits.adaptive_performance_floor_pct
        cooldown_required = loss_streak_triggered and performance_deteriorating

        if loss_streak_triggered or performance_deteriorating:
            return AdaptiveGuard(
                max_new_entries=self.limits.adaptive_new_entries_limit,
                position_weight_multiplier=self.limits.adaptive_position_weight_multiplier,
                stop_loss_tighten_multiplier=self.limits.adaptive_stop_loss_tighten_multiplier,
                cooldown_required=cooldown_required,
                loss_streak_triggered=loss_streak_triggered,
                performance_deteriorating=performance_deteriorating,
                require_stronger_entry=self.limits.adaptive_enable_entry_filter,
                min_entry_score=self.limits.adaptive_min_entry_score,
            )
        return AdaptiveGuard(
            max_new_entries=self.limits.max_positions,
            position_weight_multiplier=1.0,
            stop_loss_tighten_multiplier=1.0,
            cooldown_required=False,
            loss_streak_triggered=False,
            performance_deteriorating=False,
            require_stronger_entry=False,
            min_entry_score=self.limits.adaptive_min_entry_score,
        )

    def adaptive_guard(self, snapshot: RiskSnapshot) -> AdaptiveGuard:
        return self._build_adaptive_guard(snapshot)


def rolling_trade_pnl_pct(recent_trade_pnls: tuple[float, ...], window: int, equity: float) -> float:
    if window <= 0 or equity <= 0 or not recent_trade_pnls:
        return 0.0
    samples = recent_trade_pnls[-window:]
    return (sum(samples) / equity) * 100.0
