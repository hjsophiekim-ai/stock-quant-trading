from datetime import datetime, timedelta, timezone

from app.orders.models import OrderRequest
from app.portfolio.pnl import build_adaptive_defense_snapshot, summarize_recent_trade_performance
from app.risk.kill_switch import KillSwitch
from app.risk.rules import RiskLimits, RiskRules, RiskSnapshot


def test_rolling_loss_limit_halts_new_entries() -> None:
    rules = RiskRules(limits=RiskLimits(rolling_loss_window_trades=5, rolling_loss_limit_pct=2.0))
    snapshot = RiskSnapshot(
        daily_pnl_pct=0.0,
        total_pnl_pct=0.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
        recent_trade_pnls=(-8000.0, -7000.0, -6000.0, -3000.0, -2000.0),
    )
    decision = rules.evaluate_global_guard(snapshot)
    assert decision.approved is False
    assert decision.reason_code == "HALT_ROLLING_LOSS_LIMIT"


def test_adaptive_new_entry_limit_blocks_after_loss_streak() -> None:
    rules = RiskRules(limits=RiskLimits(adaptive_loss_streak_threshold=3, adaptive_new_entries_limit=1))
    snapshot = RiskSnapshot(
        daily_pnl_pct=-0.3,
        total_pnl_pct=-1.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
        consecutive_losses=3,
        recent_trade_pnls=(-500.0, -400.0, -300.0, -200.0),
        todays_new_entries=1,
    )
    order = OrderRequest(symbol="005930", side="buy", quantity=11, price=10_000.0, stop_loss_pct=3.0)
    decision = rules.approve_order(order=order, snapshot=snapshot)
    assert decision.approved is False
    assert decision.reason_code == "ADAPTIVE_NEW_ENTRY_LIMIT"


def test_trading_cooldown_active_blocks_buy() -> None:
    rules = RiskRules()
    snapshot = RiskSnapshot(
        daily_pnl_pct=0.0,
        total_pnl_pct=0.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
        trading_cooldown_until=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    order = OrderRequest(symbol="005930", side="buy", quantity=10, price=10_000.0, stop_loss_pct=3.0)
    decision = rules.approve_order(order=order, snapshot=snapshot)
    assert decision.approved is False
    assert decision.reason_code == "TRADING_COOLDOWN_ACTIVE"


def test_kill_switch_recommends_cooldown_on_loss_streak() -> None:
    rules = RiskRules(limits=RiskLimits(adaptive_loss_streak_threshold=3, adaptive_trading_cooldown_minutes=60))
    ks = KillSwitch(rules=rules)
    snapshot = RiskSnapshot(
        daily_pnl_pct=0.0,
        total_pnl_pct=0.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
        consecutive_losses=3,
    )
    cooldown_until = ks.recommend_cooldown_until(snapshot)
    assert cooldown_until is not None


def test_recent_trade_performance_summary() -> None:
    summary = summarize_recent_trade_performance(
        trade_pnls=[1000.0, -500.0, -700.0, -200.0, 300.0, -100.0],
        equity=1_000_000.0,
        window=5,
    )
    assert summary.window == 5
    assert summary.total_pnl == -1200.0
    assert summary.consecutive_losses == 1
    assert summary.rolling_pnl_pct < 0


def test_adaptive_entry_filter_blocks_low_score_in_defense_mode() -> None:
    rules = RiskRules(
        limits=RiskLimits(
            adaptive_loss_streak_threshold=3,
            adaptive_min_entry_score=0.7,
            adaptive_enable_entry_filter=True,
        )
    )
    snapshot = RiskSnapshot(
        daily_pnl_pct=-0.2,
        total_pnl_pct=-1.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
        consecutive_losses=3,
        recent_trade_pnls=(-500.0, -400.0, -250.0),
        latest_entry_score=0.55,
    )
    order = OrderRequest(symbol="005930", side="buy", quantity=10, price=10_000.0, stop_loss_pct=2.5)
    decision = rules.approve_order(order=order, snapshot=snapshot)
    assert decision.approved is False
    assert decision.reason_code == "ADAPTIVE_ENTRY_FILTER_BLOCK"


def test_adaptive_defense_snapshot_detects_deterioration() -> None:
    snap = build_adaptive_defense_snapshot(
        trade_pnls=[-3000.0, -3500.0, -2000.0, -1500.0],
        equity=1_000_000.0,
        window=4,
        loss_streak_threshold=3,
        performance_floor_pct=-0.5,
    )
    assert snap.performance_deteriorating is True
    assert snap.defense_mode is True
