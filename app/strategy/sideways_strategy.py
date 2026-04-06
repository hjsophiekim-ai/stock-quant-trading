from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.strategy.base_strategy import BaseStrategy, StrategyContext, StrategySignal
from app.strategy.indicators import add_basic_indicators


@dataclass(frozen=True)
class SidewaysStrategyConfig:
    order_quantity: int = 5
    stop_loss_pct: float = 3.0
    take_profit_pct: float = 4.0
    time_exit_days: int = 4
    max_new_entries_per_cycle: int = 1


@dataclass
class SidewaysStrategy(BaseStrategy):
    config: SidewaysStrategyConfig = SidewaysStrategyConfig()

    def generate_signals(self, context: StrategyContext) -> list[StrategySignal]:
        signals: list[StrategySignal] = []
        entries = 0
        for symbol, symbol_df in context.prices.groupby("symbol", sort=False):
            signal = _build_symbol_signal(symbol_df)
            position = _get_position_row(context.portfolio, symbol)
            if position is None:
                if entries < self.config.max_new_entries_per_cycle and _should_enter_mean_reversion(signal):
                    signals.append(
                        StrategySignal(
                            symbol=symbol,
                            side="buy",
                            quantity=self.config.order_quantity,
                            price=None,
                            stop_loss_pct=self.config.stop_loss_pct,
                            reason="Sideways limited mean-reversion entry",
                            strategy_name="sideways_strategy",
                        )
                    )
                    entries += 1
            else:
                signals.extend(_build_exit_signals(symbol, signal, position, self.config))
        return signals


def _build_symbol_signal(symbol_df: pd.DataFrame) -> dict[str, float | bool]:
    enriched = add_basic_indicators(symbol_df.sort_values("date"))
    latest = enriched.iloc[-1]
    return {
        "close_below_ma20": bool(pd.notna(latest["ma20"]) and latest["close"] < latest["ma20"]),
        "rsi": float(latest["rsi14"]) if pd.notna(latest["rsi14"]) else 50.0,
        "bullish": bool(latest["is_bullish"]),
        "close": float(latest["close"]),
    }


def _should_enter_mean_reversion(signal: dict[str, float | bool]) -> bool:
    return bool(signal["close_below_ma20"] and float(signal["rsi"]) < 38.0 and signal["bullish"])


def _build_exit_signals(symbol: str, signal: dict[str, float | bool], position: pd.Series, cfg: SidewaysStrategyConfig) -> list[StrategySignal]:
    entry = float(position["average_price"])
    qty = int(position["quantity"])
    hold_days = int(position.get("hold_days", 0))
    if entry <= 0 or qty <= 0:
        return []
    pnl_pct = ((float(signal["close"]) / entry) - 1.0) * 100.0
    if pnl_pct <= -abs(cfg.stop_loss_pct):
        return [StrategySignal(symbol, "sell", qty, None, None, "Sideways stop-loss priority exit", "sideways_strategy")]
    if pnl_pct >= cfg.take_profit_pct:
        return [StrategySignal(symbol, "sell", qty, None, None, "Sideways take-profit exit", "sideways_strategy")]
    if hold_days >= cfg.time_exit_days and pnl_pct <= 0.0:
        return [StrategySignal(symbol, "sell", qty, None, None, "Sideways time exit", "sideways_strategy")]
    return []


def _get_position_row(portfolio_df: pd.DataFrame, symbol: str) -> pd.Series | None:
    if portfolio_df.empty:
        return None
    matched = portfolio_df[portfolio_df["symbol"] == symbol]
    if matched.empty:
        return None
    return matched.iloc[-1]
