from __future__ import annotations

import pandas as pd
from dataclasses import dataclass


def unrealized_pnl(entry_price: float, current_price: float, quantity: int) -> float:
    return (current_price - entry_price) * quantity


def pnl_pct(equity_start: float, equity_now: float) -> float:
    if equity_start <= 0:
        return 0.0
    return ((equity_now / equity_start) - 1.0) * 100.0


def realized_pnl(entry_price: float, exit_price: float, quantity: int) -> float:
    return (exit_price - entry_price) * quantity


def compute_daily_return_pct(equity_series: pd.Series) -> pd.Series:
    if equity_series.empty:
        return pd.Series(dtype="float64")
    return equity_series.pct_change().fillna(0.0) * 100.0


def compute_cumulative_return_pct(equity_series: pd.Series) -> pd.Series:
    if equity_series.empty:
        return pd.Series(dtype="float64")
    base = float(equity_series.iloc[0])
    if base <= 0:
        return pd.Series([0.0] * len(equity_series), index=equity_series.index, dtype="float64")
    return ((equity_series / base) - 1.0) * 100.0


def split_trade_realized_pnl(
    buy_fills: list[tuple[int, float]],
    sell_fills: list[tuple[int, float]],
) -> float:
    total_buy_qty = sum(q for q, _ in buy_fills)
    if total_buy_qty <= 0:
        return 0.0
    avg_buy_price = sum(q * p for q, p in buy_fills) / total_buy_qty
    return sum((sell_price - avg_buy_price) * sell_qty for sell_qty, sell_price in sell_fills)


@dataclass(frozen=True)
class TradePerformanceSummary:
    window: int
    total_pnl: float
    avg_pnl: float
    win_rate: float
    consecutive_losses: int
    rolling_pnl_pct: float


def summarize_recent_trade_performance(
    trade_pnls: list[float],
    *,
    equity: float,
    window: int = 10,
) -> TradePerformanceSummary:
    if window <= 0:
        window = 1
    samples = trade_pnls[-window:]
    if not samples:
        return TradePerformanceSummary(
            window=window,
            total_pnl=0.0,
            avg_pnl=0.0,
            win_rate=0.0,
            consecutive_losses=0,
            rolling_pnl_pct=0.0,
        )
    total = float(sum(samples))
    avg = total / len(samples)
    wins = sum(1 for x in samples if x > 0)
    win_rate = wins / len(samples)
    consec_losses = consecutive_loss_streak(samples)
    rolling_pct = (total / equity) * 100.0 if equity > 0 else 0.0
    return TradePerformanceSummary(
        window=window,
        total_pnl=total,
        avg_pnl=avg,
        win_rate=win_rate,
        consecutive_losses=consec_losses,
        rolling_pnl_pct=rolling_pct,
    )


def consecutive_loss_streak(trade_pnls: list[float]) -> int:
    streak = 0
    for pnl in reversed(trade_pnls):
        if pnl < 0:
            streak += 1
            continue
        break
    return streak
