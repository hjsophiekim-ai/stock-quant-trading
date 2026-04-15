"""Paper 인트라데이 단타 v2 — 1분봉·완화형 모멘텀(점수 기반) + 리스크 우선."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.config import get_settings
from app.strategy.base_strategy import BaseStrategy, StrategyContext, StrategySignal
from app.strategy.intraday_common import (
    ema,
    get_krx_session_state_kst,
    intraday_liquidity_multipliers_for_state,
    krx_session_config_from_settings,
    last_bar_body_pct,
    quote_liquidity_from_payload,
    rsi_wilder,
    session_vwap,
    should_force_flatten_before_close_kst,
    volume_zscore_recent,
)
from app.strategy.intraday_paper_state import IntradayPaperState, parse_iso
from app.strategy.market_regime import MarketRegimeConfig, MarketRegimeInputs, classify_market_regime


@dataclass
class ScalpMomentumV2Strategy(BaseStrategy):
    """1분봉 VWAP reclaim·단기 EMA 정배열·거래량 스파이크. 동일 종목 재진입 쿨다운은 루프/상태에서 처리."""

    regime_config: MarketRegimeConfig = field(default_factory=MarketRegimeConfig)
    last_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    last_intraday_filter_breakdown: list[dict[str, Any]] = field(default_factory=list)
    last_intraday_signal_breakdown: dict[str, Any] = field(default_factory=dict)

    quote_by_symbol: dict[str, dict[str, Any]] = field(default_factory=dict)
    intraday_state: IntradayPaperState | None = None
    intraday_session_context: dict[str, Any] = field(default_factory=dict)
    risk_halt_new_entries: bool = False
    timeframe_label: str = "1m"

    _risk_tighten: float = 0.90

    def generate_signals(self, context: StrategyContext) -> list[StrategySignal]:
        cfg = get_settings()
        self.last_diagnostics = []
        self.last_intraday_filter_breakdown = []
        self.last_intraday_signal_breakdown = {"entries_evaluated": 0, "exits_evaluated": 0}
        signals: list[StrategySignal] = []
        st = self.intraday_state
        rt = float(self._risk_tighten)

        ctx_sess = getattr(self, "intraday_session_context", None) or {}
        sess_state = str(ctx_sess.get("krx_session_state") or get_krx_session_state_kst())
        self.last_intraday_signal_breakdown["session_state"] = sess_state
        if sess_state == "closed":
            self.last_intraday_signal_breakdown["session"] = "closed"
            return signals

        scfg = krx_session_config_from_settings(cfg)
        regime = classify_market_regime(
            MarketRegimeInputs(
                kospi=context.kospi_index,
                sp500=context.sp500_index,
                volatility=context.volatility_index,
            ),
            self.regime_config,
        )
        high_vol_block = regime.regime == "high_volatility_risk"
        flatten_close = should_force_flatten_before_close_kst(
            minutes_before_close=int(cfg.paper_intraday_flatten_before_close_minutes),
            session_config=scfg,
        )

        prices = context.prices
        portfolio = context.portfolio
        pos_symbols: set[str] = set()
        if not portfolio.empty and "symbol" in portfolio.columns:
            pos_symbols = set(str(s).strip() for s in portfolio["symbol"].unique())

        sl_pct = float(cfg.paper_intraday_stop_loss_pct) * rt
        tp_pct = float(cfg.paper_intraday_take_profit_pct) * rt
        trail_pct = float(cfg.paper_intraday_trailing_stop_pct) * rt
        hold_min = float(cfg.paper_intraday_max_hold_minutes) * 0.65

        for sym in pos_symbols:
            sub = prices[prices["symbol"] == sym].sort_values("date") if not prices.empty else pd.DataFrame()
            row = portfolio[portfolio["symbol"] == sym].iloc[0] if not portfolio.empty else None
            if row is None:
                continue
            qty = int(row.get("quantity") or 0)
            avg = float(row.get("average_price") or 0)
            if qty <= 0 or avg <= 0:
                continue
            last_px = float(sub["close"].iloc[-1]) if not sub.empty else avg
            exit_reason = None
            if flatten_close:
                exit_reason = "forced_flatten_before_close"
            elif not sub.empty:
                sl = avg * (1.0 - sl_pct / 100.0)
                tp = avg * (1.0 + tp_pct / 100.0)
                peak = float(st.peak_price.get(sym, last_px)) if st else last_px
                if last_px > peak:
                    peak = last_px
                    if st:
                        st.peak_price[sym] = peak
                trail_line = peak * (1.0 - trail_pct / 100.0) if trail_pct > 0 else 0.0
                entry_ts = parse_iso(st.entry_ts_iso.get(sym)) if st else None
                if last_px <= sl:
                    exit_reason = "stop_loss"
                elif last_px >= tp:
                    exit_reason = "take_profit"
                elif trail_pct > 0 and last_px < trail_line:
                    exit_reason = "trailing_stop"
                elif entry_ts is not None:
                    age_m = (datetime.now(timezone.utc) - entry_ts).total_seconds() / 60.0
                    if age_m >= hold_min:
                        exit_reason = "time_stop"

            if exit_reason:
                self.last_intraday_signal_breakdown["exits_evaluated"] = (
                    int(self.last_intraday_signal_breakdown.get("exits_evaluated") or 0) + 1
                )
                signals.append(
                    StrategySignal(
                        symbol=sym,
                        side="sell",
                        quantity=qty,
                        price=last_px,
                        stop_loss_pct=None,
                        reason=exit_reason,
                        strategy_name="scalp_momentum_v2",
                    )
                )

        if flatten_close:
            return signals

        if self.risk_halt_new_entries:
            self.last_intraday_signal_breakdown["blocked"] = "daily_loss_halt"
            return signals

        if st and int(cfg.paper_intraday_max_trades_per_day) > 0:
            if st.trade_count_today >= int(cfg.paper_intraday_max_trades_per_day):
                self.last_intraday_signal_breakdown["blocked"] = "max_trades_per_day"
                return signals

        open_n = len(pos_symbols)
        if open_n >= int(cfg.paper_intraday_max_open_positions):
            self.last_intraday_signal_breakdown["blocked"] = "max_open_positions"
            return signals

        if high_vol_block:
            self.last_intraday_signal_breakdown["blocked"] = "high_volatility_risk_no_entry"
            return signals

        max_new = max(0, int(cfg.paper_intraday_max_open_positions) - open_n)
        entries_added = 0

        m_vol, m_spread, m_chase = intraday_liquidity_multipliers_for_state(sess_state, cfg)

        if not prices.empty:
            for sym in prices["symbol"].unique():
                sym = str(sym).strip()
                if sym in pos_symbols:
                    continue
                if entries_added >= max_new:
                    break
                self.last_intraday_signal_breakdown["entries_evaluated"] = (
                    int(self.last_intraday_signal_breakdown.get("entries_evaluated") or 0) + 1
                )
                sub = prices[prices["symbol"] == sym].sort_values("date")
                diag: dict[str, Any] = {
                    "symbol": sym,
                    "entered": False,
                    "blocked_reason": "",
                    "ema_align": False,
                    "vwap_reclaim": False,
                    "mom_ok": False,
                    "vol_spike": False,
                    "micro_break": False,
                    "rsi_ok": False,
                    "total_score": 0,
                    "min_score_required": 3,
                }
                if len(sub) < 24:
                    diag["blocked_reason"] = "insufficient_bars"
                    self.last_diagnostics.append(diag)
                    continue

                qp = self.quote_by_symbol.get(sym) or {}
                liq = quote_liquidity_from_payload(qp) if qp else None
                if liq:
                    min_v = float(cfg.paper_intraday_min_quote_volume) * 0.8 * m_vol
                    min_tv = float(cfg.paper_intraday_min_trade_value_krw) * 0.8 * m_vol
                    max_sp = float(cfg.paper_intraday_max_spread_pct) * m_spread
                    if liq["acml_vol"] < min_v:
                        diag["blocked_reason"] = "liquidity_volume"
                        self.last_intraday_filter_breakdown.append({"symbol": sym, "rule": "min_volume"})
                        self.last_diagnostics.append(diag)
                        continue
                    if liq["acml_tr_pbmn"] < min_tv:
                        diag["blocked_reason"] = "liquidity_trade_value"
                        self.last_intraday_filter_breakdown.append({"symbol": sym, "rule": "min_trade_value"})
                        self.last_diagnostics.append(diag)
                        continue
                    if liq["spread_pct"] > max_sp:
                        diag["blocked_reason"] = "spread"
                        self.last_intraday_filter_breakdown.append({"symbol": sym, "rule": "max_spread"})
                        self.last_diagnostics.append(diag)
                        continue

                close = sub["close"].astype(float)
                ema3 = ema(close, 3)
                ema8 = ema(close, 8)
                ema21 = ema(close, 21)
                vwap = session_vwap(sub)
                rsi = rsi_wilder(close, 14)
                vol = sub["volume"].astype(float)
                vz = volume_zscore_recent(vol, 15)
                last_close = float(close.iloc[-1])
                prev_high = float(sub["high"].iloc[-2]) if len(sub) >= 2 else last_close
                mom_ok = last_close >= float(close.iloc[-5]) * 1.0002 if len(close) >= 5 else False
                ema_align = (
                    len(ema3) > 0
                    and len(ema8) > 0
                    and float(ema3.iloc[-1]) > float(ema8.iloc[-1]) > float(ema21.iloc[-1])
                )
                vwap_reclaim = len(vwap) and last_close > float(vwap.iloc[-1]) * 1.0
                micro_break = last_close > prev_high * 1.0001
                vol_spike = vz is not None and vz > 0.10
                rsi_ok = len(rsi) and float(rsi.iloc[-1]) < 76.0
                body_pct = last_bar_body_pct(sub) or 0.0
                if body_pct > float(cfg.paper_intraday_max_chase_candle_pct) * 1.2 * m_chase:
                    diag["blocked_reason"] = "chase_candle"
                    self.last_intraday_filter_breakdown.append({"symbol": sym, "rule": "chase_candle"})
                    self.last_diagnostics.append(diag)
                    continue

                score_flags = {
                    "ema_align": bool(ema_align),
                    "vwap_reclaim": bool(vwap_reclaim),
                    "mom_ok": bool(mom_ok),
                    "vol_spike": bool(vol_spike),
                    "micro_break": bool(micro_break),
                    "rsi_ok": bool(rsi_ok),
                }
                total_score = sum(1 for v in score_flags.values() if v)
                diag.update(score_flags)
                diag["total_score"] = int(total_score)
                diag["min_score_required"] = 3
                diag["body_pct"] = float(body_pct)

                if total_score < 3:
                    diag["blocked_reason"] = "signal_not_met"
                    self.last_diagnostics.append(diag)
                    continue

                last_px = last_close
                signals.append(
                    StrategySignal(
                        symbol=sym,
                        side="buy",
                        quantity=int(cfg.paper_intraday_order_quantity),
                        price=last_px,
                        stop_loss_pct=sl_pct,
                        reason="scalp_momentum_v2_entry",
                        strategy_name="scalp_momentum_v2",
                    )
                )
                diag["entered"] = True
                diag["blocked_reason"] = ""
                self.last_diagnostics.append(diag)
                entries_added += 1

        return signals
