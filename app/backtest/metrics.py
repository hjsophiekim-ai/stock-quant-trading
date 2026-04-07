from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class BacktestMetrics:
    total_return_pct: float
    monthly_returns: dict[str, float]
    monthly_return_stability: float
    max_drawdown_pct: float
    win_rate: float
    payoff_ratio: float
    profit_factor: float
    regime_performance: dict[str, dict[str, float]]


def calculate_metrics(*, equity_curve: pd.Series, trades: list[object]) -> BacktestMetrics:
    total_return = _total_return_pct(equity_curve)
    monthly = _monthly_return_pct(equity_curve)
    stability = _monthly_return_stability(monthly)
    max_dd = _max_drawdown_pct(equity_curve)
    win_rate = _win_rate(trades)
    payoff = _payoff_ratio(trades)
    pf = _profit_factor(trades)
    regime_perf = _regime_performance(trades)
    return BacktestMetrics(
        total_return_pct=total_return,
        monthly_returns=monthly,
        monthly_return_stability=stability,
        max_drawdown_pct=max_dd,
        win_rate=win_rate,
        payoff_ratio=payoff,
        profit_factor=pf,
        regime_performance=regime_perf,
    )


def _total_return_pct(equity_curve: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    start = float(equity_curve.iloc[0])
    end = float(equity_curve.iloc[-1])
    if start <= 0:
        return 0.0
    return ((end / start) - 1.0) * 100.0


def _monthly_return_pct(equity_curve: pd.Series) -> dict[str, float]:
    if equity_curve.empty:
        return {}
    s = equity_curve.copy()
    s.index = pd.to_datetime(s.index)
    monthly_last = s.resample("ME").last()
    monthly_ret = monthly_last.pct_change().fillna(0.0) * 100.0
    return {idx.strftime("%Y-%m"): float(val) for idx, val in monthly_ret.items()}


def _max_drawdown_pct(equity_curve: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    running_max = equity_curve.cummax()
    dd = (equity_curve / running_max) - 1.0
    return float(dd.min() * 100.0)


def _monthly_return_stability(monthly_returns: dict[str, float]) -> float:
    if not monthly_returns:
        return 0.0
    values = pd.Series(list(monthly_returns.values()), dtype="float64")
    std = float(values.std(ddof=0))
    # Higher is better: 1/(1+std) in 0~1 range.
    return 1.0 / (1.0 + max(std, 0.0))


def _win_rate(trades: list[object]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl > 0)
    return wins / len(trades)


def _payoff_ratio(trades: list[object]) -> float:
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [abs(t.pnl) for t in trades if t.pnl < 0]
    if not wins or not losses:
        return 0.0
    return (sum(wins) / len(wins)) / (sum(losses) / len(losses))


def _profit_factor(trades: list[object]) -> float:
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    if gross_loss == 0:
        return 0.0
    return gross_profit / gross_loss


def _regime_performance(trades: list[object]) -> dict[str, dict[str, float]]:
    if not trades:
        return {}
    rows = []
    for t in trades:
        rows.append({"regime": t.regime, "pnl": t.pnl, "win": 1 if t.pnl > 0 else 0})
    df = pd.DataFrame(rows)
    grouped = df.groupby("regime", dropna=False)
    result: dict[str, dict[str, float]] = {}
    for regime, g in grouped:
        result[str(regime)] = {
            "trades": float(len(g)),
            "total_pnl": float(g["pnl"].sum()),
            "avg_pnl": float(g["pnl"].mean()),
            "win_rate": float(g["win"].mean()),
        }
    return result
