from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from app.backtest.engine import BacktestConfig, BacktestResult, TradeRecord, run_backtest


@dataclass(frozen=True)
class WalkForwardFold:
    fold_id: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    selected_params: dict[str, Any]
    train_score: float
    test_result: BacktestResult


@dataclass(frozen=True)
class WalkForwardResult:
    folds: list[WalkForwardFold]
    summary: dict[str, float]


def build_time_splits(
    *,
    dates: pd.Series,
    train_months: int = 12,
    test_months: int = 3,
    step_months: int = 3,
) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    s = pd.Series(pd.to_datetime(dates).dropna().sort_values().unique())
    if s.empty:
        return []

    start = s.min()
    end = s.max()
    splits: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
    cursor = pd.Timestamp(start)
    while True:
        train_start = cursor
        train_end = train_start + pd.DateOffset(months=train_months) - pd.Timedelta(days=1)
        test_start = train_end + pd.Timedelta(days=1)
        test_end = test_start + pd.DateOffset(months=test_months) - pd.Timedelta(days=1)
        if test_end > end:
            break
        splits.append((train_start, train_end, test_start, test_end))
        cursor = cursor + pd.DateOffset(months=step_months)
    return splits


def walk_forward_validate(
    *,
    data: pd.DataFrame,
    parameter_grid: list[dict[str, Any]],
    trade_builder: Callable[[pd.DataFrame, dict[str, Any]], list[TradeRecord]],
    objective_fn: Callable[[BacktestResult], float] | None = None,
    backtest_config: BacktestConfig = BacktestConfig(),
    train_months: int = 12,
    test_months: int = 3,
    step_months: int = 3,
) -> WalkForwardResult:
    if "date" not in data.columns:
        raise ValueError("data must include 'date' column")
    if not parameter_grid:
        raise ValueError("parameter_grid must not be empty")

    objective = objective_fn or default_objective
    splits = build_time_splits(
        dates=data["date"],
        train_months=train_months,
        test_months=test_months,
        step_months=step_months,
    )
    folds: list[WalkForwardFold] = []
    for i, (tr_s, tr_e, te_s, te_e) in enumerate(splits, start=1):
        train_df = _slice_by_date(data, tr_s, tr_e)
        test_df = _slice_by_date(data, te_s, te_e)
        if train_df.empty or test_df.empty:
            continue

        best_params = parameter_grid[0]
        best_score = float("-inf")
        for params in parameter_grid:
            train_trades = trade_builder(train_df, params)
            train_result = run_backtest(trades=train_trades, config=backtest_config)
            score = objective(train_result)
            if score > best_score:
                best_score = score
                best_params = params

        test_trades = trade_builder(test_df, best_params)
        test_result = run_backtest(trades=test_trades, config=backtest_config)
        folds.append(
            WalkForwardFold(
                fold_id=i,
                train_start=tr_s,
                train_end=tr_e,
                test_start=te_s,
                test_end=te_e,
                selected_params=best_params,
                train_score=best_score,
                test_result=test_result,
            )
        )

    summary = summarize_walkforward(folds)
    return WalkForwardResult(folds=folds, summary=summary)


def default_objective(result: BacktestResult) -> float:
    # Prefer robust profiles: return - drawdown penalty.
    return result.metrics.total_return_pct + (result.metrics.max_drawdown_pct * 0.5)


def summarize_walkforward(folds: list[WalkForwardFold]) -> dict[str, float]:
    if not folds:
        return {"folds": 0.0, "avg_test_return_pct": 0.0, "avg_test_max_drawdown_pct": 0.0}
    returns = [f.test_result.metrics.total_return_pct for f in folds]
    mdds = [f.test_result.metrics.max_drawdown_pct for f in folds]
    return {
        "folds": float(len(folds)),
        "avg_test_return_pct": float(sum(returns) / len(returns)),
        "avg_test_max_drawdown_pct": float(sum(mdds) / len(mdds)),
    }


def _slice_by_date(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    return d[(d["date"] >= start) & (d["date"] <= end)]
