from __future__ import annotations

from backend.app.risk.live_exit_rules import evaluate_exit_for_position


def test_stop_loss_triggers_sell() -> None:
    st: dict = {}
    d = evaluate_exit_for_position(
        symbol="AAA",
        quantity=10,
        average_price=100.0,
        last_price=98.0,
        state=st,
        stop_loss_enabled=True,
        take_profit_enabled=False,
        trailing_enabled=False,
        stop_loss_pct=0.015,
    )
    assert d.should_sell is True
    assert "stop_loss" in d.reason


def test_take_profit_triggers_sell() -> None:
    st: dict = {}
    d = evaluate_exit_for_position(
        symbol="AAA",
        quantity=10,
        average_price=100.0,
        last_price=103.0,
        state=st,
        stop_loss_enabled=False,
        take_profit_enabled=True,
        trailing_enabled=False,
        take_profit_pct=0.02,
    )
    assert d.should_sell is True
    assert "take_profit" in d.reason


def test_trailing_stop_triggers_sell_after_peak() -> None:
    st: dict = {}
    d0 = evaluate_exit_for_position(
        symbol="AAA",
        quantity=10,
        average_price=100.0,
        last_price=104.0,
        state=st,
        stop_loss_enabled=False,
        take_profit_enabled=False,
        trailing_enabled=True,
        trailing_start_profit_pct=0.02,
        trailing_gap_pct=0.012,
    )
    assert d0.should_sell is False
    d1 = evaluate_exit_for_position(
        symbol="AAA",
        quantity=10,
        average_price=100.0,
        last_price=102.5,
        state=st,
        stop_loss_enabled=False,
        take_profit_enabled=False,
        trailing_enabled=True,
        trailing_start_profit_pct=0.02,
        trailing_gap_pct=0.012,
    )
    assert d1.should_sell is True
    assert "trailing_stop" in d1.reason

