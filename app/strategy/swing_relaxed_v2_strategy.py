"""
Paper 검증용 완화 스윙 v2.

- 실거래용이 아닌 Paper 탐색 전략
- high_volatility_risk 국면에서는 신규 진입 차단 유지
- 4조건 중 2개 이상이면 진입 가능(단, 무제한 진입 방지)
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
)


def _v2_conditions(signal: dict[str, Any]) -> tuple[bool, bool, bool, bool, dict[str, Any]]:
    ma20 = float(signal.get("ma20") or 0.0)
    ma60 = float(signal.get("ma60") or 0.0)
    trend_ok = ma20 >= ma60
    near_ma_ok = False
    if ma60 > 0:
        near_ma_ok = abs(ma20 - ma60) / ma60 <= 0.01
    trend_cond = trend_ok or near_ma_ok

    ret3 = float(signal.get("ret_3d_pct") or 0.0)
    drop_cond = -10.0 <= ret3 <= 0.0

    rsi = float(signal.get("rsi14") or 99.0)
    rsi_cond = rsi < 55.0

    bullish = bool(signal.get("bullish_reversal"))
    rebound_hint = ret3 > -0.8 and (ma20 > 0) and float(signal.get("close") or 0.0) >= ma20 * 0.99
    rebound_cond = bullish or rebound_hint

    detail = {
        "trend_ok": trend_ok,
        "near_ma_ok": near_ma_ok,
        "ret3d_pct": ret3,
        "rsi14": rsi,
        "bullish_reversal": bullish,
        "rebound_hint": rebound_hint,
    }
    return trend_cond, drop_cond, rsi_cond, rebound_cond, detail


def should_enter_long_relaxed_v2(signal: dict[str, Any]) -> tuple[bool, int, dict[str, Any]]:
    trend_cond, drop_cond, rsi_cond, rebound_cond, detail = _v2_conditions(signal)
    hits = sum([trend_cond, drop_cond, rsi_cond, rebound_cond])
    detail.update(
        {
            "trend_cond": trend_cond,
            "drop_cond": drop_cond,
            "rsi_cond": rsi_cond,
            "rebound_cond": rebound_cond,
            "hit_count": hits,
        }
    )
    return hits >= 2, hits, detail


@dataclass
class SwingRelaxedV2Strategy(SwingStrategy):
    config: SwingStrategyConfig = SwingStrategyConfig(
        order_quantity=4,
        ranking_top_n=6,
        first_buy_drawdown_pct=-4.0,
        second_buy_drawdown_pct=-7.0,
    )

    def paper_candidate_symbols(self, prices: pd.DataFrame) -> list[str]:
        # v2 는 후보 게이트도 완화하되, 너무 넓어지지 않게 상위 유동성 필터는 유지.
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
            top_symbols = set(context.prices["symbol"].unique().tolist()[:10])

        signals: list[StrategySignal] = []
        for symbol, symbol_df in context.prices.groupby("symbol", sort=False):
            if symbol not in top_symbols:
                continue
            bs = build_symbol_signal(symbol_df)
            pos = _get_position_row(context.portfolio, symbol)
            if pos is None:
                if regime.regime == "high_volatility_risk":
                    continue
                ok, _, _ = should_enter_long_relaxed_v2(bs)
                if ok:
                    signals.append(
                        StrategySignal(
                            symbol=symbol,
                            side="buy",
                            quantity=max(1, int(self.config.order_quantity)),
                            price=None,
                            stop_loss_pct=self.config.stop_loss_pct,
                            reason="swing_relaxed_v2 test entry",
                            strategy_name="swing_relaxed_v2",
                        )
                    )
            else:
                signals.extend(_build_exit_orders(symbol, bs, pos, self.config))

        self._build_last_diagnostics_v2(context, regime.regime, signals)
        return signals

    def _build_last_diagnostics_v2(
        self,
        context: StrategyContext,
        regime_str: str,
        signals: list[StrategySignal],
    ) -> None:
        buy_syms = {s.symbol for s in signals if s.side == "buy"}
        sym_list = [r.symbol for r in self.last_ranking]
        if not sym_list:
            sym_list = sorted(self.paper_candidate_symbols(context.prices))[: max(10, self.config.ranking_top_n)]

        rows: list[dict[str, Any]] = []
        for sym in sym_list:
            sdf = context.prices[context.prices["symbol"] == sym]
            if sdf.empty:
                continue
            bs = build_symbol_signal(sdf)
            pos = _get_position_row(context.portfolio, sym)
            entered = sym in buy_syms
            ok, hits, detail = should_enter_long_relaxed_v2(bs)
            blocked: str | None = None
            if not entered:
                if pos is not None:
                    blocked = "보유 중 — 신규 매수 대신 청산/홀드 평가"
                elif regime_str == "high_volatility_risk":
                    blocked = "고변동 리스크 국면으로 신규 진입 차단"
                elif not ok:
                    reasons: list[str] = []
                    if not detail["trend_cond"]:
                        reasons.append("MA20>=MA60/근접 조건 미충족")
                    if not detail["drop_cond"]:
                        reasons.append("3일수익률 -10~0% 범위 아님")
                    if not detail["rsi_cond"]:
                        reasons.append("RSI>=55")
                    if not detail["rebound_cond"]:
                        reasons.append("반등 신호 없음")
                    blocked = "완화 v2(4중2): " + ", ".join(reasons) + f" (충족 {hits}/4)"
                else:
                    blocked = "완화 v2 조건 충족 — 이번 틱 매수 신호 없음"

            rows.append(
                {
                    "symbol": sym,
                    "ma20_gt_ma60": bool(bs.get("ma20_gt_ma60")),
                    "drop_3d_in_range": bool(bs.get("drop_3d_in_range")),
                    "rsi_lt_40": bool(bs.get("rsi_lt_40")),
                    "bullish_reversal": bool(bs.get("bullish_reversal")),
                    "entered": entered,
                    "blocked_reason": blocked,
                    "v2_hit_count": hits,
                    "v2_detail": detail,
                }
            )
        self.last_diagnostics = rows
