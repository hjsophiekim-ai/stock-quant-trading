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


def _swing_v2_liquidity_and_weak_bounce(
    symbol_df: pd.DataFrame, signal: dict[str, Any]
) -> tuple[bool, str, dict[str, Any]]:
    """거래대금 대비 최소 유동성 + 약한 반등(추격) 차단."""
    sd = symbol_df.sort_values("date")
    if "volume" not in sd.columns or sd.empty:
        return False, "volume_column_missing", {}
    vt = sd["volume"].astype(float)
    vma = float(vt.tail(20).mean()) if len(vt) >= 8 else float(vt.mean())
    last_v = float(vt.iloc[-1])
    vol_ratio = (last_v / vma) if vma > 0 else 1.0
    liquidity_ok = vma <= 0 or last_v >= vma * 0.82
    ret3 = float(signal.get("ret_3d_pct") or 0)
    rsi = float(signal.get("rsi14") or 50)
    weak = (not bool(signal.get("bullish_reversal"))) and (-0.4 < ret3 < 0.55) and rsi >= 51.5
    extra: dict[str, Any] = {
        "volume_vs_ma20_ratio": round(vol_ratio, 4),
        "liquidity_floor_ok": liquidity_ok,
        "weak_bounce_risk": weak,
    }
    if not liquidity_ok:
        return False, "유동성 부족(당일 거래량 < 20일평균×0.82)", extra
    if weak:
        return False, "약한 반등·추격 위험(반등 강도 미흡)", extra
    # 거래량 급증: 유동성은 통과했으나 거래대금이 평소 대비 너무 낮으면 가짜 반등·칼날 리스크
    vol_surge_min = 1.10
    if vol_ratio < vol_surge_min:
        extra["volume_surge_ok"] = False
        return False, f"거래량 급증 미달(당일/20일 ≥ {vol_surge_min:.2f})", extra
    extra["volume_surge_ok"] = True
    return True, "", extra


def _dynamic_stop_pct_relaxed_v2(config: SwingStrategyConfig, atr_pct: float) -> float:
    """고정 %와 ATR%를 블렌딩해 휩소에 의한 불필요 손절을 줄임(상한·하한 캡)."""
    sl = abs(float(config.stop_loss_pct))
    if atr_pct <= 0:
        return sl
    blended = max(sl * 0.90, min(sl * 1.32, float(atr_pct) * 1.58))
    return float(min(max(blended, sl * 0.78), sl * 1.42))


def _build_exit_signals_relaxed_v2(
    symbol: str,
    signal: dict[str, Any],
    position_row: pd.Series,
    config: SwingStrategyConfig,
) -> list[StrategySignal]:
    entry_price = float(position_row["average_price"])
    qty = int(position_row["quantity"])
    hold_days = int(position_row.get("hold_days", 0))
    if qty <= 0 or entry_price <= 0:
        return []

    close_price = float(signal["close"])
    pnl_pct = ((close_price / entry_price) - 1.0) * 100.0
    atr_pct = float(signal.get("atr_pct") or 0.0)
    ma20 = float(signal.get("ma20") or 0.0)
    sl_eff = _dynamic_stop_pct_relaxed_v2(config, atr_pct)

    if pnl_pct <= -abs(sl_eff):
        return [
            StrategySignal(
                symbol=symbol,
                side="sell",
                quantity=qty,
                price=None,
                stop_loss_pct=None,
                reason="swing_relaxed_v2_stop_atr",
                strategy_name="swing_relaxed_v2",
            )
        ]

    if pnl_pct >= float(config.second_take_profit_pct):
        return [
            StrategySignal(
                symbol=symbol,
                side="sell",
                quantity=qty,
                price=None,
                stop_loss_pct=None,
                reason="swing_relaxed_v2_tp2",
                strategy_name="swing_relaxed_v2",
            )
        ]

    if pnl_pct >= float(config.first_take_profit_pct):
        sell_qty = max(int(qty * 0.5), 1)
        return [
            StrategySignal(
                symbol=symbol,
                side="sell",
                quantity=sell_qty,
                price=None,
                stop_loss_pct=None,
                reason="swing_relaxed_v2_tp1_partial",
                strategy_name="swing_relaxed_v2",
            )
        ]

    fp1 = float(config.first_take_profit_pct)
    trail_floor = max(2.0, fp1 * 0.38)
    if pnl_pct >= trail_floor and ma20 > 0:
        buf = max(0.005, 0.38 * (atr_pct / 100.0)) if atr_pct > 0 else 0.008
        if close_price < ma20 * (1.0 - buf):
            return [
                StrategySignal(
                    symbol=symbol,
                    side="sell",
                    quantity=qty,
                    price=None,
                    stop_loss_pct=None,
                    reason="swing_relaxed_v2_trailing_ma_atr",
                    strategy_name="swing_relaxed_v2",
                )
            ]

    if hold_days >= config.time_exit_days and pnl_pct <= 0.0:
        return [
            StrategySignal(
                symbol=symbol,
                side="sell",
                quantity=qty,
                price=None,
                stop_loss_pct=None,
                reason="swing_relaxed_v2_time_exit",
                strategy_name="swing_relaxed_v2",
            )
        ]

    return []


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
                gate_ok, _, _ = _swing_v2_liquidity_and_weak_bounce(symbol_df, bs)
                if not gate_ok:
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
                signals.extend(_build_exit_signals_relaxed_v2(symbol, bs, pos, self.config))

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
            gate_ok, gate_reason, gate_ex = _swing_v2_liquidity_and_weak_bounce(sdf, bs)
            blocked: str | None = None
            if not entered:
                if pos is not None:
                    blocked = "보유 중 — 신규 매수 대신 청산/홀드 평가"
                elif regime_str == "high_volatility_risk":
                    blocked = "고변동 리스크 국면으로 신규 진입 차단"
                elif not gate_ok:
                    blocked = gate_reason
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
                    "v2_score_breakdown": {**detail, **gate_ex},
                }
            )
        self.last_diagnostics = rows
