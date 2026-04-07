from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from app.backtest.engine import BacktestConfig, TradeRecord, run_backtest
from app.backtest.walkforward import walk_forward_validate


def _trade(day: int, pnl: float, regime: str) -> TradeRecord:
    base = datetime(2025, 1, 1)
    entry = base + timedelta(days=day)
    exit_ = entry + timedelta(days=1)
    qty = 10
    entry_price = 100.0
    exit_price = entry_price + (pnl / qty)
    return TradeRecord(
        symbol="AAA",
        entry_time=entry,
        exit_time=exit_,
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=qty,
        pnl=pnl,
        return_pct=(pnl / (entry_price * qty)) * 100.0,
        regime=regime,
    )


def test_backtest_metrics_include_requested_fields() -> None:
    trades = [
        _trade(0, 10_000.0, "bullish_trend"),
        _trade(10, -6_000.0, "bearish_trend"),
        _trade(20, 4_000.0, "sideways"),
    ]
    result = run_backtest(trades=trades, config=BacktestConfig(initial_capital=1_000_000.0))
    assert isinstance(result.metrics.total_return_pct, float)
    assert result.metrics.monthly_returns
    assert isinstance(result.metrics.max_drawdown_pct, float)
    assert 0.0 <= result.metrics.win_rate <= 1.0
    assert isinstance(result.metrics.payoff_ratio, float)
    assert isinstance(result.metrics.profit_factor, float)
    assert "bullish_trend" in result.metrics.regime_performance


def test_walkforward_validation_runs_and_returns_fold_summary() -> None:
    base = datetime(2024, 1, 1)
    data = pd.DataFrame(
        [
            {"date": base + timedelta(days=i), "close": 100.0 + i * 0.2}
            for i in range(480)
        ]
    )

    def trade_builder(df: pd.DataFrame, params: dict[str, float]) -> list[TradeRecord]:
        step = int(params["step"])
        trades: list[TradeRecord] = []
        for i in range(0, max(len(df) - 2, 0), step):
            pnl = 2500.0 if i % (step * 2) == 0 else -1200.0
            regime = "bullish_trend" if pnl > 0 else "sideways"
            trades.append(_trade(i, pnl, regime))
        return trades

    wf = walk_forward_validate(
        data=data,
        parameter_grid=[{"step": 20}, {"step": 30}],
        trade_builder=trade_builder,
        train_months=6,
        test_months=2,
        step_months=2,
    )
    assert wf.summary["folds"] > 0
    assert "avg_test_return_pct" in wf.summary
    assert "avg_test_max_drawdown_pct" in wf.summary
