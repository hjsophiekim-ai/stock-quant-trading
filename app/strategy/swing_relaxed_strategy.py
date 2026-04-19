"""
Paper 검증용 완화 스윙(swing_v1 은 수정하지 않음).

- 후보: `filter_relaxed_swing_candidates`
- 진입: MA/3일낙폭/RSI/양봉 4조건 중 3개 이상(낙폭·RSI 구간 완화)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.strategy.base_strategy import StrategyContext, StrategySignal
from app.strategy.filters import filter_relaxed_swing_candidates
from app.strategy.market_regime import MarketRegimeInputs, classify_market_regime
from app.strategy.ranking import build_ranking_report_rows, rank_candidates
from app.strategy.swing_strategy import (
    SwingStrategy,
    SwingStrategyConfig,
    _build_exit_orders,
    _get_position_row,
    build_symbol_signal,
    orders_to_strategy_signals,
)


def should_enter_long_relaxed(signal: dict[str, Any]) -> bool:
    ret3 = float(signal.get("ret_3d_pct") or 0.0)
    drop_ok = -8.0 <= ret3 <= -1.0
    rsi = float(signal.get("rsi14") or 99.0)
    rsi_ok = rsi < 48.0
    parts = [
        bool(signal.get("ma20_gt_ma60")),
        drop_ok,
        rsi_ok,
        bool(signal.get("bullish_reversal")),
    ]
    return sum(1 for p in parts if p) >= 3


@dataclass
class SwingRelaxedStrategy(SwingStrategy):
    """swing_v1 과 별도 클래스 — Paper 에서 주문 발생 빈도를 높이기 위한 테스트용."""

    config: SwingStrategyConfig = SwingStrategyConfig(
        order_quantity=5,
        ranking_top_n=5,
        first_buy_drawdown_pct=-4.0,
        second_buy_drawdown_pct=-6.0,
    )

    def paper_candidate_symbols(self, prices: pd.DataFrame) -> list[str]:
        return filter_relaxed_swing_candidates(prices)

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
        top_symbols = {r.symbol for r in ranked} if ranked else set(candidates)
        if not top_symbols and not context.prices.empty:
            top_symbols = set(context.prices["symbol"].unique().tolist()[:8])

        signals: list[StrategySignal] = []
        for symbol, symbol_df in context.prices.groupby("symbol", sort=False):
            if symbol not in top_symbols:
                continue
            bs = build_symbol_signal(symbol_df)
            pos = _get_position_row(context.portfolio, symbol)
            if pos is None:
                if regime.regime == "high_volatility_risk":
                    continue
                if should_enter_long_relaxed(bs):
                    q = max(1, int(self.config.order_quantity))
                    signals.append(
                        StrategySignal(
                            symbol=symbol,
                            side="buy",
                            quantity=q,
                            price=None,
                            stop_loss_pct=self.config.stop_loss_pct,
                            reason="swing_relaxed_v1 test entry",
                            strategy_name="swing_relaxed_v1",
                        )
                    )
            else:
                signals.extend(
                    orders_to_strategy_signals(
                        _build_exit_orders(symbol, bs, pos, self.config),
                        strategy_name="swing_relaxed_v1",
                        reason="swing_relaxed_v1_exit",
                    )
                )

        self._build_last_diagnostics_relaxed(context, regime.regime, signals)
        return signals

    def _build_last_diagnostics_relaxed(
        self,
        context: StrategyContext,
        regime_str: str,
        signals: list[StrategySignal],
    ) -> None:
        buy_syms = {s.symbol for s in signals if s.side == "buy"}
        sym_list = [r.symbol for r in self.last_ranking]
        if not sym_list:
            cand = self.paper_candidate_symbols(context.prices)
            sym_list = sorted(list(cand))[: max(8, self.config.ranking_top_n)]

        rows: list[dict[str, Any]] = []
        for sym in sym_list:
            sdf = context.prices[context.prices["symbol"] == sym]
            if sdf.empty:
                continue
            bs = build_symbol_signal(sdf)
            pos_row = _get_position_row(context.portfolio, sym)
            if pos_row is not None:
                entered = sym in buy_syms
                rows.append(
                    {
                        "symbol": sym,
                        "ma20_gt_ma60": bool(bs.get("ma20_gt_ma60")),
                        "drop_3d_in_range": bool(bs.get("drop_3d_in_range")),
                        "rsi_lt_40": bool(bs.get("rsi_lt_40")),
                        "bullish_reversal": bool(bs.get("bullish_reversal")),
                        "entered": entered,
                        "blocked_reason": None
                        if entered
                        else "보유 중 — 이번 틱은 청산·홀드만 평가(신규 매수 없음)",
                    }
                )
                continue

            entered = sym in buy_syms
            blocked: str | None = None
            if not entered:
                if regime_str == "high_volatility_risk":
                    blocked = "고변동 리스크 국면으로 신규 진입 차단"
                elif not should_enter_long_relaxed(bs):
                    miss: list[str] = []
                    if not bool(bs.get("ma20_gt_ma60")):
                        miss.append("MA20≤MA60")
                    ret3 = float(bs.get("ret_3d_pct") or 0.0)
                    if not (-8.0 <= ret3 <= -1.0):
                        miss.append("3일수익률 -8~-1% 밖")
                    if float(bs.get("rsi14") or 99.0) >= 48.0:
                        miss.append("RSI≥48")
                    if not bool(bs.get("bullish_reversal")):
                        miss.append("양봉 아님")
                    hits = sum(
                        [
                            bool(bs.get("ma20_gt_ma60")),
                            -8.0 <= ret3 <= -1.0,
                            float(bs.get("rsi14") or 99.0) < 48.0,
                            bool(bs.get("bullish_reversal")),
                        ]
                    )
                    blocked = "완화 스윙(4중3): " + ", ".join(miss) + f" (충족 {hits}/4)"
                else:
                    blocked = "완화 조건 충족 — 매수 신호 없음(다음 틱 재확인)"
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
