from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
from app.strategy.ranking import RankedCandidate, RankingReportRow, build_ranking_report_rows, rank_candidates
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
    last_ranking_report: list[RankingReportRow] = field(default_factory=list)
    last_regime_label: str | None = field(default=None, repr=False)
    last_diagnostics: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def paper_candidate_symbols(self, prices: pd.DataFrame) -> list[str]:
        """Paper/스케줄러 공통: 품질 필터 후보. 서브클래스에서 완화판 오버라이드."""
        return filter_quality_swing_candidates(prices)

    def generate_signals(self, context: StrategyContext) -> list[StrategySignal]:
        regime = classify_market_regime(
            MarketRegimeInputs(
                kospi=context.kospi_index,
                sp500=context.sp500_index,
                volatility=context.volatility_index,
            ),
            self.regime_config,
        )
        self.last_regime_label = regime.regime
        candidates = self.paper_candidate_symbols(context.prices)
        ranked = rank_candidates(
            prices_df=context.prices,
            candidate_symbols=candidates,
            regime=regime.regime,
            top_n=self.config.ranking_top_n,
        )
        self.last_ranking = ranked
        self.last_ranking_report = build_ranking_report_rows(ranked)
        top_symbols = {r.symbol for r in ranked}
        reduced_context = _filter_context_by_candidates(context, top_symbols)

        if regime.regime == "bullish_trend":
            signals = self.bull_strategy.generate_signals(reduced_context)
        elif regime.regime == "bearish_trend":
            signals = self.bear_strategy.generate_signals(reduced_context)
        elif regime.regime == "sideways":
            signals = self.sideways_strategy.generate_signals(reduced_context)
        else:
            # high_volatility_risk: block new entries, only allow risk-reduction exits.
            defensive = BearStrategy(config=BearStrategyConfig(allow_new_entries=False, order_quantity=0, stop_loss_pct=2.0))
            signals = defensive.generate_signals(reduced_context)

        self._build_last_diagnostics(context, regime.regime, signals)
        return signals

    def _build_last_diagnostics(
        self,
        context: StrategyContext,
        regime_str: str,
        signals: list[StrategySignal],
    ) -> None:
        """랭킹 상위·후보 종목별 스윙 지표 스냅샷(진입 여부·차단 사유)."""
        buy_syms = {s.symbol for s in signals if s.side == "buy"}
        sym_list = [r.symbol for r in self.last_ranking]
        if not sym_list:
            cand = self.paper_candidate_symbols(context.prices)
            sym_list = sorted(list(cand))[: max(5, self.config.ranking_top_n)]

        rows: list[dict[str, Any]] = []
        for sym in sym_list:
            sdf = context.prices[context.prices["symbol"] == sym]
            if sdf.empty:
                continue
            bs = build_symbol_signal(sdf)
            entered = sym in buy_syms
            blocked: str | None = None
            if not entered:
                if regime_str == "high_volatility_risk":
                    blocked = "고변동 리스크 국면으로 신규 진입 차단"
                elif not should_enter_long(bs):
                    miss: list[str] = []
                    if not bool(bs.get("ma20_gt_ma60")):
                        miss.append("MA20≤MA60")
                    if not bool(bs.get("drop_3d_in_range")):
                        miss.append("3일수익률 -6~-3% 밖")
                    if not bool(bs.get("rsi_lt_40")):
                        miss.append("RSI≥40")
                    if not bool(bs.get("bullish_reversal")):
                        miss.append("역추세 반전 캔들 아님")
                    blocked = "스윙 진입 조건 미충족: " + ", ".join(miss) if miss else "스윙 진입 조건 미충족"
                else:
                    blocked = "국면·전략 분기에서 매수 신호 없음"
            rows.append(
                {
                    "symbol": sym,
                    "ma20_gt_ma60": bool(bs.get("ma20_gt_ma60")),
                    "drop_3d_in_range": bool(bs.get("drop_3d_in_range")),
                    "rsi_lt_40": bool(bs.get("rsi_lt_40")),
                    "bullish_reversal": bool(bs.get("bullish_reversal")),
                    "entered": entered,
                    "blocked_reason": blocked,
                }
            )
        self.last_diagnostics = rows

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
        "ma20": float(latest["ma20"]) if pd.notna(latest["ma20"]) else 0.0,
        "ma60": float(latest["ma60"]) if pd.notna(latest["ma60"]) else 0.0,
        "close": float(latest["close"]),
        "ret_3d_pct": float(latest["ret_3d_pct"]) if pd.notna(latest["ret_3d_pct"]) else 0.0,
        "rsi14": float(latest["rsi14"]) if pd.notna(latest["rsi14"]) else 50.0,
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
