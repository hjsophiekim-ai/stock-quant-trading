"""
Paper 종가베팅 v1 — T+1 overnight / close-betting (scalp·장마감 강제청산과 분리).

- 분류: close-betting / overnight short swing
- 진입: KST 설정 구간(기본 15:10~15:18), 5개 신호 중 3개 이상
- 청산: 익거래일 오전(기본 09:00~10:30) 별도 reason
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any

import pandas as pd
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.strategy.base_strategy import BaseStrategy, StrategyContext, StrategySignal
from app.strategy.intraday_common import parse_krx_hhmm, quote_liquidity_from_payload, session_vwap
from app.strategy.intraday_paper_state import IntradayPaperState
from app.strategy.market_regime import MarketRegimeConfig, MarketRegimeInputs, classify_market_regime
from app.strategy.paper_position_sizing import compute_intraday_buy_quantity

_KST = ZoneInfo("Asia/Seoul")

# 테스트용 고정 시각(운영에서는 None)
_debug_now_kst: datetime | None = None


def _now_kst() -> datetime:
    if _debug_now_kst is not None:
        return _debug_now_kst
    return datetime.now(_KST)


def _bar_dt_kst(ts: Any) -> datetime:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        return t.tz_localize(_KST).to_pydatetime()
    return t.tz_convert(_KST).to_pydatetime()


def _session_ymd_from_bars(sub: pd.DataFrame) -> str | None:
    if sub.empty:
        return None
    last = sub.sort_values("date").iloc[-1]["date"]
    return _bar_dt_kst(last).strftime("%Y%m%d")


def _filter_session_bars(sub: pd.DataFrame, session_ymd: str) -> pd.DataFrame:
    if sub.empty:
        return sub
    rows = []
    for _, r in sub.sort_values("date").iterrows():
        if _bar_dt_kst(r["date"]).strftime("%Y%m%d") == session_ymd:
            rows.append(r)
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=sub.columns)


def _bars_between_times(sub: pd.DataFrame, session_ymd: str, t0: time, t1: time) -> pd.DataFrame:
    s = _filter_session_bars(sub, session_ymd)
    if s.empty:
        return s
    keep = []
    for _, r in s.iterrows():
        tt = _bar_dt_kst(r["date"]).time()
        if t0 <= tt <= t1:
            keep.append(r)
    return pd.DataFrame(keep) if keep else pd.DataFrame(columns=sub.columns)


def _day_ohlc(sub_all: pd.DataFrame) -> tuple[float, float, float]:
    if sub_all.empty:
        return 0.0, 0.0, 0.0
    lo = float(sub_all["low"].min())
    hi = float(sub_all["high"].max())
    cl = float(sub_all.sort_values("date")["close"].iloc[-1])
    return lo, hi, cl


def _morning_accumulation_score(morning: pd.DataFrame, day_vwap_last: float) -> tuple[float, bool]:
    """0~1 점수 + morning_accumulation 통과 여부."""
    if morning.empty or len(morning) < 4:
        return 0.0, False
    close = morning["close"].astype(float)
    high = morning["high"].astype(float)
    low = morning["low"].astype(float)
    vol = morning["volume"].astype(float).clip(lower=0.0)
    tp = (morning["high"] + morning["low"] + morning["close"]) / 3.0
    trade_val = float((tp * vol).sum())
    above_vwap = float((close > day_vwap_last * 0.999).mean()) if day_vwap_last > 0 else 0.0
    greens = float((close >= morning["open"].astype(float)).mean())
    lows = low.cummin()
    highs = high.cummax()
    hl_ok = float((lows.diff().fillna(0) >= -1e-9).mean()) * 0.5 + float((highs.diff().fillna(0) >= -1e-9).mean()) * 0.5
    # 거래대금 규모는 후보 간 상대비교에서 재스케일 → 여기서는 형태 점수 위주
    score = 0.25 * min(1.0, above_vwap * 1.1) + 0.25 * min(1.0, greens) + 0.25 * min(1.0, hl_ok) + 0.25 * min(
        1.0, (len(morning) / 90.0) ** 0.5
    )
    ok = score >= 0.52 and above_vwap >= 0.45 and greens >= 0.48
    return float(score), bool(ok)


def _afternoon_distribution_score(
    afternoon: pd.DataFrame,
    morning_low: float,
    day_lo: float,
    day_hi: float,
    last_close: float,
    day_vwap_last: float,
) -> tuple[float, bool]:
    if afternoon.empty or len(afternoon) < 3:
        return 0.0, False
    hi = float(afternoon["high"].max())
    lo = float(afternoon["low"].min())
    plunge = morning_low > 0 and lo < morning_low * 0.97
    rng = max(day_hi - day_lo, 1e-9)
    close_zone = (last_close - day_lo) / rng
    near_high = close_zone >= (1.0 - 0.35)  # 상단 35% 이내(요구 30% 근접)
    vwap_ok = day_vwap_last <= 0 or last_close >= day_vwap_last * 0.997
    tail = afternoon.sort_values("date").tail(4)
    bad_wicks = 0
    for _, r in tail.iterrows():
        o, h, low, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
        body = abs(c - o)
        upper = h - max(o, c)
        if c < o and upper > body * 1.35 and body > 0:
            bad_wicks += 1
    tail_ok = bad_wicks < 2 and not plunge
    score = (
        0.35 * (0.0 if plunge else 1.0)
        + 0.25 * (1.0 if vwap_ok else 0.0)
        + 0.25 * (1.0 if near_high else max(0.0, close_zone - 0.4))
        + 0.15 * (1.0 if tail_ok else 0.0)
    )
    ok = (not plunge) and vwap_ok and near_high and tail_ok
    return float(min(1.0, score)), bool(ok)


def _relative_strength_ok(
    sym: str,
    sub: pd.DataFrame,
    kospi_day_ret: float,
    cohort_tv: list[float],
    min_tv: float,
) -> tuple[float, bool]:
    if sub.empty:
        return 0.0, False
    close = sub["close"].astype(float)
    vol = sub["volume"].astype(float).clip(lower=0.0)
    tp = (sub["high"] + sub["low"] + sub["close"]) / 3.0
    tv = float((tp * vol).sum())
    if tv < min_tv:
        return 0.0, False
    first_c = float(close.iloc[0])
    last_c = float(close.iloc[-1])
    sym_ret = (last_c / first_c - 1.0) * 100.0 if first_c > 0 else 0.0
    rel = sym_ret - kospi_day_ret
    if not cohort_tv:
        return 0.7, True
    thr = sorted(cohort_tv)[max(0, int(len(cohort_tv) * 0.35) - 1)]
    ok = tv >= thr and rel >= -0.15
    score = 0.5 + 0.25 * min(1.0, max(0.0, rel + 0.5)) + 0.25 * min(1.0, tv / max(thr, 1.0))
    return float(min(1.0, score)), bool(ok)


def _calendar_days_between(ymd_a: str, ymd_b: str) -> int:
    try:
        da = datetime.strptime(ymd_a, "%Y%m%d").date()
        db = datetime.strptime(ymd_b, "%Y%m%d").date()
        return int(abs((db - da).days))
    except ValueError:
        return 999


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=max(1, int(span)), adjust=False).mean()


def _rsi14(close: pd.Series) -> float:
    if len(close) < 15:
        return 50.0
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = (-delta).clip(lower=0.0)
    gain = up.ewm(alpha=1.0 / 14.0, adjust=False).mean()
    loss = down.ewm(alpha=1.0 / 14.0, adjust=False).mean().replace(0.0, 1e-9)
    rs = gain / loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return float(rsi.iloc[-1])


def _auction_instability_score(sub_s: pd.DataFrame, session_ymd: str) -> float:
    tail = _bars_between_times(sub_s, session_ymd, time(15, 10), time(15, 20))
    if tail.empty or len(tail) < 3:
        return 0.0
    c = tail["close"].astype(float)
    ref = float(c.iloc[0]) if float(c.iloc[0]) > 0 else 1.0
    return float((c.max() - c.min()) / ref * 100.0)


def _flow_proxy_score(sub_s: pd.DataFrame, session_ymd: str, day_vwap_last: float) -> tuple[float, bool]:
    """기관/외국인 수급 데이터 부재 시 close auction 내 매수 우위 프록시."""
    late = _bars_between_times(sub_s, session_ymd, time(14, 50), time(15, 20))
    if late.empty or len(late) < 8:
        return 0.0, False
    close = late["close"].astype(float)
    open_ = late["open"].astype(float)
    vol = late["volume"].astype(float).clip(lower=0.0)
    green_ratio = float((close >= open_).mean())
    drift = (float(close.iloc[-1]) / max(float(close.iloc[0]), 1e-9) - 1.0) * 100.0
    vol_bias = float(vol.tail(10).sum() / max(vol.sum(), 1e-9))
    vwap_ok = float(close.iloc[-1]) >= day_vwap_last * 0.998 if day_vwap_last > 0 else True
    score = 0.4 * min(1.0, green_ratio) + 0.3 * min(1.0, max(0.0, drift + 0.25)) + 0.3 * min(1.0, vol_bias * 2.2)
    ok = score >= 0.54 and vwap_ok
    return float(score), bool(ok)


@dataclass
class FinalBettingV1Strategy(BaseStrategy):
    """Paper 전용 종가베팅. IntradaySchedulerJobs + 분봉 유니버스에서만 동작."""

    regime_config: MarketRegimeConfig = field(default_factory=MarketRegimeConfig)
    last_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    last_intraday_signal_breakdown: dict[str, Any] = field(default_factory=dict)
    quote_by_symbol: dict[str, dict[str, Any]] = field(default_factory=dict)
    intraday_state: IntradayPaperState | None = None
    intraday_session_context: dict[str, Any] = field(default_factory=dict)
    risk_halt_new_entries: bool = False
    timeframe_label: str = "1m"
    pending_carry_updates: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    _final_betting_equity_krw: float = 0.0

    def consume_pending_carry_update(self, symbol: str) -> dict[str, Any] | None:
        return self.pending_carry_updates.pop(symbol, None)

    def on_fb_sell_accepted(self, symbol: str, sold_qty: int, state: IntradayPaperState) -> None:
        carry = state.final_betting_carry
        pos = carry.get("positions") or {}
        meta = pos.get(symbol)
        if not meta:
            return
        before = int(meta.get("shares", 0))
        left = before - int(sold_qty)
        if left <= 0:
            pos.pop(symbol, None)
            carry["positions"] = pos
            carry.setdefault("last_exit_kst", {})[symbol] = _now_kst().strftime("%Y%m%d")
        else:
            meta["shares"] = left
            if int(sold_qty) < before:
                meta["partial_scaleout_done"] = True
            pos[symbol] = meta
            carry["positions"] = pos

    def generate_signals(self, context: StrategyContext) -> list[StrategySignal]:
        cfg = get_settings()
        self.last_diagnostics = []
        self.last_intraday_signal_breakdown = {
            "strategy_profile": "final_betting_v1",
            "classification": "close_betting_overnight_swing",
            "entries_evaluated": 0,
            "exits_evaluated": 0,
        }
        signals: list[StrategySignal] = []
        st = self.intraday_state
        if st is None:
            self.last_intraday_signal_breakdown["blocked"] = "no_state"
            return signals

        now = _now_kst()
        today = now.strftime("%Y%m%d")
        sess = str((self.intraday_session_context or {}).get("krx_session_state") or "")
        self.last_intraday_signal_breakdown["session_state"] = sess

        t_entry0 = parse_krx_hhmm(cfg.paper_final_betting_entry_start_hhmm, default=time(15, 10))
        t_entry1 = parse_krx_hhmm(cfg.paper_final_betting_entry_end_hhmm, default=time(15, 18))
        t_exit0 = parse_krx_hhmm(cfg.paper_krx_regular_open_hhmm, default=time(9, 0))
        t_exit1 = parse_krx_hhmm(cfg.paper_final_betting_exit_deadline_hhmm, default=time(10, 30))

        regime = classify_market_regime(
            MarketRegimeInputs(
                kospi=context.kospi_index,
                sp500=context.sp500_index,
                volatility=context.volatility_index,
            ),
            self.regime_config,
        )
        high_vol_block = regime.regime == "high_volatility_risk"

        prices = context.prices
        portfolio = context.portfolio
        pos_symbols: dict[str, tuple[int, float]] = {}
        if not portfolio.empty and "symbol" in portfolio.columns:
            for sym in portfolio["symbol"].unique():
                row = portfolio[portfolio["symbol"] == sym].iloc[0]
                q = int(row.get("quantity") or 0)
                avg = float(row.get("average_price") or 0.0)
                if q > 0 and avg > 0:
                    pos_symbols[str(sym).strip()] = (q, avg)

        kospi_day_ret = 0.0
        if not context.kospi_index.empty and "value" in context.kospi_index.columns:
            v = context.kospi_index.sort_values("date")["value"].astype(float)
            if len(v) >= 2:
                kospi_day_ret = float((v.iloc[-1] / v.iloc[-2] - 1.0) * 100.0)

        # --- overnight exits (다음 거래일 오전) ---
        carry = st.final_betting_carry
        fb_positions: dict[str, Any] = dict(carry.get("positions") or {})
        tv_hist: dict[str, list[float]] = dict(carry.get("tv_history") or {})
        tv_hist_day: dict[str, str] = dict(carry.get("tv_history_day") or {})
        scale_start = time(9, 30)
        scale_end = time(10, 0)
        tp_mult = 1.0 + float(cfg.paper_final_betting_target_pct) / 100.0

        for sym, (qty, avg) in list(pos_symbols.items()):
            sub = prices[prices["symbol"] == sym].sort_values("date") if not prices.empty else pd.DataFrame()
            if sub.empty:
                continue
            session_ymd = _session_ymd_from_bars(sub) or now.strftime("%Y%m%d")
            sub_s = _filter_session_bars(sub, session_ymd)
            last_px = float(sub_s["close"].iloc[-1]) if not sub_s.empty else avg
            meta = fb_positions.get(sym) or {}
            entry_day = str(meta.get("entry_kst_date") or "")
            ref_close = float(meta.get("ref_close") or avg)
            partial_done = bool(meta.get("partial_scaleout_done"))
            is_carry_overnight = bool(entry_day) and entry_day != today

            exit_reason: str | None = None
            exit_qty = qty

            if sess == "regular" and is_carry_overnight:
                morning_bars = _bars_between_times(sub, session_ymd, t_exit0, now.time() if now.time() <= t_exit1 else t_exit1)
                open_px = float(morning_bars.sort_values("date")["open"].iloc[0]) if not morning_bars.empty else last_px
                gap_pct = (open_px / ref_close - 1.0) * 100.0 if ref_close > 0 else 0.0
                if gap_pct >= 1.2 and not partial_done:
                    exit_reason = "gap_take_profit"
                    exit_qty = max(1, qty // 2)
                elif scale_start <= now.time() <= scale_end and not partial_done and last_px >= avg * max(1.01, min(tp_mult, 1.02)):
                    exit_reason = "scaleout_morning_strength"
                    exit_qty = max(1, qty // 2)
                elif not morning_bars.empty:
                    vwap_m = session_vwap(morning_bars)
                    v_last = float(vwap_m.iloc[-1]) if len(vwap_m) else last_px
                    if last_px < v_last * 0.998 and now.time() >= time(9, 15):
                        exit_reason = "vwap_fail_exit"
                if exit_reason is None and last_px < avg * (1.0 - float(cfg.paper_final_betting_stop_loss_pct) / 100.0):
                    exit_reason = "open_weakness_stop"
                if exit_reason is None and now.time() >= t_exit1:
                    exit_reason = "time_exit_next_morning"
                if exit_reason is None and now.time() >= time(10, 0) and last_px < open_px * 0.998:
                    exit_reason = "open_weakness_stop"

            if exit_reason:
                self.last_intraday_signal_breakdown["exits_evaluated"] = (
                    int(self.last_intraday_signal_breakdown.get("exits_evaluated") or 0) + 1
                )
                signals.append(
                    StrategySignal(
                        symbol=sym,
                        side="sell",
                        quantity=min(qty, exit_qty),
                        price=last_px,
                        stop_loss_pct=None,
                        reason=exit_reason,
                        strategy_name="final_betting_v1",
                    )
                )

        # --- entries (당일 종가 직전) ---
        in_entry_window = sess == "regular" and t_entry0 <= now.time() <= t_entry1
        if not in_entry_window:
            self.last_intraday_signal_breakdown["entry_window"] = "closed"
        else:
            self.last_intraday_signal_breakdown["entry_window"] = "open"

        if self.risk_halt_new_entries:
            self.last_intraday_signal_breakdown["blocked"] = "daily_loss_halt"
            return signals
        if high_vol_block:
            self.last_intraday_signal_breakdown["blocked"] = "high_volatility_risk_no_entry"
            return signals
        # 지수 필터: KOSPI 수익률이 음수이고 5일 EMA 아래면 보수화(신규 진입 중단).
        if not context.kospi_index.empty and "close" in context.kospi_index.columns:
            kclose = context.kospi_index.sort_values("date")["close"].astype(float)
            if len(kclose) >= 6:
                ema5 = _ema(kclose, 5)
                if float(kclose.iloc[-1]) < float(ema5.iloc[-1]) and kospi_day_ret <= -0.35:
                    self.last_intraday_signal_breakdown["blocked"] = "index_filter_risk_off"
                    return signals
        if not in_entry_window:
            return signals

        open_slots = max(0, int(cfg.paper_final_betting_max_new_positions) - len(pos_symbols))
        entered_today = list(carry.get("entered_symbols_today") or [])
        if open_slots <= 0:
            self.last_intraday_signal_breakdown["blocked"] = "max_open_positions"
            return signals

        last_exit_map: dict[str, str] = dict(carry.get("last_exit_kst") or {})
        cooldown = int(cfg.paper_final_betting_reentry_cooldown_days)
        min_tv = float(cfg.paper_final_betting_min_trade_value_krw)

        cohort_tv: list[float] = []
        if not prices.empty:
            for sym2 in prices["symbol"].unique():
                s2 = prices[prices["symbol"] == sym2].sort_values("date")
                ymd2 = _session_ymd_from_bars(s2)
                if not ymd2:
                    continue
                s2f = _filter_session_bars(s2, ymd2)
                if s2f.empty:
                    continue
                tp2 = (s2f["high"] + s2f["low"] + s2f["close"]) / 3.0
                tv2 = float((tp2 * s2f["volume"].astype(float).clip(lower=0.0)).sum())
                if tv2 > 0:
                    cohort_tv.append(tv2)

        ranked: list[tuple[float, str, dict[str, Any]]] = []

        if not prices.empty:
            for sym in prices["symbol"].unique():
                sym = str(sym).strip()
                if sym in pos_symbols:
                    continue
                if len(entered_today) >= int(cfg.paper_final_betting_max_new_positions) and sym not in entered_today:
                    continue
                if sym in entered_today:
                    continue
                le = last_exit_map.get(sym)
                if le and cooldown > 0 and _calendar_days_between(le, today) < cooldown:
                    continue

                sub = prices[prices["symbol"] == sym].sort_values("date")
                session_ymd = _session_ymd_from_bars(sub)
                if not session_ymd:
                    continue
                sub_s = _filter_session_bars(sub, session_ymd)
                if len(sub_s) < 25:
                    diag: dict[str, Any] = {
                        "symbol": sym,
                        "strategy": "final_betting_v1",
                        "entered": False,
                        "blocked_reason": "insufficient_bars",
                        "morning_accumulation_score": 0.0,
                        "distribution_unfinished_score": 0.0,
                        "close_strength_score": 0.0,
                        "final_betting_rank": None,
                    }
                    self.last_diagnostics.append(diag)
                    continue

                qp = self.quote_by_symbol.get(sym) or {}
                liq = quote_liquidity_from_payload(qp) if qp else None
                if liq and liq["acml_tr_pbmn"] < min_tv:
                    self.last_diagnostics.append(
                        {
                            "symbol": sym,
                            "strategy": "final_betting_v1",
                            "entered": False,
                            "blocked_reason": "min_trade_value",
                            "morning_accumulation_score": 0.0,
                            "distribution_unfinished_score": 0.0,
                            "close_strength_score": 0.0,
                            "final_betting_rank": None,
                        }
                    )
                    continue
                if liq and liq["spread_pct"] > 0.55:
                    self.last_diagnostics.append(
                        {
                            "symbol": sym,
                            "strategy": "final_betting_v1",
                            "entered": False,
                            "blocked_reason": "spread",
                            "morning_accumulation_score": 0.0,
                            "distribution_unfinished_score": 0.0,
                            "close_strength_score": 0.0,
                            "final_betting_rank": None,
                        }
                    )
                    continue

                morning = _bars_between_times(sub_s, session_ymd, time(9, 0), time(10, 30))
                afternoon = _bars_between_times(sub_s, session_ymd, time(11, 0), time(15, 10))
                day_lo, day_hi, last_close = _day_ohlc(sub_s)
                vw = session_vwap(sub_s)
                day_vwap_last = float(vw.iloc[-1]) if len(vw) else last_close
                morning_lo = float(morning["low"].min()) if not morning.empty else day_lo
                close_s = sub_s["close"].astype(float)
                ma5 = _ema(close_s, 5)
                ma5_last = float(ma5.iloc[-1]) if len(ma5) else last_close
                rsi14 = _rsi14(close_s)
                pullback_ok = ma5_last > 0 and abs(last_close - ma5_last) / ma5_last <= 0.0085
                rsi_ok = 40.0 <= rsi14 <= 52.0
                last_bar = sub_s.sort_values("date").iloc[-1]
                prev_low = float(sub_s.sort_values("date")["low"].iloc[-2]) if len(sub_s) >= 2 else float(last_bar["low"])
                support_ok = float(last_bar["close"]) < float(last_bar["open"]) and float(last_bar["low"]) >= prev_low * 0.999
                flow_score, flow_ok = _flow_proxy_score(sub_s, session_ymd, day_vwap_last)
                auction_instability = _auction_instability_score(sub_s, session_ymd)
                if auction_instability >= 1.0:
                    self.last_diagnostics.append(
                        {
                            "symbol": sym,
                            "strategy": "final_betting_v1",
                            "entered": False,
                            "blocked_reason": "auction_price_instability",
                            "morning_accumulation_score": 0.0,
                            "distribution_unfinished_score": 0.0,
                            "close_strength_score": 0.0,
                            "final_betting_rank": None,
                            "auction_instability_pct": round(auction_instability, 4),
                        }
                    )
                    continue

                m_score, m_ok = _morning_accumulation_score(morning, day_vwap_last)
                a_score, a_ok = _afternoon_distribution_score(
                    afternoon, morning_lo, day_lo, day_hi, last_close, day_vwap_last
                )
                close_above = last_close >= day_vwap_last * 0.998 if day_vwap_last > 0 else False
                zone_pct = float(cfg.paper_final_betting_day_high_zone_pct)
                in_high_zone = last_close >= day_lo + (day_hi - day_lo) * (1.0 - zone_pct / 100.0) if day_hi > day_lo else False
                rel_score, rel_ok = _relative_strength_ok(sym, sub_s, kospi_day_ret, cohort_tv, min_tv)

                # 5신호(기존 요구) + 종가 눌림목 조건을 게이트로 추가
                hits = sum([m_ok, a_ok, close_above, in_high_zone, rel_ok])
                pullback_gate = pullback_ok and rsi_ok and support_ok and flow_ok
                close_strength = (
                    0.25 * (1.0 if close_above else 0.0)
                    + 0.25 * (1.0 if in_high_zone else 0.0)
                    + 0.25 * min(1.0, max(0.0, (last_close - day_lo) / max(day_hi - day_lo, 1e-9)))
                    + 0.25 * rel_score
                )
                blocked = ""
                tv_sym = float(liq["acml_tr_pbmn"]) if liq else 0.0
                if tv_hist_day.get(sym) != today and tv_sym > 0:
                    hist = list(tv_hist.get(sym) or [])
                    hist.append(tv_sym)
                    tv_hist[sym] = hist[-5:]
                    tv_hist_day[sym] = today
                avg5 = sum(tv_hist.get(sym) or []) / max(1, len(tv_hist.get(sym) or []))
                tv_spike_ok = avg5 <= 0 or tv_sym >= avg5 * 2.0
                if hits < 3:
                    blocked = "signals_lt_3"
                elif not pullback_gate:
                    blocked = "pullback_signal_not_met"
                elif not tv_spike_ok:
                    blocked = "trade_value_not_2x_avg5"
                if liq:
                    # 과열·급등 휴리스틱: 당일 고가 대비 종가 괴리가 너무 크면 제외
                    if day_hi > 0 and last_close > day_hi * 1.095:
                        blocked = "overheated_chase"
                if blocked:
                    self.last_diagnostics.append(
                        {
                            "symbol": sym,
                            "strategy": "final_betting_v1",
                            "entered": False,
                            "blocked_reason": blocked,
                            "morning_accumulation_score": round(m_score, 4),
                            "distribution_unfinished_score": round(a_score, 4),
                            "close_strength_score": round(float(close_strength), 4),
                            "signal_hits": int(hits),
                            "morning_accumulation": bool(m_ok),
                            "afternoon_distribution_unfinished": bool(a_ok),
                            "close_above_vwap": bool(close_above),
                            "close_near_day_high": bool(in_high_zone),
                            "relative_trade_value_strong": bool(rel_ok),
                            "pullback_near_ma5": bool(pullback_ok),
                            "rsi14": round(rsi14, 3),
                            "rsi_band_ok": bool(rsi_ok),
                            "support_candle_ok": bool(support_ok),
                            "flow_proxy_score": round(flow_score, 4),
                            "flow_proxy_ok": bool(flow_ok),
                            "trade_value_today": round(tv_sym, 2),
                            "trade_value_avg5": round(avg5, 2),
                            "trade_value_spike_ok": bool(tv_spike_ok),
                            "final_betting_rank": None,
                        }
                    )
                    continue

                ranked.append(
                    (
                        tv_sym,
                        sym,
                        {
                            "m": m_score,
                            "a": a_score,
                            "cs": float(close_strength),
                            "hits": hits,
                            "rsi14": rsi14,
                            "flow_proxy_score": flow_score,
                            "avg5": avg5,
                        },
                    )
                )

        ranked.sort(key=lambda x: -x[0])
        entries_added = 0
        for rank_i, (_tv, sym, _sc_pack) in enumerate(ranked):
            if entries_added >= open_slots:
                break
            if len(entered_today) + entries_added >= int(cfg.paper_final_betting_max_new_positions):
                break
            self.last_intraday_signal_breakdown["entries_evaluated"] = (
                int(self.last_intraday_signal_breakdown.get("entries_evaluated") or 0) + 1
            )
            sub = prices[prices["symbol"] == sym].sort_values("date")
            session_ymd = _session_ymd_from_bars(sub) or now.strftime("%Y%m%d")
            sub_s = _filter_session_bars(sub, session_ymd)
            last_close = float(sub_s["close"].iloc[-1])
            morning = _bars_between_times(sub_s, session_ymd, time(9, 0), time(10, 30))
            afternoon = _bars_between_times(sub_s, session_ymd, time(11, 0), time(15, 10))
            day_lo, day_hi, _lc = _day_ohlc(sub_s)
            vw = session_vwap(sub_s)
            day_vwap_last = float(vw.iloc[-1]) if len(vw) else last_close
            morning_lo = float(morning["low"].min()) if not morning.empty else day_lo
            m_score, m_ok = _morning_accumulation_score(morning, day_vwap_last)
            a_score, a_ok = _afternoon_distribution_score(
                afternoon, morning_lo, day_lo, day_hi, last_close, day_vwap_last
            )
            close_above = last_close >= day_vwap_last * 0.998 if day_vwap_last > 0 else False
            zone_pct = float(cfg.paper_final_betting_day_high_zone_pct)
            in_high_zone = last_close >= day_lo + (day_hi - day_lo) * (1.0 - zone_pct / 100.0) if day_hi > day_lo else False
            rel_score, rel_ok = _relative_strength_ok(sym, sub_s, kospi_day_ret, cohort_tv, min_tv)
            hits = sum([m_ok, a_ok, close_above, in_high_zone, rel_ok])
            close_s = sub_s["close"].astype(float)
            rsi14 = _rsi14(close_s)
            flow_score, _ = _flow_proxy_score(sub_s, session_ymd, day_vwap_last)
            close_strength = (
                0.25 * (1.0 if close_above else 0.0)
                + 0.25 * (1.0 if in_high_zone else 0.0)
                + 0.25 * min(1.0, max(0.0, (last_close - day_lo) / max(day_hi - day_lo, 1e-9)))
                + 0.25 * rel_score
            )

            eq = float(getattr(self, "_final_betting_equity_krw", 0.0) or 0.0)
            q = compute_intraday_buy_quantity(
                price_krw=float(last_close),
                stop_loss_pct_points=float(cfg.paper_final_betting_stop_loss_pct),
                equity_krw=eq,
                intraday_budget_krw=max(eq, 1.0),
                max_position_pct=float(cfg.paper_final_betting_max_capital_per_position_pct),
                risk_per_trade_pct=min(float(cfg.paper_risk_per_trade_pct), float(cfg.paper_final_betting_stop_loss_pct)),
                fallback_qty=1,
            )
            ref_close = last_close
            self.pending_carry_updates[sym] = {
                "entry_kst_date": now.strftime("%Y%m%d"),
                "ref_close": ref_close,
                "shares": int(q),
                "partial_scaleout_done": False,
            }
            signals.append(
                StrategySignal(
                    symbol=sym,
                    side="buy",
                    quantity=int(q),
                    price=last_close,
                    stop_loss_pct=float(cfg.paper_final_betting_stop_loss_pct),
                    reason="final_betting_v1_entry",
                    strategy_name="final_betting_v1",
                )
            )
            diag = {
                "symbol": sym,
                "strategy": "final_betting_v1",
                "entered": True,
                "blocked_reason": "",
                "morning_accumulation_score": round(m_score, 4),
                "distribution_unfinished_score": round(a_score, 4),
                "close_strength_score": round(float(close_strength), 4),
                "signal_hits": int(hits),
                "morning_accumulation": bool(m_ok),
                "afternoon_distribution_unfinished": bool(a_ok),
                "close_above_vwap": bool(close_above),
                "close_near_day_high": bool(in_high_zone),
                "relative_trade_value_strong": bool(rel_ok),
                "rsi14": round(rsi14, 3),
                "flow_proxy_score": round(flow_score, 4),
                "final_betting_rank": rank_i + 1,
            }
            self.last_diagnostics.append(diag)
            entries_added += 1

        carry["tv_history"] = tv_hist
        carry["tv_history_day"] = tv_hist_day

        return signals


def set_final_betting_debug_now(dt: datetime | None) -> None:
    """테스트에서 KST '현재' 시각을 고정할 때 사용. 운영에서는 None."""
    global _debug_now_kst
    _debug_now_kst = dt
