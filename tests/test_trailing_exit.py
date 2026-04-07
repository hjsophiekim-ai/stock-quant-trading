import pandas as pd

from app.portfolio.positions import Position, apply_sell_fill
from app.strategy.bull_strategy import (
    BullStrategyConfig,
    _build_exit_signals,
    _trailing_stop_triggered,
)


def test_first_take_profit_partial_exit_then_keep_runner() -> None:
    cfg = BullStrategyConfig(first_take_profit_pct=6.0, trailing_mode="atr")
    position = pd.Series(
        {
            "average_price": 100.0,
            "quantity": 10,
            "hold_days": 2,
            "first_take_profit_done": False,
            "highest_price_since_entry": 106.0,
        }
    )
    signal = {"close": 106.0, "atr14": 1.0, "low_n": 103.0, "ma20": 102.0}
    exits = _build_exit_signals("005930", signal, position, cfg, "bull_strategy")
    assert len(exits) == 1
    assert exits[0].quantity == 5
    assert "partial" in exits[0].reason.lower()


def test_trailing_exit_triggers_after_partial_take_profit_atr_mode() -> None:
    cfg = BullStrategyConfig(trailing_mode="atr", trailing_atr_multiplier=2.0)
    position = pd.Series(
        {
            "average_price": 100.0,
            "quantity": 5,
            "hold_days": 4,
            "first_take_profit_done": True,
            "highest_price_since_entry": 112.0,
        }
    )
    # trailing stop = 112 - (2 * 2.0) = 108
    signal = {"close": 107.5, "atr14": 2.0, "low_n": 106.0, "ma20": 105.0}
    exits = _build_exit_signals("005930", signal, position, cfg, "bull_strategy")
    assert len(exits) == 1
    assert exits[0].quantity == 5
    assert "trailing" in exits[0].reason.lower()


def test_trailing_not_applied_before_first_take_profit_done() -> None:
    cfg = BullStrategyConfig(trailing_mode="atr", trailing_atr_multiplier=2.0)
    position = pd.Series(
        {
            "average_price": 100.0,
            "quantity": 10,
            "hold_days": 2,
            "first_take_profit_done": False,
            "highest_price_since_entry": 112.0,
        }
    )
    signal = {"close": 107.0, "atr14": 2.0, "low_n": 106.0, "ma20": 105.0}
    exits = _build_exit_signals("005930", signal, position, cfg, "bull_strategy")
    assert exits == []


def test_trailing_exit_triggers_on_n_day_low_break() -> None:
    cfg = BullStrategyConfig(trailing_mode="n_day_low")
    position = pd.Series(
        {
            "average_price": 100.0,
            "quantity": 5,
            "hold_days": 3,
            "first_take_profit_done": True,
            "highest_price_since_entry": 111.0,
        }
    )
    signal = {"close": 103.0, "atr14": 1.5, "low_n": 103.5, "ma20": 104.0}
    exits = _build_exit_signals("005930", signal, position, cfg, "bull_strategy")
    assert len(exits) == 1
    assert exits[0].quantity == 5


def test_trailing_trigger_helper_returns_false_when_not_breached() -> None:
    hit = _trailing_stop_triggered(
        close=110.0,
        atr=1.5,
        low_n=107.0,
        highest_price=113.0,
        mode="atr",
        atr_multiplier=2.0,
    )
    assert hit is False


def test_partial_sell_marks_trailing_state_for_remaining_position() -> None:
    position = Position(
        symbol="005930",
        quantity=10,
        average_price=100.0,
        initial_quantity=10,
        realized_sell_quantity=0,
        first_take_profit_done=False,
        trailing_active=False,
        highest_price_since_entry=110.0,
    )
    updated = apply_sell_fill(position, quantity=5, mark_first_take_profit=True)
    assert updated is not None
    assert updated.quantity == 5
    assert updated.first_take_profit_done is True
    assert updated.trailing_active is True
