"""멀티 전략 라우터: 종목 배정·노셔널."""

from __future__ import annotations

from backend.app.engine.portfolio_strategy_router import notionals_for_legs, route_swing_vs_scalp_symbols
from app.strategy.paper_position_sizing import compute_intraday_buy_quantity


def test_route_prefers_scalp_on_overlap() -> None:
    r = route_swing_vs_scalp_symbols(
        swing_csv="005930,000660",
        intraday_symbols=["005930", "035420"],
        prefer_scalp_on_overlap=True,
    )
    assert "005930" not in r.swing_symbols
    assert "005930" in r.scalp_symbols
    assert "000660" in r.swing_symbols
    assert any(d.get("symbol") == "005930" for d in r.diagnostics)


def test_route_prefers_swing_when_flag_false() -> None:
    r = route_swing_vs_scalp_symbols(
        swing_csv="005930",
        intraday_symbols=["005930"],
        prefer_scalp_on_overlap=False,
    )
    assert "005930" in r.swing_symbols
    assert "005930" not in r.scalp_symbols


def test_notionals_scale_down_by_cash() -> None:
    n = notionals_for_legs(equity_krw=10_000_000, cash_krw=1_000_000, swing_pct=60.0, intraday_pct=40.0)
    assert n["swing_notional_krw"] + n["intraday_notional_krw"] <= 1_000_000 + 1e-6


def test_compute_intraday_buy_quantity_min_one() -> None:
    q = compute_intraday_buy_quantity(
        price_krw=50_000,
        stop_loss_pct_points=0.5,
        equity_krw=10_000_000,
        intraday_budget_krw=4_000_000,
        max_position_pct=8.0,
        risk_per_trade_pct=0.45,
        fallback_qty=1,
    )
    assert q >= 1
