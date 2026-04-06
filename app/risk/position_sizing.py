from dataclasses import dataclass
from typing import Literal

MarketRegime = Literal["bullish_trend", "bearish_trend", "sideways", "high_volatility_risk"]

@dataclass(frozen=True)
class PositionSizingPlan:
    quantity: int
    target_value: float
    target_weight: float
    reason: str


@dataclass(frozen=True)
class RegimeSizingProfile:
    min_weight: float
    max_weight: float
    prefer_weight: float
    max_new_entries: int
    max_hold_days: int


@dataclass(frozen=True)
class DynamicSizingConfig:
    bullish_boost_multiplier: float = 1.20
    bearish_cut_multiplier: float = 0.60
    sideways_cut_multiplier: float = 0.80
    high_volatility_cut_multiplier: float = 0.00
    high_volatility_atr_threshold_pct: float = 4.0
    low_volatility_atr_threshold_pct: float = 1.8
    confidence_floor: float = 0.0
    confidence_cap: float = 1.0
    confidence_weight: float = 0.35
    performance_weight: float = 0.20
    pnl_state_weight: float = 0.25
    losing_streak_deleverage_step: float = 0.10
    max_deleverage_multiplier: float = 0.50
    bearish_max_additional_entries: int = 0
    default_max_additional_entries: int = 1


@dataclass(frozen=True)
class DynamicSizingInput:
    regime: MarketRegime
    equity: float
    entry_price: float
    atr_pct: float
    strategy_confidence: float  # 0.0 ~ 1.0
    recent_performance_pct: float
    daily_pnl_pct: float
    total_pnl_pct: float
    total_loss_limit_pct: float
    consecutive_losses: int = 0
    current_symbol_weight: float = 0.0
    recent_entries_on_symbol: int = 0


@dataclass(frozen=True)
class DynamicSizingOutput:
    recommended_quantity: int
    max_allowed_weight: float
    allow_additional_entry: bool
    leverage_multiplier: float
    reason: str


REGIME_SIZING_PROFILES: dict[MarketRegime, RegimeSizingProfile] = {
    "bullish_trend": RegimeSizingProfile(min_weight=0.10, max_weight=0.15, prefer_weight=0.13, max_new_entries=3, max_hold_days=10),
    "sideways": RegimeSizingProfile(min_weight=0.07, max_weight=0.10, prefer_weight=0.08, max_new_entries=1, max_hold_days=5),
    "bearish_trend": RegimeSizingProfile(min_weight=0.04, max_weight=0.08, prefer_weight=0.06, max_new_entries=1, max_hold_days=3),
    "high_volatility_risk": RegimeSizingProfile(min_weight=0.00, max_weight=0.00, prefer_weight=0.00, max_new_entries=0, max_hold_days=2),
}


def fixed_fraction_size(cash: float, risk_fraction: float, entry_price: float) -> int:
    if cash <= 0 or risk_fraction <= 0 or entry_price <= 0:
        return 0
    budget = cash * risk_fraction
    return int(budget // entry_price)


def size_position_by_weight(
    *,
    equity: float,
    entry_price: float,
    min_weight: float = 0.10,
    max_weight: float = 0.15,
    prefer_weight: float = 0.12,
) -> PositionSizingPlan:
    if equity <= 0:
        return PositionSizingPlan(quantity=0, target_value=0.0, target_weight=0.0, reason="Invalid equity")
    if entry_price <= 0:
        return PositionSizingPlan(quantity=0, target_value=0.0, target_weight=0.0, reason="Invalid entry price")
    if not (0 < min_weight <= prefer_weight <= max_weight):
        return PositionSizingPlan(quantity=0, target_value=0.0, target_weight=0.0, reason="Invalid weight setup")

    target_value = equity * prefer_weight
    qty = int(target_value // entry_price)
    if qty <= 0:
        return PositionSizingPlan(quantity=0, target_value=target_value, target_weight=prefer_weight, reason="Too small equity for 1 share")

    actual_weight = (qty * entry_price) / equity
    if actual_weight < min_weight:
        min_qty = int((equity * min_weight) // entry_price)
        if min_qty <= 0:
            return PositionSizingPlan(quantity=0, target_value=target_value, target_weight=prefer_weight, reason="Cannot satisfy min weight")
        qty = min_qty
        actual_weight = (qty * entry_price) / equity

    if actual_weight > max_weight:
        max_qty = int((equity * max_weight) // entry_price)
        qty = max(max_qty, 0)
        actual_weight = (qty * entry_price) / equity if qty > 0 else 0.0

    return PositionSizingPlan(
        quantity=qty,
        target_value=qty * entry_price,
        target_weight=actual_weight,
        reason="Sized by 10-15% position weight policy",
    )


def size_position_by_regime(
    *,
    regime: MarketRegime,
    equity: float,
    entry_price: float,
) -> PositionSizingPlan:
    profile = REGIME_SIZING_PROFILES[regime]
    if profile.max_new_entries == 0:
        return PositionSizingPlan(
            quantity=0,
            target_value=0.0,
            target_weight=0.0,
            reason="New entries blocked in high volatility regime",
        )
    plan = size_position_by_weight(
        equity=equity,
        entry_price=entry_price,
        min_weight=profile.min_weight,
        max_weight=profile.max_weight,
        prefer_weight=profile.prefer_weight,
    )
    return PositionSizingPlan(
        quantity=plan.quantity,
        target_value=plan.target_value,
        target_weight=plan.target_weight,
        reason=f"{regime} sizing profile applied: {plan.reason}",
    )


def max_holding_days_for_regime(regime: MarketRegime) -> int:
    return REGIME_SIZING_PROFILES[regime].max_hold_days


def calculate_dynamic_position_sizing(
    *,
    data: DynamicSizingInput,
    config: DynamicSizingConfig = DynamicSizingConfig(),
) -> DynamicSizingOutput:
    if data.equity <= 0 or data.entry_price <= 0:
        return DynamicSizingOutput(
            recommended_quantity=0,
            max_allowed_weight=0.0,
            allow_additional_entry=False,
            leverage_multiplier=0.0,
            reason="Invalid equity or entry price",
        )

    # Absolute capital protection has priority over any upside sizing logic.
    if data.total_pnl_pct <= -abs(data.total_loss_limit_pct):
        return DynamicSizingOutput(
            recommended_quantity=0,
            max_allowed_weight=0.0,
            allow_additional_entry=False,
            leverage_multiplier=0.0,
            reason="Total loss limit reached; no new exposure allowed",
        )

    regime_profile = REGIME_SIZING_PROFILES[data.regime]
    base_weight = regime_profile.prefer_weight
    max_allowed_weight = regime_profile.max_weight

    regime_multiplier = _regime_multiplier(data.regime, config)
    volatility_multiplier = _volatility_multiplier(data.atr_pct, config)
    confidence_multiplier = _confidence_multiplier(data.strategy_confidence, config)
    performance_multiplier = _performance_multiplier(data.recent_performance_pct, config)
    pnl_state_multiplier = _pnl_state_multiplier(data.daily_pnl_pct, data.total_pnl_pct, config)
    deleverage_multiplier = _losing_streak_multiplier(data.consecutive_losses, config)

    leverage_multiplier = (
        regime_multiplier
        * volatility_multiplier
        * confidence_multiplier
        * performance_multiplier
        * pnl_state_multiplier
        * deleverage_multiplier
    )

    target_weight = min(max(base_weight * leverage_multiplier, 0.0), max_allowed_weight)

    # High volatility risk regime should not allow new entries.
    if data.regime == "high_volatility_risk":
        return DynamicSizingOutput(
            recommended_quantity=0,
            max_allowed_weight=0.0,
            allow_additional_entry=False,
            leverage_multiplier=0.0,
            reason="High volatility risk regime blocks new entries",
        )

    allow_additional_entry = _allow_additional_entry(data, config)
    if not allow_additional_entry:
        return DynamicSizingOutput(
            recommended_quantity=0,
            max_allowed_weight=max_allowed_weight,
            allow_additional_entry=False,
            leverage_multiplier=leverage_multiplier,
            reason="Additional entry blocked by regime or symbol entry cap",
        )

    target_value = data.equity * target_weight
    remaining_value_room = max((max_allowed_weight - data.current_symbol_weight) * data.equity, 0.0)
    order_budget = min(target_value, remaining_value_room)
    qty = int(order_budget // data.entry_price)

    return DynamicSizingOutput(
        recommended_quantity=max(qty, 0),
        max_allowed_weight=max_allowed_weight,
        allow_additional_entry=allow_additional_entry,
        leverage_multiplier=leverage_multiplier,
        reason=(
            f"Dynamic sizing applied: regime={data.regime}, atr={data.atr_pct:.2f}%, "
            f"confidence={data.strategy_confidence:.2f}, recent_perf={data.recent_performance_pct:.2f}%"
        ),
    )


def _regime_multiplier(regime: MarketRegime, cfg: DynamicSizingConfig) -> float:
    if regime == "bullish_trend":
        return cfg.bullish_boost_multiplier
    if regime == "bearish_trend":
        return cfg.bearish_cut_multiplier
    if regime == "sideways":
        return cfg.sideways_cut_multiplier
    return cfg.high_volatility_cut_multiplier


def _volatility_multiplier(atr_pct: float, cfg: DynamicSizingConfig) -> float:
    if atr_pct >= cfg.high_volatility_atr_threshold_pct:
        return 0.55
    if atr_pct <= cfg.low_volatility_atr_threshold_pct:
        return 1.10
    return 1.0


def _confidence_multiplier(confidence: float, cfg: DynamicSizingConfig) -> float:
    clipped = min(max(confidence, cfg.confidence_floor), cfg.confidence_cap)
    return 1.0 + ((clipped - 0.5) * 2.0 * cfg.confidence_weight)


def _performance_multiplier(recent_performance_pct: float, cfg: DynamicSizingConfig) -> float:
    scaled = max(min(recent_performance_pct / 10.0, 1.0), -1.0)
    return 1.0 + (scaled * cfg.performance_weight)


def _pnl_state_multiplier(daily_pnl_pct: float, total_pnl_pct: float, cfg: DynamicSizingConfig) -> float:
    # Drawdown in account state should reduce new risk quickly.
    daily_scaled = max(min(daily_pnl_pct / 3.0, 1.0), -1.0)
    total_scaled = max(min(total_pnl_pct / 10.0, 1.0), -1.0)
    penalty = (daily_scaled + total_scaled) / 2.0
    return 1.0 + (penalty * cfg.pnl_state_weight)


def _losing_streak_multiplier(consecutive_losses: int, cfg: DynamicSizingConfig) -> float:
    if consecutive_losses <= 0:
        return 1.0
    cut = consecutive_losses * cfg.losing_streak_deleverage_step
    return max(1.0 - cut, cfg.max_deleverage_multiplier)


def _allow_additional_entry(data: DynamicSizingInput, cfg: DynamicSizingConfig) -> bool:
    if data.regime == "bearish_trend":
        return data.recent_entries_on_symbol <= cfg.bearish_max_additional_entries
    return data.recent_entries_on_symbol <= cfg.default_max_additional_entries
