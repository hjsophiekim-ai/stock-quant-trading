from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.strategy.base_strategy import BaseStrategy, StrategyContext, StrategySignal
from app.strategy.indicators import add_basic_indicators


@dataclass(frozen=True)
class BearStrategyConfig:
    order_quantity: int = 3
    stop_loss_pct: float = 2.0
    first_take_profit_pct: float = 2.5
    second_take_profit_pct: float = 4.0
    time_exit_days: int = 2
    max_new_entries_per_cycle: int = 1
    allow_new_entries: bool = True


@dataclass
class BearStrategy(BaseStrategy):
    config: BearStrategyConfig = BearStrategyConfig()

    def generate_signals(self, context: StrategyContext) -> list[StrategySignal]:
        signals: list[StrategySignal] = []
        new_entry_count = 0
        for symbol, symbol_df in context.prices.groupby("symbol", sort=False):
            signal = _build_symbol_signal(symbol_df)
            position = _get_position_row(context.portfolio, symbol)
            if position is None:
                if self.config.allow_new_entries and new_entry_count < self.config.max_new_entries_per_cycle and _should_enter_defensive_rebound(signal):
                    signals.append(
                        StrategySignal(
                            symbol=symbol,
                            side="buy",
                            quantity=self.config.order_quantity,
                            price=None,
                            stop_loss_pct=self.config.stop_loss_pct,
                            reason="Defensive short rebound entry",
                            strategy_name="bear_strategy",
                        )
                    )
                    new_entry_count += 1
            else:
                signals.extend(_build_exit_signals(symbol, signal, position, self.config))
        return signals


def _build_symbol_signal(symbol_df: pd.DataFrame) -> dict[str, float | bool]:
    enriched = add_basic_indicators(symbol_df.sort_values("date"))
    latest = enriched.iloc[-1]
    return {
        "rsi": float(latest["rsi14"]) if pd.notna(latest["rsi14"]) else 50.0,
        "ret_3d": float(latest["ret_3d_pct"]) if pd.notna(latest["ret_3d_pct"]) else 0.0,
        "bullish": bool(latest["is_bullish"]),
        "close": float(latest["close"]),
    }


def _should_enter_defensive_rebound(signal: dict[str, float | bool]) -> bool:
    # Bear regime entry threshold is intentionally strict to reduce drawdown risk.
    return bool(float(signal["ret_3d"]) <= -5.0 and float(signal["rsi"]) < 30.0 and signal["bullish"])


def _build_exit_signals(symbol: str, signal: dict[str, float | bool], position: pd.Series, cfg: BearStrategyConfig) -> list[StrategySignal]:
    entry = float(position["average_price"])
    qty = int(position["quantity"])
    hold_days = int(position.get("hold_days", 0))
    if entry <= 0 or qty <= 0:
        return []
    pnl_pct = ((float(signal["close"]) / entry) - 1.0) * 100.0
    if pnl_pct <= -abs(cfg.stop_loss_pct):
        return [StrategySignal(symbol, "sell", qty, None, None, "Bear stop-loss priority exit", "bear_strategy")]
    if pnl_pct >= cfg.second_take_profit_pct:
        return [StrategySignal(symbol, "sell", qty, None, None, "Bear second TP full exit", "bear_strategy")]
    if pnl_pct >= cfg.first_take_profit_pct:
        return [StrategySignal(symbol, "sell", max(int(qty * 0.5), 1), None, None, "Bear first TP partial exit", "bear_strategy")]
    if hold_days >= cfg.time_exit_days and pnl_pct <= 0.5:
        return [StrategySignal(symbol, "sell", qty, None, None, "Bear time exit", "bear_strategy")]
    return []


def _get_position_row(portfolio_df: pd.DataFrame, symbol: str) -> pd.Series | None:
    if portfolio_df.empty:
        return None
    matched = portfolio_df[portfolio_df["symbol"] == symbol]
    if matched.empty:
        return None
    return matched.iloc[-1]
