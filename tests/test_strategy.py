import pandas as pd

from app.strategy.swing_strategy import (
    SwingStrategyConfig,
    _build_exit_orders,
    _build_split_buy_orders,
    should_enter_long,
)


def test_should_enter_long_when_all_conditions_match() -> None:
    signal = {
        "ma20_gt_ma60": True,
        "drop_3d_in_range": True,
        "rsi_lt_40": True,
        "bullish_reversal": True,
        "close": 100.0,
    }
    assert should_enter_long(signal) is True


def test_should_enter_long_fails_when_one_condition_is_false() -> None:
    signal = {
        "ma20_gt_ma60": True,
        "drop_3d_in_range": False,
        "rsi_lt_40": True,
        "bullish_reversal": True,
        "close": 100.0,
    }
    assert should_enter_long(signal) is False


def test_split_buy_orders_are_evenly_sized() -> None:
    cfg = SwingStrategyConfig(order_quantity=10, stop_loss_pct=4.0)
    orders = _build_split_buy_orders("005930", cfg)
    assert len(orders) == 2
    assert orders[0].quantity == 5
    assert orders[1].quantity == 5
    assert all(o.side == "buy" for o in orders)


def test_exit_orders_stop_loss_has_priority() -> None:
    cfg = SwingStrategyConfig(stop_loss_pct=4.0, first_take_profit_pct=6.0, second_take_profit_pct=10.0)
    position = pd.Series({"average_price": 100.0, "quantity": 10, "hold_days": 2})
    signal = {"close": 95.9}  # -4.1%
    orders = _build_exit_orders("005930", signal, position, cfg)
    assert len(orders) == 1
    assert orders[0].side == "sell"
    assert orders[0].quantity == 10


def test_exit_orders_partial_take_profit_at_six_percent() -> None:
    cfg = SwingStrategyConfig(first_take_profit_pct=6.0, second_take_profit_pct=10.0)
    position = pd.Series({"average_price": 100.0, "quantity": 10, "hold_days": 2})
    signal = {"close": 106.0}
    orders = _build_exit_orders("005930", signal, position, cfg)
    assert len(orders) == 1
    assert orders[0].side == "sell"
    assert orders[0].quantity == 5
