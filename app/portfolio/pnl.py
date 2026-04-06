from __future__ import annotations

import pandas as pd


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
