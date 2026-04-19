"""Paper 인트라데이 RSI red/blue 플래그 기반 고빈도 스캘프 v1 (3m 봉 권장).

- 매수: RSI red 플래그 + 유동성·스프레드·추격 캔들 필터 + 점수 게이트
- 매도: RSI blue 플래그 우선, 이후 손절/익절/트레일/시간/장마감 강제청산
- 목표: 일 5회+ 완료 체결(페이퍼)에 가깝게 기회 확대하되 리스크·쿨다운으로 과매매 억제
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.config import get_settings
from app.strategy.base_strategy import BaseStrategy, StrategyContext, StrategySignal
from app.strategy.intraday_common import (
    effective_intraday_max_open_positions,
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
from app.strategy.rsi_flag_helpers import rsi_blue_flag_sell, rsi_red_flag_buy


@dataclass
class ScalpRsiFlagHfV1Strategy(BaseStrategy):
    regime_config: MarketRegimeConfig = field(default_factory=MarketRegimeConfig)
    last_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    last_intraday_filter_breakdown: list[dict[str, Any]] = field(default_factory=list)
    last_intraday_signal_breakdown: dict[str, Any] = field(default_factory=dict)

    quote_by_symbol: dict[str, dict[str, Any]] = field(default_factory=dict)
    intraday_state: IntradayPaperState | None = None
    intraday_session_context: dict[str, Any] = field(default_factory=dict)
    risk_halt_new_entries: bool = False
    manual_override_enabled: bool = False
    timeframe_label: str = "3m"

    _risk_tighten: float = 0.92

    def generate_signals(self, context: StrategyContext) -> list[StrategySignal]:
        cfg = get_settings()
        sid = str(getattr(self, "_paper_strategy_id", None) or "scalp_rsi_flag_hf_v1").strip()
        self.last_diagnostics = []
        self.last_intraday_filter_breakdown = []
        self.last_intraday_signal_breakdown = {
            "entries_evaluated": 0,
            "exits_evaluated": 0,
            "strategy_profile": sid,
            "label_ko": "RSI red/blue 플래그 고빈도 스캘프(3m·리스크 게이트)",
        }
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
        hold_min = float(cfg.paper_intraday_max_hold_minutes) * 0.55
        min_path = max(1, int(getattr(cfg, "paper_rsi_hf_min_entry_score", 2)))
        max_sym_trades = int(getattr(cfg, "paper_rsi_hf_max_trades_per_symbol_day", 4))

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
            blue_diag: dict[str, Any] = {}
            if not sub.empty and len(sub) >= 30:
                blue_diag = rsi_blue_flag_sell(sub)
            if flatten_close:
                exit_reason = "forced_flatten_before_close"
            elif not sub.empty:
                if bool(blue_diag.get("rsi_blue_flag_sell")):
                    exit_reason = "rsi_blue_flag_sell"
                else:
                    close_s = sub["close"].astype(float)
                    ema8 = ema(close_s, 8)
                    cushion_px = avg * (1.0 + max(float(cfg.paper_intraday_stop_loss_pct), 0.35) * 0.01 * 0.5)
                    momentum_fail = False
                    if len(ema8) >= 2 and last_px >= cushion_px and last_px < float(ema8.iloc[-1]) * 0.998:
                        if len(close_s) >= 2 and last_px < float(close_s.iloc[-2]):
                            momentum_fail = True
                    if momentum_fail:
                        exit_reason = "momentum_failure_ema"
                    sl = avg * (1.0 - sl_pct / 100.0)
                    tp = avg * (1.0 + tp_pct / 100.0)
                    peak = float(st.peak_price.get(sym, last_px)) if st else last_px
                    if last_px > peak:
                        peak = last_px
                        if st:
                            st.peak_price[sym] = peak
                    trail_line = peak * (1.0 - trail_pct / 100.0) if trail_pct > 0 else 0.0
                    entry_ts = parse_iso(st.entry_ts_iso.get(sym)) if st else None
                    if exit_reason is None and last_px <= sl:
                        exit_reason = "stop_loss"
                    elif exit_reason is None and last_px >= tp:
                        exit_reason = "take_profit"
                    elif exit_reason is None and trail_pct > 0 and last_px < trail_line:
                        exit_reason = "trailing_stop"
                    elif exit_reason is None and entry_ts is not None:
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
                        strategy_name=sid,
                    )
                )
                self.last_diagnostics.append(
                    {
                        "symbol": sym,
                        "side": "sell",
                        "exit_reason": exit_reason,
                        **{k: blue_diag.get(k) for k in ("rsi_blue_flag_sell", "rsi_blue_flag_reason") if blue_diag},
                    }
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
        max_pos = effective_intraday_max_open_positions(cfg, sid)
        if open_n >= max_pos:
            self.last_intraday_signal_breakdown["blocked"] = "max_open_positions"
            return signals

        if high_vol_block and (not self.manual_override_enabled):
            self.last_intraday_signal_breakdown["blocked"] = "high_volatility_risk_no_entry"
            return signals

        max_new = max(0, max_pos - open_n)
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
                    "strategy": sid,
                }
                if st and max_sym_trades > 0:
                    n_sym = int((st.symbol_entries_today or {}).get(sym, 0))
                    if n_sym >= max_sym_trades:
                        diag["blocked_reason"] = "max_trades_per_symbol_day"
                        self.last_diagnostics.append(diag)
                        continue

                if len(sub) < 28:
                    diag["blocked_reason"] = "insufficient_bars"
                    self.last_diagnostics.append(diag)
                    continue

                qp = self.quote_by_symbol.get(sym) or {}
                liq = quote_liquidity_from_payload(qp) if qp else None
                if liq:
                    min_v = float(cfg.paper_intraday_min_quote_volume) * 0.75 * m_vol
                    min_tv = float(cfg.paper_intraday_min_trade_value_krw) * 0.75 * m_vol
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

                red = rsi_red_flag_buy(sub)
                diag.update({k: red.get(k) for k in ("rsi_red_flag_buy", "rsi_red_flag_reason", "rsi_red_path_hits")})

                path_hits = int(red.get("rsi_red_path_hits") or 0)
                if path_hits < min_path:
                    diag["blocked_reason"] = f"path_hits_lt_min({path_hits}<{min_path})"
                    self.last_diagnostics.append(diag)
                    continue

                if not bool(red.get("rsi_red_flag_buy")):
                    diag["blocked_reason"] = "rsi_red_flag_false"
                    self.last_diagnostics.append(diag)
                    continue

                close = sub["close"].astype(float)
                ema3 = ema(close, 3)
                ema8 = ema(close, 8)
                vw = session_vwap(sub)
                rsi14 = rsi_wilder(close, 14)
                vol = sub["volume"].astype(float)
                vz = volume_zscore_recent(vol, 15)
                last_close = float(close.iloc[-1])
                vwap_ok = len(vw) and last_close >= float(vw.iloc[-1]) * 0.997
                ema_confirm = len(ema3) and len(ema8) and float(ema3.iloc[-1]) >= float(ema8.iloc[-1]) * 0.9985
                continuation = len(close) >= 6 and last_close >= float(close.iloc[-5]) * 1.0001
                sub_score = int(vwap_ok) + int(ema_confirm) + int(continuation) + int(vz is not None and vz > -0.2)
                diag["optional_vwap_ema_score"] = sub_score

                body_pct = last_bar_body_pct(sub) or 0.0
                if body_pct > float(cfg.paper_intraday_max_chase_candle_pct) * 1.15 * m_chase:
                    diag["blocked_reason"] = "chase_candle"
                    self.last_intraday_filter_breakdown.append({"symbol": sym, "rule": "chase_candle"})
                    self.last_diagnostics.append(diag)
                    continue

                from app.strategy.intraday_entry_qty import resolved_intraday_entry_quantity

                qty = resolved_intraday_entry_quantity(
                    cfg, self, price_krw=last_close, stop_loss_pct_points=sl_pct
                )
                signals.append(
                    StrategySignal(
                        symbol=sym,
                        side="buy",
                        quantity=qty,
                        price=last_close,
                        stop_loss_pct=sl_pct,
                        reason=f"{sid}_entry",
                        strategy_name=sid,
                    )
                )
                diag["entered"] = True
                diag["blocked_reason"] = ""
                self.last_diagnostics.append(diag)
                entries_added += 1

        return signals
