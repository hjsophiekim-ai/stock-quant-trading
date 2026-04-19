"""Paper 인트라데이 — 3분봉 MACD/RSI/VWAP 보수형 단타 (당일청산)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.config import get_settings
from app.strategy.base_strategy import BaseStrategy, StrategyContext, StrategySignal
from app.strategy.intraday_common import (
    ema,
    effective_intraday_max_open_positions,
    get_krx_session_state_kst,
    intraday_liquidity_multipliers_for_state,
    krx_session_config_from_settings,
    last_bar_body_pct,
    macd_line_signal_hist,
    minutes_since_session_open_kst,
    minutes_to_regular_close_kst,
    quote_liquidity_from_payload,
    rsi_wilder,
    session_vwap,
    should_force_flatten_before_close_kst,
)
from app.strategy.intraday_entry_qty import resolved_intraday_entry_quantity
from app.strategy.intraday_paper_state import IntradayPaperState, parse_iso
from app.strategy.market_regime import MarketRegimeConfig, MarketRegimeInputs, classify_market_regime


@dataclass
class ScalpMacdRsi3mV1Strategy(BaseStrategy):
    """
    3분봉 기준 보수형 단타. 메인 장중 축용.
    실험용(v2/v3)보다 진입 점수·시간대 제약을 강화한다.
    """

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

    def generate_signals(self, context: StrategyContext) -> list[StrategySignal]:
        cfg = get_settings()
        self.last_diagnostics = []
        self.last_intraday_filter_breakdown = []
        self.last_intraday_signal_breakdown = {"entries_evaluated": 0, "exits_evaluated": 0, "strategy_role": "main_intraday"}
        signals: list[StrategySignal] = []
        st = self.intraday_state

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

        # 손절·익절·보유 — 보수형 고정 밴드
        sl_pct = 0.72
        tp1_pct = 0.8
        tp2_pct = 1.55
        trail_pct = float(cfg.paper_intraday_trailing_stop_pct) * 0.85
        hold_min = max(25.0, float(cfg.paper_intraday_max_hold_minutes) * 0.55)

        max_open = effective_intraday_max_open_positions(cfg, "scalp_macd_rsi_3m_v1")
        open_block_m = int(cfg.paper_scalp_macd_entry_open_block_minutes)
        close_block_m = int(cfg.paper_scalp_macd_entry_close_block_minutes)

        for sym in list(pos_symbols):
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
            elif not sub.empty and len(sub) >= 30:
                close = sub["close"].astype(float)
                macd, sigl, hist = macd_line_signal_hist(close)
                rsi = rsi_wilder(close, 14)
                sl = avg * (1.0 - sl_pct / 100.0)
                tp1 = avg * (1.0 + tp1_pct / 100.0)
                tp2 = avg * (1.0 + tp2_pct / 100.0)
                peak = float(st.peak_price.get(sym, last_px)) if st else last_px
                if last_px > peak:
                    peak = last_px
                    if st:
                        st.peak_price[sym] = peak
                trail_line = peak * (1.0 - trail_pct / 100.0) if trail_pct > 0 else 0.0
                entry_ts = parse_iso(st.entry_ts_iso.get(sym)) if st else None

                macd_dead = len(macd) >= 2 and float(macd.iloc[-1]) < float(sigl.iloc[-1]) and float(
                    macd.iloc[-2]
                ) >= float(sigl.iloc[-2])
                rsi_drop = len(rsi) >= 2 and float(rsi.iloc[-1]) < float(rsi.iloc[-2])

                if last_px <= sl:
                    exit_reason = "stop_loss"
                elif last_px >= tp2:
                    exit_reason = "take_profit_final"
                elif last_px >= tp1:
                    exit_reason = "take_profit_1"
                elif macd_dead and rsi_drop and last_px >= avg * 1.001:
                    exit_reason = "macd_dead_rsi_exit"
                elif trail_pct > 0 and last_px < trail_line and last_px >= tp1 * 0.998:
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
                        strategy_name="scalp_macd_rsi_3m_v1",
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
        if open_n >= max_open:
            self.last_intraday_signal_breakdown["blocked"] = "max_open_positions"
            return signals

        if high_vol_block and (not self.manual_override_enabled):
            self.last_intraday_signal_breakdown["blocked"] = "high_volatility_risk_no_entry"
            return signals

        mins_open = minutes_since_session_open_kst(session_config=scfg)
        mins_left = minutes_to_regular_close_kst(session_config=scfg)
        if mins_open >= 0 and mins_open < float(open_block_m):
            self.last_intraday_signal_breakdown["blocked"] = "open_session_entry_block"
            return signals
        if mins_left >= 0 and mins_left < float(close_block_m):
            self.last_intraday_signal_breakdown["blocked"] = "close_session_entry_block"
            return signals

        max_new = max(0, max_open - open_n)
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
                    "strategy": "scalp_macd_rsi_3m_v1",
                    "entered": False,
                    "blocked_reason": "",
                    "macd_cross": False,
                    "macd_hist_improving": False,
                    "rsi_band_ok": False,
                    "above_vwap": False,
                    "above_ema20": False,
                    "volume_burst": False,
                    "hit_count": 0,
                }
                if len(sub) < 35:
                    diag["blocked_reason"] = "insufficient_bars"
                    self.last_diagnostics.append(diag)
                    continue

                qp = self.quote_by_symbol.get(sym) or {}
                liq = quote_liquidity_from_payload(qp) if qp else None
                if liq:
                    min_v = float(cfg.paper_intraday_min_quote_volume) * 0.9 * m_vol
                    min_tv = float(cfg.paper_intraday_min_trade_value_krw) * 0.9 * m_vol
                    max_sp = float(cfg.paper_intraday_max_spread_pct) * 0.95 * m_spread
                    if liq["acml_vol"] < min_v:
                        diag["blocked_reason"] = "liquidity_volume"
                        self.last_intraday_filter_breakdown.append({"symbol": sym, "rule": "min_volume"})
                        self.last_diagnostics.append(diag)
                        continue
                    if liq["acml_tr_pbmn"] < min_tv:
                        diag["blocked_reason"] = "liquidity_trade_value"
                        self.last_diagnostics.append(diag)
                        continue
                    if liq["spread_pct"] > max_sp:
                        diag["blocked_reason"] = "spread"
                        self.last_diagnostics.append(diag)
                        continue

                close = sub["close"].astype(float)
                vol = sub["volume"].astype(float)
                macd, sigl, hist = macd_line_signal_hist(close)
                rsi = rsi_wilder(close, 14)
                vwap = session_vwap(sub)
                ema20 = ema(close, 20)

                macd_cross = False
                if len(macd) >= 3 and len(sigl) >= 3:
                    macd_cross = float(macd.iloc[-2]) <= float(sigl.iloc[-2]) and float(macd.iloc[-1]) > float(sigl.iloc[-1])
                    if not macd_cross and len(macd) >= 4:
                        macd_cross = float(macd.iloc[-3]) <= float(sigl.iloc[-3]) and float(macd.iloc[-2]) > float(
                            sigl.iloc[-2]
                        )

                macd_hist_improving = False
                if len(hist) >= 3:
                    macd_hist_improving = float(hist.iloc[-1]) > float(hist.iloc[-2]) > float(hist.iloc[-3])

                rsi_last = float(rsi.iloc[-1]) if len(rsi) else 50.0
                rsi_band_ok = 50.0 <= rsi_last <= 68.0

                last_close = float(close.iloc[-1])
                above_vwap = len(vwap) > 0 and last_close > float(vwap.iloc[-1]) * 1.0001
                above_ema20 = len(ema20) > 0 and last_close > float(ema20.iloc[-1]) * 1.0001

                vol_ma20 = float(vol.tail(20).mean()) if len(vol) >= 20 else float(vol.mean())
                volume_burst = vol_ma20 > 0 and float(vol.iloc[-1]) >= vol_ma20 * 1.3

                macd_ok = float(macd.iloc[-1]) > float(sigl.iloc[-1]) if len(macd) and len(sigl) else False
                macd_signal_secondary = bool(macd_cross or macd_hist_improving)

                diag["macd_cross"] = bool(macd_cross)
                diag["macd_hist_improving"] = bool(macd_hist_improving)
                diag["rsi_band_ok"] = bool(rsi_band_ok)
                diag["above_vwap"] = bool(above_vwap)
                diag["above_ema20"] = bool(above_ema20)
                diag["volume_burst"] = bool(volume_burst)
                diag["macd_line_gt_signal"] = bool(macd_ok)

                core = [macd_ok, macd_signal_secondary, rsi_band_ok, above_vwap, above_ema20, volume_burst]
                hit_count = sum(1 for x in core if x)
                diag["hit_count"] = int(hit_count)

                body_pct = last_bar_body_pct(sub) or 0.0
                if body_pct > float(cfg.paper_intraday_max_chase_candle_pct) * 1.15 * m_chase:
                    diag["blocked_reason"] = "chase_candle"
                    self.last_intraday_filter_breakdown.append({"symbol": sym, "rule": "chase_candle"})
                    self.last_diagnostics.append(diag)
                    continue

                if hit_count < 4:
                    diag["blocked_reason"] = f"score_below_4 (hits={hit_count}/6)"
                    self.last_diagnostics.append(diag)
                    continue

                if not macd_ok:
                    diag["blocked_reason"] = "macd_not_above_signal"
                    self.last_diagnostics.append(diag)
                    continue

                last_px = last_close
                qty_buy = resolved_intraday_entry_quantity(cfg, self, price_krw=last_px, stop_loss_pct_points=sl_pct)
                signals.append(
                    StrategySignal(
                        symbol=sym,
                        side="buy",
                        quantity=qty_buy,
                        price=last_px,
                        stop_loss_pct=sl_pct,
                        reason="scalp_macd_rsi_3m_v1_entry",
                        strategy_name="scalp_macd_rsi_3m_v1",
                    )
                )
                diag["entered"] = True
                diag["blocked_reason"] = ""
                self.last_diagnostics.append(diag)
                entries_added += 1

        return signals
