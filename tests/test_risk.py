from datetime import datetime, timedelta, timezone

from app.orders.models import OrderRequest
from app.risk.kill_switch import KillSwitch
from app.risk.rules import RiskLimits, RiskRules, RiskSnapshot


def _base_snapshot() -> RiskSnapshot:
    return RiskSnapshot(
        daily_pnl_pct=0.0,
        total_pnl_pct=0.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
    )


def test_daily_loss_limit_blocks_trading() -> None:
    rules = RiskRules()
    snapshot = RiskSnapshot(
        daily_pnl_pct=-3.1,
        total_pnl_pct=-1.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
    )
    decision = rules.evaluate_global_guard(snapshot)
    assert decision.approved is False
    assert decision.reason_code == "HALT_DAILY_LOSS"


def test_kill_switch_only_aborts_cycle_on_total_loss_not_daily() -> None:
    rules = RiskRules()
    ks = KillSwitch(rules=rules)
    daily = RiskSnapshot(
        daily_pnl_pct=-3.5,
        total_pnl_pct=-2.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
    )
    assert ks.evaluate(daily) is False
    assert ks.system_risk_off is False
    assert ks.new_entries_blocked is True

    total = RiskSnapshot(
        daily_pnl_pct=-5.0,
        total_pnl_pct=-10.5,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
    )
    assert ks.evaluate(total) is True
    assert ks.system_risk_off is True


def test_total_loss_limit_turns_system_off() -> None:
    rules = RiskRules()
    snapshot = RiskSnapshot(
        daily_pnl_pct=-1.0,
        total_pnl_pct=-10.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
    )
    decision = rules.evaluate_global_guard(snapshot)
    assert decision.approved is False
    assert decision.reason_code == "SYSTEM_OFF_TOTAL_LOSS"
    assert decision.is_hard_stop is True


def test_stop_loss_priority_sell_allowed_even_if_market_filter_bad() -> None:
    rules = RiskRules()
    snapshot = RiskSnapshot(
        daily_pnl_pct=-1.0,
        total_pnl_pct=-1.0,
        equity=1_000_000.0,
        market_filter_ok=False,
        position_values={"005930": 120_000.0},
    )
    order = OrderRequest(symbol="005930", side="sell", quantity=10, price=95.0, stop_loss_pct=None)
    decision = rules.approve_order(order=order, snapshot=snapshot)
    assert decision.approved is True
    assert decision.reason_code == "OK_SELL"


def test_buy_blocked_when_market_filter_is_bad() -> None:
    rules = RiskRules()
    snapshot = RiskSnapshot(
        daily_pnl_pct=0.5,
        total_pnl_pct=1.2,
        equity=1_000_000.0,
        market_filter_ok=False,
        position_values={},
    )
    order = OrderRequest(symbol="005930", side="buy", quantity=15, price=8_000.0, stop_loss_pct=4.0)
    decision = rules.approve_order(order=order, snapshot=snapshot)
    assert decision.approved is False
    assert decision.reason_code == "BLOCK_BAD_MARKET_FILTER"


def test_sell_allowed_when_daily_loss_limit_hit() -> None:
    rules = RiskRules()
    snapshot = RiskSnapshot(
        daily_pnl_pct=-3.5,
        total_pnl_pct=-2.0,
        equity=1_000_000.0,
        market_filter_ok=False,
        position_values={"005930": 50_000.0},
    )
    order = OrderRequest(symbol="005930", side="sell", quantity=5, price=9_000.0, stop_loss_pct=None)
    decision = rules.approve_order(order=order, snapshot=snapshot)
    assert decision.approved is True
    assert decision.reason_code == "OK_SELL"


def test_buy_blocked_when_daily_loss_limit_hit() -> None:
    rules = RiskRules()
    snapshot = RiskSnapshot(
        daily_pnl_pct=-3.5,
        total_pnl_pct=-2.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
    )
    order = OrderRequest(symbol="005930", side="buy", quantity=5, price=10_000.0, stop_loss_pct=3.0)
    decision = rules.approve_order(order=order, snapshot=snapshot)
    assert decision.approved is False
    assert decision.reason_code == "HALT_DAILY_LOSS"


def test_single_order_notional_cap_blocks_oversized_buy() -> None:
    rules = RiskRules(limits=RiskLimits(max_single_order_notional_pct=20.0))
    snapshot = RiskSnapshot(
        daily_pnl_pct=0.0,
        total_pnl_pct=0.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
    )
    # 30 * 10_000 = 300k > 20% of 1M
    order = OrderRequest(symbol="005930", side="buy", quantity=30, price=10_000.0, stop_loss_pct=3.0)
    decision = rules.approve_order(order=order, snapshot=snapshot)
    assert decision.approved is False
    assert decision.reason_code == "ORDER_NOTIONAL_EXCEEDS_CAP"


def test_reentry_cooldown_blocks_same_symbol_buy() -> None:
    rules = RiskRules()
    now = datetime(2026, 4, 6, 9, 0, tzinfo=timezone.utc)
    snapshot = RiskSnapshot(
        daily_pnl_pct=0.2,
        total_pnl_pct=0.5,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
        cooldown_until={"005930": now + timedelta(minutes=30)},
    )
    order = OrderRequest(symbol="005930", side="buy", quantity=12, price=10_000.0, stop_loss_pct=4.0)
    decision = rules.approve_order(order=order, snapshot=snapshot, now=now)
    assert decision.approved is False
    assert decision.reason_code == "REENTRY_COOLDOWN"
