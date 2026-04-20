"""Paper 인트라데이 RSI red/blue 플래그 기반 고빈도 스캘프 v1 (3m 봉 권장).

- 매수: (1) RSI red 반전 경로 또는 (2) 모멘텀 연속 추세 경로 + 적응형 거래량 + 유동성·스프레드·추격 필터
- 매도: RSI blue 플래그 우선, 이후 손절/익절/트레일/시간/장마감 강제청산
- 목표: 일 5회+ 완료 체결(페이퍼)에 가깝게 기회 확대하되 리스크·쿨다운으로 과매매 억제
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.strategy.base_strategy import BaseStrategy, StrategyContext, StrategySignal
from app.strategy.intraday_common import (
    KrxSessionConfig,
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
from app.strategy.scalp_rsi_hf_momentum import evaluate_momentum_continuation_entry

_KST = ZoneInfo("Asia/Seoul")


def _leader_symbol_set(cfg: Any) -> set[str]:
    raw = str(getattr(cfg, "paper_rsi_hf_leader_symbols_csv", "") or "")
    return {x.strip() for x in raw.split(",") if x.strip()}


def _minutes_since_regular_open(sub: pd.DataFrame, scfg: KrxSessionConfig) -> float:
    if sub is None or sub.empty or "date" not in sub.columns:
        return 0.0
    ts = sub["date"].iloc[-1]
    dt = pd.Timestamp(ts).to_pydatetime()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_KST)
    else:
        dt = dt.astimezone(_KST)
    open_dt = datetime.combine(dt.date(), scfg.regular_open, tzinfo=_KST)
    return max(0.0, (dt - open_dt).total_seconds() / 60.0)


def _rsi_hf_adaptive_volume_floors(
    *,
    cfg: Any,
    minutes_since_open: float,
    is_leader: bool,
    regime: str,
    entry_mode: str,
    volume_z_extra: float = 0.0,
    volume_ratio_extra: float = 0.0,
) -> tuple[float, float, str]:
    late_m = float(getattr(cfg, "paper_rsi_hf_late_session_open_minutes", 330.0))
    if minutes_since_open < 40.0:
        z, r = -1.0, 0.88
    elif minutes_since_open < 210.0:
        z, r = -0.55, 0.92
    elif minutes_since_open < late_m:
        z, r = -0.50, 0.90
    else:
        z, r = -0.35, 0.94

    if entry_mode == "momentum":
        z -= 0.05
        r -= 0.02
    if is_leader:
        z -= 0.12
        r -= 0.03
    if regime == "sideways" and entry_mode == "momentum":
        z += 0.06
        r += 0.02
    if regime == "sideways" and entry_mode == "reversal":
        z += 0.03
        r += 0.01

    z = max(-1.5, float(z) + float(volume_z_extra))
    r = max(0.72, min(0.97, float(r) + float(volume_ratio_extra)))
    detail = (
        f"mode={entry_mode}; t={minutes_since_open:.1f}m; reg={regime}; leader={int(is_leader)}; z_floor={z:.3f}; r_floor={r:.3f}"
    )
    return z, r, detail


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
        mm_snap = getattr(self, "_paper_market_mode_snapshot", None) or {}
        mm_pol = (mm_snap.get("policy") or {}).get("scalp_rsi_hf", {}) if mm_snap else {}
        sid = str(getattr(self, "_paper_strategy_id", None) or "scalp_rsi_flag_hf_v1").strip()
        self.last_diagnostics = []
        self.last_intraday_filter_breakdown = []
        self.last_intraday_signal_breakdown = {
            "entries_evaluated": 0,
            "exits_evaluated": 0,
            "strategy_profile": sid,
            "label_ko": "RSI red/blue 플래그 고빈도 스캘프(3m·리스크 게이트)",
            "market_mode": {
                "market_mode_active": mm_snap.get("market_mode_active"),
                "market_mode_source": mm_snap.get("market_mode_source"),
                "status_line": mm_snap.get("status_line"),
            },
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

        rt = float(mm_pol.get("intraday_risk_tighten", rt))
        sl_pct = float(cfg.paper_intraday_stop_loss_pct) * rt
        tp_pct = float(cfg.paper_intraday_take_profit_pct) * rt
        trail_pct = float(cfg.paper_intraday_trailing_stop_pct) * rt
        hold_min = float(cfg.paper_intraday_max_hold_minutes) * 0.55
        min_path = max(1, int(getattr(cfg, "paper_rsi_hf_min_entry_score", 2)) + int(mm_pol.get("min_entry_score_delta", 0) or 0))
        max_sym_trades = max(
            1,
            int(getattr(cfg, "paper_rsi_hf_max_trades_per_symbol_day", 4)) + int(mm_pol.get("max_trades_per_symbol_delta", 0) or 0),
        )

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
        m_vol *= float(mm_pol.get("liquidity_volume_mult", 1.0) or 1.0)
        m_spread *= float(mm_pol.get("liquidity_spread_mult", 1.0) or 1.0)
        vz_x = float(mm_pol.get("volume_z_delta", 0.0) or 0.0)
        rr_x = float(mm_pol.get("volume_ratio_delta", 0.0) or 0.0)
        leader_syms = _leader_symbol_set(cfg)
        mom_min_hits = max(2, int(getattr(cfg, "paper_rsi_hf_momentum_min_hits", 3)) + int(mm_pol.get("momentum_min_hits_delta", 0) or 0))
        mom_min_hits_late = max(
            mom_min_hits,
            int(getattr(cfg, "paper_rsi_hf_momentum_min_hits_late", 4)) + int(mm_pol.get("momentum_min_hits_late_delta", 0) or 0),
        )
        mom_stop_mult = float(getattr(cfg, "paper_rsi_hf_momentum_stop_tighten_mult", 0.92))
        sw_m_mult = float(getattr(cfg, "paper_rsi_hf_sideways_momentum_qty_mult", 0.65))
        sw_r_mult = float(getattr(cfg, "paper_rsi_hf_sideways_reversal_qty_mult", 0.85))

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
                    "blocked_reason_detail": "",
                    "strategy": sid,
                    "entry_mode_selected": "",
                    "reversal_path_hits": 0,
                    "momentum_path_hits": 0,
                    "min_required_reversal_hits": int(min_path),
                    "min_required_momentum_hits": int(mom_min_hits),
                    "trend_strength_score": 0.0,
                    "continuation_quality_score": 0.0,
                    "strong_override_used": False,
                    "volume_confirmation_value": 0.0,
                    "volume_confirmation_threshold": 0.0,
                    "volume_confirmation_detail": "",
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

                is_leader = sym in leader_syms or (
                    bool(liq) and float(liq.get("acml_vol") or 0.0) >= float(cfg.paper_intraday_min_quote_volume) * 8.0
                )
                diag["is_leader_liquid_profile"] = bool(is_leader)
                minutes_so = _minutes_since_regular_open(sub, scfg)
                diag["minutes_since_regular_open"] = round(float(minutes_so), 3)

                z_rev, r_rev, vol_adapt_rev = _rsi_hf_adaptive_volume_floors(
                    cfg=cfg,
                    minutes_since_open=minutes_so,
                    is_leader=bool(is_leader),
                    regime=str(regime.regime),
                    entry_mode="reversal",
                    volume_z_extra=vz_x,
                    volume_ratio_extra=rr_x,
                )
                red = rsi_red_flag_buy(
                    sub,
                    volume_z_floor=z_rev,
                    volume_ratio_floor=r_rev,
                    is_leader_symbol=bool(is_leader),
                    trend_quality_for_volume=0,
                )
                diag.update(
                    {k: red.get(k) for k in ("rsi_red_flag_buy", "rsi_red_flag_reason", "rsi_red_path_hits", "rsi_red_core_ok")}
                )
                diag["reversal_path_hits"] = int(red.get("rsi_red_path_hits") or 0)
                for k in (
                    "volume_confirmation_ok",
                    "volume_confirmation_value",
                    "volume_confirmation_threshold",
                    "volume_ratio_vs_ma",
                    "volume_confirmation_ratio_floor",
                    "volume_confirmation_detail",
                    "strong_override_used",
                ):
                    if k in red:
                        diag[k] = red.get(k)
                diag["adaptive_volume_reversal_detail"] = vol_adapt_rev

                z_mom, r_mom, vol_adapt_mom = _rsi_hf_adaptive_volume_floors(
                    cfg=cfg,
                    minutes_since_open=minutes_so,
                    is_leader=bool(is_leader),
                    regime=str(regime.regime),
                    entry_mode="momentum",
                    volume_z_extra=vz_x,
                    volume_ratio_extra=rr_x,
                )
                mom = evaluate_momentum_continuation_entry(
                    sub,
                    min_hits=mom_min_hits,
                    min_hits_late_session=mom_min_hits_late,
                    minutes_since_open=minutes_so,
                    late_open_minutes=float(getattr(cfg, "paper_rsi_hf_late_session_open_minutes", 330.0)),
                    volume_z_floor=z_mom,
                    volume_ratio_floor=r_mom,
                    is_leader=bool(is_leader),
                )
                need_mom = int(mom_min_hits_late if minutes_so >= float(getattr(cfg, "paper_rsi_hf_late_session_open_minutes", 330.0)) else mom_min_hits)
                diag["min_required_momentum_hits"] = int(need_mom)
                diag["momentum_path_hits"] = int(mom.get("momentum_path_hits") or 0)
                diag["momentum_continuation_ok"] = bool(mom.get("momentum_continuation_ok"))
                diag["momentum_continuation_reason"] = str(mom.get("momentum_continuation_reason") or "")
                diag["momentum_paths_detail"] = str(mom.get("momentum_paths_detail") or "")
                diag["trend_strength_score"] = float(mom.get("trend_strength_score") or 0.0)
                diag["continuation_quality_score"] = float(mom.get("continuation_quality_score") or 0.0)
                diag["adaptive_volume_momentum_detail"] = vol_adapt_mom
                diag["strong_override_used"] = bool(red.get("strong_override_used")) or bool(
                    mom.get("strong_override_used")
                )

                rev_ok = bool(int(red.get("rsi_red_path_hits") or 0) >= min_path and bool(red.get("rsi_red_flag_buy")))
                mom_ok = bool(mom.get("momentum_continuation_ok"))
                cq_delta = float(mm_pol.get("continuation_quality_threshold_delta", 0.0) or 0.0)
                if mom_ok and abs(cq_delta) > 1e-6:
                    cq_min = 38.0 + cq_delta * 150.0
                    cq_min = max(24.0, min(56.0, cq_min))
                    if float(mom.get("continuation_quality_score") or 0.0) < cq_min:
                        mom_ok = False

                entry_mode = ""
                if mom_ok:
                    entry_mode = "momentum_continuation"
                elif rev_ok:
                    entry_mode = "reversal_entry_mode"

                if not entry_mode:
                    r_snip = f"path={int(red.get('rsi_red_path_hits') or 0)} red={bool(red.get('rsi_red_flag_buy'))} {red.get('rsi_red_flag_reason')}"
                    m_snip = f"mom_hits={int(mom.get('momentum_path_hits') or 0)} {mom.get('momentum_continuation_reason')}"
                    diag["blocked_reason_detail"] = f"reversal_gate:{r_snip}; momentum_gate:{m_snip}"
                    if int(red.get("rsi_red_path_hits") or 0) < min_path:
                        diag["blocked_reason"] = f"path_hits_lt_min({int(red.get('rsi_red_path_hits') or 0)}<{min_path})"
                    elif not bool(red.get("rsi_red_flag_buy")):
                        diag["blocked_reason"] = "rsi_red_flag_false"
                    else:
                        diag["blocked_reason"] = "no_entry_mode_passed"
                    self.last_diagnostics.append(diag)
                    continue

                diag["entry_mode_selected"] = entry_mode

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
                diag["rsi14_last"] = round(float(rsi14.iloc[-1]), 3) if len(rsi14) else None

                body_pct = last_bar_body_pct(sub) or 0.0
                chase_lim = (
                    float(cfg.paper_intraday_max_chase_candle_pct)
                    * 1.15
                    * m_chase
                    * float(mm_pol.get("chase_candle_mult", 1.0) or 1.0)
                )
                if entry_mode == "momentum_continuation":
                    chase_lim *= 0.92
                if body_pct > chase_lim:
                    diag["blocked_reason"] = "chase_candle"
                    diag["blocked_reason_detail"] = f"body_pct={body_pct:.3f} lim={chase_lim:.3f} mode={entry_mode}"
                    self.last_intraday_filter_breakdown.append({"symbol": sym, "rule": "chase_candle"})
                    self.last_diagnostics.append(diag)
                    continue

                from app.strategy.intraday_entry_qty import resolved_intraday_entry_quantity

                sl_use = float(sl_pct)
                if entry_mode == "momentum_continuation":
                    sl_use = float(sl_pct) * mom_stop_mult

                qty = resolved_intraday_entry_quantity(cfg, self, price_krw=last_close, stop_loss_pct_points=sl_use)
                qty_scale = 1.0
                if str(regime.regime) == "sideways":
                    qty_scale = sw_m_mult if entry_mode == "momentum_continuation" else sw_r_mult
                qty = max(1, int(round(float(qty) * float(qty_scale))))

                signals.append(
                    StrategySignal(
                        symbol=sym,
                        side="buy",
                        quantity=qty,
                        price=last_close,
                        stop_loss_pct=sl_use,
                        reason=f"{sid}_entry_{entry_mode}",
                        strategy_name=sid,
                    )
                )
                diag["entered"] = True
                diag["blocked_reason"] = ""
                diag["blocked_reason_detail"] = ""
                diag["regime_qty_scale_applied"] = round(float(qty_scale), 4)
                self.last_diagnostics.append(diag)
                entries_added += 1

        return signals
