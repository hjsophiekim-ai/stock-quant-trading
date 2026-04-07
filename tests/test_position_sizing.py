from app.risk.position_sizing import (
    DynamicSizingConfig,
    DynamicSizingInput,
    RegimeSizingConfig,
    calculate_dynamic_position_sizing,
)


def test_bullish_low_vol_high_confidence_increases_size() -> None:
    result = calculate_dynamic_position_sizing(
        data=DynamicSizingInput(
            regime="bullish_trend",
            equity=10_000_000.0,
            entry_price=50_000.0,
            atr_pct=1.2,
            strategy_confidence=0.9,
            recent_performance_pct=4.0,
            daily_pnl_pct=0.5,
            total_pnl_pct=2.0,
            total_loss_limit_pct=10.0,
            account_volatility_pct=1.0,
            consecutive_losses=0,
            current_symbol_weight=0.02,
            recent_entries_on_symbol=0,
        )
    )
    assert result.allow_additional_entry is True
    assert result.recommended_quantity > 0
    assert result.max_allowed_weight >= 0.15


def test_bearish_high_vol_reduces_size_significantly() -> None:
    result = calculate_dynamic_position_sizing(
        data=DynamicSizingInput(
            regime="bearish_trend",
            equity=10_000_000.0,
            entry_price=50_000.0,
            atr_pct=5.2,
            strategy_confidence=0.6,
            recent_performance_pct=-2.0,
            daily_pnl_pct=-1.0,
            total_pnl_pct=-3.0,
            total_loss_limit_pct=10.0,
            account_volatility_pct=2.8,
            consecutive_losses=2,
            current_symbol_weight=0.0,
            recent_entries_on_symbol=0,
        )
    )
    assert result.max_allowed_weight <= 0.08
    assert result.recommended_quantity >= 0
    assert result.leverage_multiplier < 1.0


def test_losing_streak_auto_deleverages() -> None:
    base = calculate_dynamic_position_sizing(
        data=DynamicSizingInput(
            regime="sideways",
            equity=5_000_000.0,
            entry_price=20_000.0,
            atr_pct=2.0,
            strategy_confidence=0.6,
            recent_performance_pct=1.0,
            daily_pnl_pct=0.2,
            total_pnl_pct=0.5,
            total_loss_limit_pct=10.0,
            account_volatility_pct=1.6,
            consecutive_losses=0,
            current_symbol_weight=0.0,
            recent_entries_on_symbol=0,
        )
    )
    after_losses = calculate_dynamic_position_sizing(
        data=DynamicSizingInput(
            regime="sideways",
            equity=5_000_000.0,
            entry_price=20_000.0,
            atr_pct=2.0,
            strategy_confidence=0.6,
            recent_performance_pct=1.0,
            daily_pnl_pct=0.2,
            total_pnl_pct=0.5,
            total_loss_limit_pct=10.0,
            account_volatility_pct=1.6,
            consecutive_losses=4,
            current_symbol_weight=0.0,
            recent_entries_on_symbol=0,
        )
    )
    assert after_losses.leverage_multiplier < base.leverage_multiplier
    assert after_losses.recommended_quantity <= base.recommended_quantity


def test_high_volatility_regime_blocks_new_entry() -> None:
    result = calculate_dynamic_position_sizing(
        data=DynamicSizingInput(
            regime="high_volatility_risk",
            equity=5_000_000.0,
            entry_price=20_000.0,
            atr_pct=6.0,
            strategy_confidence=0.7,
            recent_performance_pct=0.0,
            daily_pnl_pct=-0.5,
            total_pnl_pct=-1.0,
            total_loss_limit_pct=10.0,
            account_volatility_pct=3.0,
            consecutive_losses=1,
            current_symbol_weight=0.0,
            recent_entries_on_symbol=0,
        )
    )
    assert result.allow_additional_entry is False
    assert result.recommended_quantity == 0


def test_total_loss_limit_has_absolute_priority() -> None:
    result = calculate_dynamic_position_sizing(
        data=DynamicSizingInput(
            regime="bullish_trend",
            equity=10_000_000.0,
            entry_price=50_000.0,
            atr_pct=1.1,
            strategy_confidence=0.95,
            recent_performance_pct=8.0,
            daily_pnl_pct=1.0,
            total_pnl_pct=-10.5,
            total_loss_limit_pct=10.0,
            account_volatility_pct=1.2,
            consecutive_losses=0,
            current_symbol_weight=0.0,
            recent_entries_on_symbol=0,
        )
    )
    assert result.recommended_quantity == 0
    assert result.allow_additional_entry is False


def test_account_volatility_above_target_auto_cuts_exposure() -> None:
    base = calculate_dynamic_position_sizing(
        data=DynamicSizingInput(
            regime="bullish_trend",
            equity=8_000_000.0,
            entry_price=40_000.0,
            atr_pct=1.5,
            strategy_confidence=0.8,
            recent_performance_pct=3.0,
            daily_pnl_pct=0.5,
            total_pnl_pct=1.0,
            total_loss_limit_pct=10.0,
            account_volatility_pct=1.4,
            consecutive_losses=0,
            current_symbol_weight=0.01,
            recent_entries_on_symbol=0,
        )
    )
    cut = calculate_dynamic_position_sizing(
        data=DynamicSizingInput(
            regime="bullish_trend",
            equity=8_000_000.0,
            entry_price=40_000.0,
            atr_pct=1.5,
            strategy_confidence=0.8,
            recent_performance_pct=3.0,
            daily_pnl_pct=0.5,
            total_pnl_pct=1.0,
            total_loss_limit_pct=10.0,
            account_volatility_pct=3.2,
            consecutive_losses=0,
            current_symbol_weight=0.01,
            recent_entries_on_symbol=0,
        )
    )
    assert cut.recommended_quantity < base.recommended_quantity


def test_regime_sizing_config_can_override_bearish_limits() -> None:
    result = calculate_dynamic_position_sizing(
        data=DynamicSizingInput(
            regime="bearish_trend",
            equity=10_000_000.0,
            entry_price=50_000.0,
            atr_pct=2.0,
            strategy_confidence=0.7,
            recent_performance_pct=0.0,
            daily_pnl_pct=0.0,
            total_pnl_pct=0.0,
            total_loss_limit_pct=10.0,
            account_volatility_pct=1.4,
            consecutive_losses=0,
            current_symbol_weight=0.0,
            recent_entries_on_symbol=0,
        ),
        regime_sizing_config=RegimeSizingConfig(bearish_max_weight=0.05, bearish_prefer_weight=0.03),
    )
    assert result.max_allowed_weight == 0.05
