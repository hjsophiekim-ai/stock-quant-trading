from datetime import datetime, timezone

from app.orders.models import OrderRequest
from app.risk.position_sizing import max_holding_days_for_regime, size_position_by_regime
from app.risk.rules import RiskRules, RiskSnapshot


def test_bearish_blocks_when_position_weight_too_high() -> None:
    rules = RiskRules()
    snapshot = RiskSnapshot(
        daily_pnl_pct=0.0,
        total_pnl_pct=0.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
        market_regime="bearish_trend",
    )
    # 100,000 value = 10% of equity, above bearish max 8%
    order = OrderRequest(symbol="005930", side="buy", quantity=10, price=10_000.0, stop_loss_pct=2.0)
    decision = rules.approve_order(order=order, snapshot=snapshot, now=datetime.now(timezone.utc))
    assert decision.approved is False
    assert decision.reason_code == "BLOCK_REGIME_BEARISH_POSITION_WEIGHT"


def test_bearish_blocks_when_stop_loss_too_wide() -> None:
    rules = RiskRules()
    snapshot = RiskSnapshot(
        daily_pnl_pct=0.0,
        total_pnl_pct=0.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
        market_regime="bearish_trend",
    )
    order = OrderRequest(symbol="005930", side="buy", quantity=6, price=10_000.0, stop_loss_pct=4.0)
    decision = rules.approve_order(order=order, snapshot=snapshot)
    assert decision.approved is False
    assert decision.reason_code == "BLOCK_REGIME_BEARISH_STOP_LOSS_TOO_WIDE"


def test_bearish_blocks_when_daily_new_entries_limit_reached() -> None:
    rules = RiskRules()
    snapshot = RiskSnapshot(
        daily_pnl_pct=0.0,
        total_pnl_pct=0.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
        market_regime="bearish_trend",
        todays_new_entries=1,
    )
    order = OrderRequest(symbol="035720", side="buy", quantity=4, price=12_000.0, stop_loss_pct=2.0)
    decision = rules.approve_order(order=order, snapshot=snapshot)
    assert decision.approved is False
    assert decision.reason_code == "BLOCK_REGIME_BEARISH_NEW_ENTRY_LIMIT"


def test_high_volatility_blocks_new_buy_entries() -> None:
    rules = RiskRules()
    snapshot = RiskSnapshot(
        daily_pnl_pct=0.0,
        total_pnl_pct=0.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
        market_regime="high_volatility_risk",
    )
    order = OrderRequest(symbol="005930", side="buy", quantity=5, price=10_000.0, stop_loss_pct=2.0)
    decision = rules.approve_order(order=order, snapshot=snapshot)
    assert decision.approved is False
    assert decision.reason_code == "BLOCK_REGIME_HIGH_VOLATILITY_NEW_ENTRY"


def test_high_volatility_still_allows_sell_for_risk_reduction() -> None:
    rules = RiskRules()
    snapshot = RiskSnapshot(
        daily_pnl_pct=0.0,
        total_pnl_pct=0.0,
        equity=1_000_000.0,
        market_filter_ok=False,
        position_values={"005930": 60_000.0},
        market_regime="high_volatility_risk",
    )
    order = OrderRequest(symbol="005930", side="sell", quantity=3, price=9_500.0, stop_loss_pct=None)
    decision = rules.approve_order(order=order, snapshot=snapshot)
    assert decision.approved is True
    assert decision.reason_code == "OK_SELL"


def test_regime_position_sizing_is_more_conservative_in_bear_market() -> None:
    bullish = size_position_by_regime(regime="bullish_trend", equity=1_000_000.0, entry_price=10_000.0)
    bearish = size_position_by_regime(regime="bearish_trend", equity=1_000_000.0, entry_price=10_000.0)
    assert bearish.quantity < bullish.quantity
    assert max_holding_days_for_regime("bearish_trend") < max_holding_days_for_regime("bullish_trend")


def test_bearish_buy_approval_returns_regime_specific_reason_code() -> None:
    rules = RiskRules()
    snapshot = RiskSnapshot(
        daily_pnl_pct=0.0,
        total_pnl_pct=0.0,
        equity=1_000_000.0,
        market_filter_ok=True,
        position_values={},
        market_regime="bearish_trend",
        todays_new_entries=0,
    )
    order = OrderRequest(symbol="005930", side="buy", quantity=4, price=10_000.0, stop_loss_pct=2.0)
    decision = rules.approve_order(order=order, snapshot=snapshot)
    assert decision.approved is True
    assert decision.reason_code == "OK_REGIME_BEARISH_BUY_CONSERVATIVE"
