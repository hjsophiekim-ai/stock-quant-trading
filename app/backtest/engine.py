from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from app.backtest.metrics import BacktestMetrics, calculate_metrics


@dataclass(frozen=True)
class TradeRecord:
    symbol: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    return_pct: float
    regime: str = "unknown"
    side: str = "long"


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 10_000_000.0
    fee_rate: float = 0.00015
    slippage_bps: float = 2.0


@dataclass(frozen=True)
class BacktestResult:
    trades: list[TradeRecord]
    equity_curve: pd.Series
    metrics: BacktestMetrics
    metadata: dict[str, Any] = field(default_factory=dict)


def run_backtest(*, trades: list[TradeRecord], config: BacktestConfig = BacktestConfig()) -> BacktestResult:
    normalized = _apply_costs(trades, config)
    equity = build_equity_curve(normalized, initial_capital=config.initial_capital)
    metrics = calculate_metrics(equity_curve=equity, trades=normalized)
    return BacktestResult(
        trades=normalized,
        equity_curve=equity,
        metrics=metrics,
        metadata={
            "initial_capital": config.initial_capital,
            "fee_rate": config.fee_rate,
            "slippage_bps": config.slippage_bps,
            "trade_count": len(normalized),
        },
    )


def build_equity_curve(trades: list[TradeRecord], *, initial_capital: float) -> pd.Series:
    if initial_capital <= 0:
        raise ValueError("initial_capital must be positive")

    if not trades:
        return pd.Series([initial_capital], index=[pd.Timestamp("1970-01-01")], dtype="float64")

    rows = sorted(trades, key=lambda t: t.exit_time)
    equity_values: list[float] = [initial_capital]
    timestamps: list[pd.Timestamp] = [pd.Timestamp(rows[0].entry_time)]
    running = initial_capital
    for tr in rows:
        running += tr.pnl
        timestamps.append(pd.Timestamp(tr.exit_time))
        equity_values.append(running)
    return pd.Series(equity_values, index=timestamps, dtype="float64")


def _apply_costs(trades: list[TradeRecord], config: BacktestConfig) -> list[TradeRecord]:
    adjusted: list[TradeRecord] = []
    for tr in trades:
        gross_notional = (tr.entry_price + tr.exit_price) * tr.quantity
        fee = gross_notional * config.fee_rate
        slippage = gross_notional * (config.slippage_bps / 10_000.0)
        net_pnl = tr.pnl - fee - slippage
        ret_base = max(tr.entry_price * tr.quantity, 1e-9)
        ret_pct = (net_pnl / ret_base) * 100.0
        adjusted.append(
            TradeRecord(
                symbol=tr.symbol,
                entry_time=tr.entry_time,
                exit_time=tr.exit_time,
                entry_price=tr.entry_price,
                exit_price=tr.exit_price,
                quantity=tr.quantity,
                pnl=net_pnl,
                return_pct=ret_pct,
                regime=tr.regime,
                side=tr.side,
            )
        )
    return adjusted
