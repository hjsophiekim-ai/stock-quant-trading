from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.orders.models import OrderRequest
from app.strategy.base_strategy import BaseStrategy, StrategyContext, StrategySignal
from app.strategy.bear_strategy import BearStrategy, BearStrategyConfig
from app.strategy.bull_strategy import BullStrategy
from app.strategy.filters import filter_quality_swing_candidates
from app.strategy.indicators import add_basic_indicators
from app.strategy.market_regime import (
    MarketRegimeConfig,
    MarketRegimeInputs,
    classify_market_regime,
)
from app.strategy.ranking import RankedCandidate, rank_candidates
from app.strategy.sideways_strategy import SidewaysStrategy


@dataclass(frozen=True)
class SwingStrategyConfig:
    order_quantity: int = 10
    first_buy_drawdown_pct: float = -3.0
    second_buy_drawdown_pct: float = -5.0
    stop_loss_pct: float = 4.0
    first_take_profit_pct: float = 6.0
    second_take_profit_pct: float = 10.0
    time_exit_days: int = 7
    ranking_top_n: int = 3


@dataclass
class SwingStrategy(BaseStrategy):
    config: SwingStrategyConfig = SwingStrategyConfig()
    regime_config: MarketRegimeConfig = MarketRegimeConfig()
    bull_strategy: BullStrategy = field(default_factory=BullStrategy)
    bear_strategy: BearStrategy = field(default_factory=BearStrategy)
    sideways_strategy: SidewaysStrategy = field(default_factory=SidewaysStrategy)
    last_ranking: list[RankedCandidate] = field(default_factory=list)

    def generate_signals(self, context: StrategyContext) -> list[StrategySignal]:
        regime = classify_market_regime(
            MarketRegimeInputs(
                kospi=context.kospi_index,
                sp500=context.sp500_index,
                volatility=context.volatility_index,
            ),
            self.regime_config,
        )
        candidates = filter_quality_swing_candidates(context.prices)
        ranked = rank_candidates(
            prices_df=context.prices,
            candidate_symbols=candidates,
            regime=regime.regime,
            top_n=self.config.ranking_top_n,
        )
        self.last_ranking = ranked
        top_symbols = {r.symbol for r in ranked}
        reduced_context = _filter_context_by_candidates(context, top_symbols)

        if regime.regime == "bullish_trend":
            return self.bull_strategy.generate_signals(reduced_context)
        if regime.regime == "bearish_trend":
            return self.bear_strategy.generate_signals(reduced_context)
        if regime.regime == "sideways":
            return self.sideways_strategy.generate_signals(reduced_context)

        # high_volatility_risk: block new entries, only allow risk-reduction exits.
        defensive = BearStrategy(config=BearStrategyConfig(allow_new_entries=False, order_quantity=0, stop_loss_pct=2.0))
        return defensive.generate_signals(reduced_context)

    def generate_orders(self, context: StrategyContext) -> list[OrderRequest]:
        return super().generate_orders(context)


def build_symbol_signal(symbol_df: pd.DataFrame) -> dict[str, float | bool]:
    df = symbol_df.sort_values("date").copy()
    enriched = add_basic_indicators(df)
    latest = enriched.iloc[-1]

    signal: dict[str, float | bool] = {
        "ma20_gt_ma60": bool(latest["ma20"] > latest["ma60"]) if pd.notna(latest["ma20"]) and pd.notna(latest["ma60"]) else False,
        "drop_3d_in_range": bool(-6.0 <= float(latest["ret_3d_pct"]) <= -3.0) if pd.notna(latest["ret_3d_pct"]) else False,
        "rsi_lt_40": bool(float(latest["rsi14"]) < 40.0) if pd.notna(latest["rsi14"]) else False,
        "bullish_reversal": bool(latest["is_bullish"]),
        "close": float(latest["close"]),
    }
    return signal


def should_enter_long(signal: dict[str, float | bool]) -> bool:
    return bool(
        signal["ma20_gt_ma60"]
        and signal["drop_3d_in_range"]
        and signal["rsi_lt_40"]
        and signal["bullish_reversal"]
    )


def _build_split_buy_orders(symbol: str, config: SwingStrategyConfig) -> list[OrderRequest]:
    first_qty = max(int(config.order_quantity * 0.5), 1)
    second_qty = max(config.order_quantity - first_qty, 1)
    return [
        OrderRequest(symbol=symbol, side="buy", quantity=first_qty, price=None, stop_loss_pct=config.stop_loss_pct),
        OrderRequest(symbol=symbol, side="buy", quantity=second_qty, price=None, stop_loss_pct=config.stop_loss_pct),
    ]


def _build_exit_orders(
    symbol: str,
    signal: dict[str, float | bool],
    position_row: pd.Series,
    config: SwingStrategyConfig,
) -> list[OrderRequest]:
    entry_price = float(position_row["average_price"])
    qty = int(position_row["quantity"])
    hold_days = int(position_row.get("hold_days", 0))
    if qty <= 0 or entry_price <= 0:
        return []

    close_price = float(signal["close"])
    pnl_pct = ((close_price / entry_price) - 1.0) * 100.0

    # Absolute priority: stop loss
    if pnl_pct <= -abs(config.stop_loss_pct):
        return [OrderRequest(symbol=symbol, side="sell", quantity=qty, price=None)]

    if pnl_pct >= config.second_take_profit_pct:
        return [OrderRequest(symbol=symbol, side="sell", quantity=qty, price=None)]

    if pnl_pct >= config.first_take_profit_pct:
        sell_qty = max(int(qty * 0.5), 1)
        return [OrderRequest(symbol=symbol, side="sell", quantity=sell_qty, price=None)]

    if hold_days >= config.time_exit_days and pnl_pct <= 0.0:
        return [OrderRequest(symbol=symbol, side="sell", quantity=qty, price=None)]

    return []


def _get_position_row(portfolio_df: pd.DataFrame, symbol: str) -> pd.Series | None:
    if portfolio_df.empty:
        return None
    matched = portfolio_df[portfolio_df["symbol"] == symbol]
    if matched.empty:
        return None
    return matched.iloc[-1]


def _filter_context_by_candidates(context: StrategyContext, candidates: set[str]) -> StrategyContext:
    if not candidates:
        return StrategyContext(
            prices=context.prices.iloc[0:0].copy(),
            kospi_index=context.kospi_index,
            sp500_index=context.sp500_index,
            portfolio=context.portfolio,
            volatility_index=context.volatility_index,
        )
    prices = context.prices[context.prices["symbol"].isin(candidates)].copy()
    portfolio = context.portfolio[context.portfolio["symbol"].isin(candidates)].copy() if not context.portfolio.empty else context.portfolio
    return StrategyContext(
        prices=prices,
        kospi_index=context.kospi_index,
        sp500_index=context.sp500_index,
        portfolio=portfolio,
        volatility_index=context.volatility_index,
    )
