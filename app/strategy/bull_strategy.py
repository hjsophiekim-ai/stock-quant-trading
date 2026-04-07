from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from app.strategy.base_strategy import BaseStrategy, StrategyContext, StrategySignal
from app.strategy.indicators import add_basic_indicators


@dataclass(frozen=True)
class BullStrategyConfig:
    order_quantity: int = 12
    stop_loss_pct: float = 4.0
    first_take_profit_pct: float = 6.0
    second_take_profit_pct: float = 10.0
    time_exit_days: int = 10
    trailing_mode: Literal["atr", "n_day_low"] = "atr"
    trailing_atr_multiplier: float = 2.5
    trailing_n_day_low_window: int = 5


@dataclass
class BullStrategy(BaseStrategy):
    config: BullStrategyConfig = BullStrategyConfig()

    def generate_signals(self, context: StrategyContext) -> list[StrategySignal]:
        signals: list[StrategySignal] = []
        for symbol, symbol_df in context.prices.groupby("symbol", sort=False):
            signal = _build_symbol_signal(symbol_df, self.config)
            position = _get_position_row(context.portfolio, symbol)
            if position is None:
                if _should_enter_bull(signal):
                    q1 = max(int(self.config.order_quantity * 0.6), 1)
                    q2 = max(self.config.order_quantity - q1, 1)
                    signals.append(
                        StrategySignal(
                            symbol=symbol,
                            side="buy",
                            quantity=q1,
                            price=None,
                            stop_loss_pct=self.config.stop_loss_pct,
                            reason="Bull trend follow first entry",
                            strategy_name="bull_strategy",
                        )
                    )
                    signals.append(
                        StrategySignal(
                            symbol=symbol,
                            side="buy",
                            quantity=q2,
                            price=None,
                            stop_loss_pct=self.config.stop_loss_pct,
                            reason="Bull pullback add entry",
                            strategy_name="bull_strategy",
                        )
                    )
            else:
                signals.extend(_build_exit_signals(symbol, signal, position, self.config, "bull_strategy"))
        return signals


def _build_symbol_signal(symbol_df: pd.DataFrame, config: BullStrategyConfig) -> dict[str, float | bool]:
    enriched = add_basic_indicators(symbol_df.sort_values("date"))
    enriched["atr14"] = _atr(enriched, period=14)
    enriched["low_n"] = enriched["low"].rolling(config.trailing_n_day_low_window, min_periods=1).min()
    latest = enriched.iloc[-1]
    return {
        "ma20_gt_ma60": bool(pd.notna(latest["ma20"]) and pd.notna(latest["ma60"]) and latest["ma20"] > latest["ma60"]),
        "ma20": float(latest["ma20"]) if pd.notna(latest["ma20"]) else float(latest["close"]),
        "rsi": float(latest["rsi14"]) if pd.notna(latest["rsi14"]) else 50.0,
        "ret_3d": float(latest["ret_3d_pct"]) if pd.notna(latest["ret_3d_pct"]) else 0.0,
        "bullish": bool(latest["is_bullish"]),
        "atr14": float(latest["atr14"]) if pd.notna(latest["atr14"]) else 0.0,
        "low_n": float(latest["low_n"]) if pd.notna(latest["low_n"]) else float(latest["low"]),
        "close": float(latest["close"]),
    }


def _should_enter_bull(signal: dict[str, float | bool]) -> bool:
    return bool(
        signal["ma20_gt_ma60"]
        and -6.0 <= float(signal["ret_3d"]) <= -1.0
        and float(signal["rsi"]) < 45.0
        and signal["bullish"]
    )


def _build_exit_signals(
    symbol: str,
    signal: dict[str, float | bool],
    position: pd.Series,
    config: BullStrategyConfig,
    strategy_name: str,
) -> list[StrategySignal]:
    entry = float(position["average_price"])
    qty = int(position["quantity"])
    hold_days = int(position.get("hold_days", 0))
    first_tp_done = bool(position.get("first_take_profit_done", False))
    highest_price_since_entry = float(position.get("highest_price_since_entry", entry))
    if entry <= 0 or qty <= 0:
        return []
    pnl_pct = ((float(signal["close"]) / entry) - 1.0) * 100.0
    highest_price_since_entry = max(highest_price_since_entry, float(signal["close"]))
    if pnl_pct <= -abs(config.stop_loss_pct):
        return [StrategySignal(symbol, "sell", qty, None, None, "Stop-loss priority exit", strategy_name)]
    if not first_tp_done and pnl_pct >= config.first_take_profit_pct:
        return [StrategySignal(symbol, "sell", max(int(qty * 0.5), 1), None, None, "First TP partial exit", strategy_name)]
    if first_tp_done:
        if _trailing_stop_triggered(
            close=float(signal["close"]),
            atr=float(signal["atr14"]),
            low_n=float(signal["low_n"]),
            highest_price=highest_price_since_entry,
            mode=config.trailing_mode,
            atr_multiplier=config.trailing_atr_multiplier,
        ):
            return [StrategySignal(symbol, "sell", qty, None, None, "Trailing exit on remaining position", strategy_name)]
    if pnl_pct >= config.second_take_profit_pct and float(signal["close"]) < float(signal["ma20"]):
        return [StrategySignal(symbol, "sell", qty, None, None, "Second TP + trend weakness full exit", strategy_name)]
    if hold_days >= config.time_exit_days and pnl_pct <= 0.0:
        return [StrategySignal(symbol, "sell", qty, None, None, "Time exit", strategy_name)]
    return []


def _get_position_row(portfolio_df: pd.DataFrame, symbol: str) -> pd.Series | None:
    if portfolio_df.empty:
        return None
    matched = portfolio_df[portfolio_df["symbol"] == symbol]
    if matched.empty:
        return None
    return matched.iloc[-1]


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def _trailing_stop_triggered(
    *,
    close: float,
    atr: float,
    low_n: float,
    highest_price: float,
    mode: Literal["atr", "n_day_low"],
    atr_multiplier: float,
) -> bool:
    if mode == "n_day_low":
        return close <= low_n
    if atr <= 0:
        return False
    trailing_stop = highest_price - (atr * atr_multiplier)
    return close <= trailing_stop
