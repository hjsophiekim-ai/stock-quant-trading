"""
Paper 종가베팅 v1 — T+1 overnight / close-betting (scalp·장마감 강제청산과 분리).

- 분류: close-betting / overnight short swing
- 진입: KST 설정 구간(기본 15:10~15:18), 5개 신호 중 3개 이상
- 청산: 익거래일 오전(기본 09:00~10:30) 별도 reason
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Any

import pandas as pd
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.orders.models import OrderRequest, OrderResult
from app.strategy.base_strategy import BaseStrategy, StrategyContext, StrategySignal
from app.strategy.intraday_common import parse_krx_hhmm, quote_liquidity_from_payload, session_vwap
from app.strategy.intraday_paper_state import IntradayPaperState
from app.strategy.final_betting_rebound import (
    blend_stop_tp_with_atr,
    build_daily_ohlc_from_intraday,
    daily_atr14_pct,
    evaluate_bearish_rebound_candidate,
)
from app.strategy.market_regime import MarketRegimeConfig, MarketRegimeInputs, classify_market_regime
from app.strategy.paper_position_sizing import compute_intraday_buy_quantity
from app.strategy.regime_soft import compute_soft_regime
from app.strategy.strategy_fill_performance import (
    apply_fb_dynamic_cooldown,
    fb_health_size_multiplier,
    fb_performance_snapshot,
    record_fb_sell_outcome,
)

_KST = ZoneInfo("Asia/Seoul")

# 테스트용 고정 시각(운영에서는 None)
_debug_now_kst: datetime | None = None


def _now_kst() -> datetime:
    if _debug_now_kst is not None:
        return _debug_now_kst
    return datetime.now(_KST)


def _fb_cooldown_detail(state: IntradayPaperState | None, carry: dict[str, Any] | None) -> dict[str, Any]:
    """쿨다운 잔여·사유(종목별)."""
    trace = (carry or {}).get("fb_cooldown_trace") or {}
    if state is None:
        return {"symbols": {}}
    now = datetime.now(timezone.utc)
    out: dict[str, dict[str, Any]] = {}
    for sym, iso in (state.cooldown_until_iso or {}).items():
        try:
            cd = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
            rem = max(0.0, (cd - now).total_seconds())
            active = rem > 0.5
        except ValueError:
            rem = 0.0
            active = False
        tr = trace.get(sym) or trace.get(str(sym)) or {}
        out[str(sym)] = {
            "cooldown_active": active,
            "cooldown_remaining_sec": round(rem, 3),
            "cooldown_reason": tr.get("cooldown_reason"),
        }
    return {"symbols": out}


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


def _morning_bars_atr_pct(morning_bars: pd.DataFrame, ref_px: float) -> float:
    """당일 오전 봉 기준 단기 ATR% (갭 손절 임계 완화에 사용)."""
    if morning_bars.empty or len(morning_bars) < 4 or ref_px <= 0:
        return 0.45
    mb = morning_bars.sort_values("date")
    h = mb["high"].astype(float)
    l = mb["low"].astype(float)
    c = mb["close"].astype(float)
    prev = c.shift(1)
    prev = prev.fillna(float(ref_px))
    tr = pd.concat([(h - l).abs(), (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    atr = float(tr.tail(min(10, len(tr))).mean())
    return (atr / ref_px) * 100.0


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


def _index_day_return_pct(df: pd.DataFrame) -> float | None:
    if df.empty:
        return None
    col = "close" if "close" in df.columns else ("value" if "value" in df.columns else None)
    if col is None:
        return None
    s = df.sort_values("date")[col].astype(float)
    if len(s) < 2:
        return None
    prev = float(s.iloc[-2])
    cur = float(s.iloc[-1])
    if prev <= 0:
        return None
    return float((cur / prev - 1.0) * 100.0)


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _pick_quote_number(qp: dict[str, Any], keys: tuple[str, ...], default: float = 0.0) -> float:
    for k in keys:
        if k in qp and qp.get(k) not in (None, ""):
            return _to_float(qp.get(k), default)
    return default


def _rank_from_quote(qp: dict[str, Any], keys: tuple[str, ...]) -> int:
    for k in keys:
        if k in qp and qp.get(k) not in (None, ""):
            return _to_int(qp.get(k), 9999)
    return 9999


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
    manual_override_enabled: bool = False
    timeframe_label: str = "1m"
    pending_carry_updates: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    _final_betting_equity_krw: float = 0.0

    def consume_pending_carry_update(self, symbol: str) -> dict[str, Any] | None:
        return self.pending_carry_updates.pop(symbol, None)

    def on_fb_sell_accepted(
        self,
        symbol: str,
        sold_qty: int,
        state: IntradayPaperState,
        *,
        order: OrderRequest | None = None,
        fill_result: OrderResult | None = None,
    ) -> None:
        cfg = get_settings()
        carry = state.final_betting_carry
        pos = carry.get("positions") or {}
        meta = pos.get(symbol)
        if not meta:
            return
        ref_close = float(meta.get("ref_close") or 0.0)
        before = int(meta.get("shares", 0))
        order_req_px = float(order.price) if order and order.price is not None else None
        broker_avg = (
            float(fill_result.avg_fill_price) if fill_result and fill_result.avg_fill_price is not None else None
        )
        if broker_avg is not None:
            fill_px = broker_avg
            pnl_src = "broker_avg_fill"
        elif order_req_px is not None:
            fill_px = order_req_px
            pnl_src = "order_request_price"
        else:
            fill_px = ref_close
            pnl_src = "reference_close_fallback"
        reason = str(order.signal_reason or "") if order else ""
        pnl_pct = (fill_px / ref_close - 1.0) * 100.0 if ref_close > 0 else 0.0
        sold_qty_i = int(sold_qty)
        record_fb_sell_outcome(
            carry,
            symbol=str(symbol),
            sold_qty=sold_qty_i,
            fill_px=fill_px,
            entry_px=ref_close,
            reason=reason,
            reference_close=ref_close,
            order_request_price=order_req_px,
            executed_avg_fill_price=broker_avg,
            pnl_price_source=pnl_src,
        )
        left = before - sold_qty_i
        if left <= 0:
            pos.pop(symbol, None)
            carry["positions"] = pos
            carry.setdefault("last_exit_kst", {})[symbol] = _now_kst().strftime("%Y%m%d")
        else:
            meta["shares"] = left
            if sold_qty_i < before:
                meta["partial_scaleout_done"] = True
            pos[symbol] = meta
            carry["positions"] = pos
        if order is not None:
            apply_fb_dynamic_cooldown(
                cfg=cfg,
                state=state,
                carry=carry,
                symbol=str(symbol),
                reason=reason,
                pnl_pct=pnl_pct,
                today_kst=_now_kst().strftime("%Y%m%d"),
            )
        carry.setdefault("fb_last_sell_price_diag", {})[str(symbol)] = {
            "reference_close": ref_close,
            "order_request_price": order_req_px,
            "executed_avg_fill_price": broker_avg,
            "pnl_price_used": fill_px,
            "pnl_price_source": pnl_src,
        }

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
        t_entry1 = parse_krx_hhmm(cfg.paper_final_betting_entry_end_hhmm, default=time(15, 20))
        t_exit0 = parse_krx_hhmm(cfg.paper_krx_regular_open_hhmm, default=time(9, 0))
        t_exit1 = parse_krx_hhmm(cfg.paper_final_betting_exit_deadline_hhmm, default=time(11, 0))

        regime = classify_market_regime(
            MarketRegimeInputs(
                kospi=context.kospi_index,
                sp500=context.sp500_index,
                volatility=context.volatility_index,
            ),
            self.regime_config,
        )
        soft = compute_soft_regime(regime.features, regime.regime)

        kospi_day_ret = _index_day_return_pct(context.kospi_index)
        # 현 코드베이스에는 CME 나스닥100 야간선물 전용 feed가 없어 SP500 proxy를 우선 사용.
        us_night_proxy_ret = _index_day_return_pct(context.sp500_index)
        market_filter_ready = us_night_proxy_ret is not None
        market_filter_ok = bool(market_filter_ready and us_night_proxy_ret >= 0.8 and (kospi_day_ret is None or kospi_day_ret > -1.0))
        market_filter_ok_effective = market_filter_ok
        if (
            not market_filter_ok_effective
            and market_filter_ready
            and us_night_proxy_ret is not None
            and soft.market_regime in ("neutral", "mild_bullish", "mild_bearish")
        ):
            market_filter_ok_effective = bool(us_night_proxy_ret >= 0.4 and (kospi_day_ret is None or kospi_day_ret > -1.35))
        self.last_intraday_signal_breakdown["market_filter"] = {
            "us_night_proxy_ret_pct": us_night_proxy_ret,
            "kospi_day_ret_pct": kospi_day_ret,
            "market_filter_ready": market_filter_ready,
            "market_filter_ok": market_filter_ok,
            "market_filter_ok_effective": market_filter_ok_effective,
            "rule": "us_night_proxy>=+0.8 and kospi>-1.0",
            "rule_soft": "neutral/mild: us>=0.4 and kospi>-1.35",
        }
        self.last_intraday_signal_breakdown["market_regime"] = soft.market_regime
        self.last_intraday_signal_breakdown["regime_score"] = soft.regime_score
        self.last_intraday_signal_breakdown["regime_entry_allowed"] = soft.regime_entry_allowed
        self.last_intraday_signal_breakdown["regime_size_multiplier"] = soft.regime_size_multiplier
        self.last_intraday_signal_breakdown["regime_block_reason"] = soft.regime_block_reason

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

        kospi_day_ret_for_rel = float(kospi_day_ret or 0.0)

        # --- overnight exits (다음 거래일 오전) ---
        carry = st.final_betting_carry
        fb_positions: dict[str, Any] = dict(carry.get("positions") or {})
        tv_hist: dict[str, list[float]] = dict(carry.get("tv_history") or {})
        tv_hist_day: dict[str, str] = dict(carry.get("tv_history_day") or {})
        loss_days: list[str] = list(carry.get("loss_days") or [])
        rest_until = str(carry.get("rest_until_kst_date") or "")
        self.last_intraday_signal_breakdown["loss_days"] = list(loss_days)
        self.last_intraday_signal_breakdown["rest_until_kst_date"] = rest_until
        self.last_intraday_signal_breakdown["fb_performance"] = fb_performance_snapshot(carry)
        _health_lbl, health_mult = fb_health_size_multiplier(carry)
        self.last_intraday_signal_breakdown["strategy_health"] = _health_lbl
        self.last_intraday_signal_breakdown["health_position_size_mult"] = health_mult
        _meta_fb = carry.get("fb_intraday_meta") or {}
        self.last_intraday_signal_breakdown["symbol_stopout_count_today"] = dict(_meta_fb.get("stopout_counts") or {})
        scale_start = time(9, 5)
        scale_end = time(9, 30)

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
                m_atr_pct = _morning_bars_atr_pct(morning_bars, ref_close)
                # 갭 손절: 고정 -0.5%는 휩소에 취약 → ATR 반영 + 장 초반 유예(아주 큰 갭만 즉시)
                gap_thr = -max(0.68, min(1.22, 0.52 + 0.11 * max(0.0, m_atr_pct)))
                gap_immediate = gap_pct <= -1.18
                gap_delayed_ok = now.time() >= time(9, 10) and gap_pct <= gap_thr
                morning_weak = (
                    not morning_bars.empty
                    and now.time() >= time(9, 12)
                    and now.time() < time(10, 0)
                    and last_px < avg * 0.9905
                    and last_px < open_px * 0.996
                )
                if gap_immediate or gap_delayed_ok:
                    exit_reason = "gap_down_stop_atr_delayed"
                elif morning_weak:
                    exit_reason = "weak_morning_flush_fast_stop"
                elif scale_start <= now.time() <= scale_end and gap_pct > 0.0:
                    exit_reason = "gap_up_take_profit"
                elif now.time() >= time(10, 0) and last_px < avg * 1.01:
                    exit_reason = "time_value_exit_1000"
                elif exit_reason is None and now.time() >= t_exit1:
                    exit_reason = "hard_exit_1100"

            if exit_reason:
                self.last_intraday_signal_breakdown["exits_evaluated"] = (
                    int(self.last_intraday_signal_breakdown.get("exits_evaluated") or 0) + 1
                )
                if is_carry_overnight and int(min(qty, exit_qty)) >= int(qty):
                    pnl_pct = (last_px / avg - 1.0) * 100.0 if avg > 0 else 0.0
                    if pnl_pct < 0:
                        if today not in loss_days:
                            loss_days.append(today)
                            loss_days = sorted(loss_days)[-2:]
                            carry["loss_days"] = loss_days
                    else:
                        carry["loss_days"] = []
                        loss_days = []
                    if len(loss_days) >= 2:
                        try:
                            ny = (datetime.strptime(today, "%Y%m%d").date()).toordinal() + 1
                            carry["rest_until_kst_date"] = datetime.fromordinal(ny).strftime("%Y%m%d")
                        except ValueError:
                            carry["rest_until_kst_date"] = today
                self.last_intraday_signal_breakdown.setdefault("final_betting_exit_intents", []).append(
                    {
                        "symbol": sym,
                        "final_betting_exit_reason": exit_reason,
                        "final_betting_nextday_gap_mode": "atr_scaled",
                    }
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
        if rest_until and rest_until >= today:
            self.last_intraday_signal_breakdown["blocked"] = "two_loss_days_rest"
            self.last_intraday_signal_breakdown["rest_until_kst_date"] = rest_until
            return signals
        if not market_filter_ok_effective:
            self.last_intraday_signal_breakdown["blocked"] = "market_filter_blocked_1430"
            return signals
        # 신규 진입: soft 국면 entry_allowed + (고변동 레거시는 compute_soft_regime 에서 이미 차단).
        soft_regime_gate_ok = bool(soft.regime_entry_allowed) or bool(self.manual_override_enabled)
        self.last_intraday_signal_breakdown["soft_regime_used_as_gate"] = True
        self.last_intraday_signal_breakdown["regime_gate_decision"] = "allowed" if soft_regime_gate_ok else "blocked"
        if not soft_regime_gate_ok:
            self.last_intraday_signal_breakdown["blocked"] = "soft_regime_entry_not_allowed"
            return signals
        # 지수 필터: KOSPI 수익률이 음수이고 5일 EMA 아래면 보수화(신규 진입 중단).
        if not context.kospi_index.empty and "close" in context.kospi_index.columns:
            kclose = context.kospi_index.sort_values("date")["close"].astype(float)
            if len(kclose) >= 6:
                ema5 = _ema(kclose, 5)
                if (not self.manual_override_enabled) and float(kclose.iloc[-1]) < float(ema5.iloc[-1]) and kospi_day_ret_for_rel <= -0.35:
                    self.last_intraday_signal_breakdown["blocked"] = "index_filter_risk_off"
                    return signals
        if not in_entry_window:
            return signals

        open_slots = max(0, int(cfg.paper_final_betting_max_new_positions) - len(pos_symbols))
        entered_today = list(carry.get("entered_symbols_today") or [])
        if open_slots <= 0:
            self.last_intraday_signal_breakdown["blocked"] = "max_open_positions"
            return signals

        eq_fb = float(getattr(self, "_final_betting_equity_krw", 0.0) or 0.0)
        max_overnight_pct = float(getattr(cfg, "paper_final_betting_max_overnight_equity_pct", 0.0) or 0.0)
        if max_overnight_pct > 0 and eq_fb > 0:
            fb_on = 0.0
            for sym_fb, meta in (fb_positions or {}).items():
                if sym_fb not in pos_symbols:
                    continue
                q_, av_ = pos_symbols[sym_fb]
                if int(q_) <= 0:
                    continue
                fb_on += float(q_) * float(av_)
            on_pct = (fb_on / eq_fb) * 100.0
            self.last_intraday_signal_breakdown["final_betting_overnight_exposure_pct"] = round(float(on_pct), 4)
            if on_pct >= max_overnight_pct - 1e-9:
                self.last_intraday_signal_breakdown["blocked"] = "max_overnight_equity_pct"
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
            self.last_intraday_signal_breakdown["raw_universe_count"] = int(prices["symbol"].nunique())
        else:
            self.last_intraday_signal_breakdown["raw_universe_count"] = 0

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

                late_tail = _bars_between_times(sub_s, session_ymd, time(14, 25), time(15, 20))
                if not late_tail.empty and len(late_tail) >= 2:
                    hi_roll = float(late_tail["high"].max())
                    last_c2 = float(late_tail["close"].iloc[-1])
                    plunge_pct = ((hi_roll - last_c2) / hi_roll * 100.0) if hi_roll > 0 else 0.0
                    if plunge_pct >= 2.85:
                        self.last_diagnostics.append(
                            {
                                "symbol": sym,
                                "strategy": "final_betting_v1",
                                "entered": False,
                                "blocked_reason": "late_session_plunge_from_intraday_high",
                                "late_plunge_pct_from_high": round(plunge_pct, 4),
                                "morning_accumulation_score": 0.0,
                                "distribution_unfinished_score": 0.0,
                                "close_strength_score": 0.0,
                                "score_breakdown": {"late_tail_bars": int(len(late_tail)), "hi_roll": hi_roll, "last_close": last_c2},
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
                ma20 = _ema(close_s, 20)
                ma20_last = float(ma20.iloc[-1]) if len(ma20) else last_close
                ma20_prev = float(ma20.iloc[-2]) if len(ma20) >= 2 else ma20_last
                rsi14 = _rsi14(close_s)
                ma5_ok = ma5_last > 0 and last_close > ma5_last
                ma20_up = ma20_last >= ma20_prev
                flow_score, flow_ok = _flow_proxy_score(sub_s, session_ymd, day_vwap_last)
                auction_instability = _auction_instability_score(sub_s, session_ymd)
                if auction_instability >= 1.8:
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
                rel_score, rel_ok = _relative_strength_ok(sym, sub_s, kospi_day_ret_for_rel, cohort_tv, min_tv)

                day_open = float(sub_s.sort_values("date")["open"].iloc[0])
                day_ret_pct = (last_close / day_open - 1.0) * 100.0 if day_open > 0 else 0.0
                day_ret_ok = 0.0 <= day_ret_pct <= 7.0
                rng = max(day_hi - day_lo, 1e-9)
                body = abs(last_close - day_open)
                long_bull_today = last_close > day_open and body / rng >= 0.45
                daily_ohlc = build_daily_ohlc_from_intraday(sub)
                atr14, atr_pct, atr_fallback = daily_atr14_pct(daily_ohlc)
                rebound_info = evaluate_bearish_rebound_candidate(
                    sub_s=sub_s,
                    day_open=day_open,
                    day_hi=day_hi,
                    day_lo=day_lo,
                    last_close=last_close,
                    rsi14=rsi14,
                    ma20_last=ma20_last,
                    ma20_prev=ma20_prev,
                    morning=morning,
                    afternoon=afternoon,
                    kospi_day_ret=kospi_day_ret_for_rel,
                )
                rmin = float(cfg.paper_final_betting_rebound_score_min)
                entry_rebound_core = (
                    bool(rebound_info.get("bearish_rebound_candidate"))
                    and float(rebound_info.get("final_betting_quality_score", 0)) >= rmin
                    and not bool(rebound_info.get("panic_candle"))
                    and (
                        soft.market_regime != "bearish"
                        or float(rebound_info.get("final_betting_reversal_score", 0)) >= 0.62
                    )
                )
                day_ret_ok_eff = bool(day_ret_ok) or (
                    entry_rebound_core and -1.2 <= float(day_ret_pct) <= 2.8
                )
                ma5_ok_eff = bool(ma5_ok) or bool(entry_rebound_core and last_close >= ma5_last * 0.994)
                patt_b = str(rebound_info.get("final_betting_bearish_close_pattern") or "") == "pattern_B"
                ma20_up_eff = bool(ma20_up) or bool(entry_rebound_core and patt_b)
                candle_ok = bool(long_bull_today) or bool(entry_rebound_core)
                qp_rank_foreign = _rank_from_quote(
                    qp,
                    ("frgn_ntby_rank", "foreign_net_buy_rank", "frgn_buy_rank", "foreign_rank"),
                )
                qp_rank_inst = _rank_from_quote(
                    qp,
                    ("orgn_ntby_rank", "inst_net_buy_rank", "institution_rank", "organ_rank"),
                )
                net_buy_rank_ok = (qp_rank_foreign <= 20) or (qp_rank_inst <= 20) or flow_ok
                market_cap = _pick_quote_number(
                    qp,
                    ("market_cap", "market_cap_krw", "stck_avls", "stck_prpr_mktcp", "stck_fcam"),
                    0.0,
                )
                market_cap_ok = market_cap <= 0.0 or market_cap >= 50_000_000_000.0

                # 기존 게이트보다 완화: 요청한 룰 핵심만 남기고 과도한 보조 게이트 제거.
                hits = sum([m_ok, a_ok, close_above, in_high_zone, rel_ok])
                close_strength = (
                    0.25 * (1.0 if close_above else 0.0)
                    + 0.25 * (1.0 if in_high_zone else 0.0)
                    + 0.25 * min(1.0, max(0.0, (last_close - day_lo) / max(day_hi - day_lo, 1e-9)))
                    + 0.25 * rel_score
                )
                hits_eff = int(hits) + (1 if entry_rebound_core and m_ok else 0)
                blocked = ""
                tv_sym = float(liq["acml_tr_pbmn"]) if liq else 0.0
                trade_value_ok = tv_sym >= 10_000_000_000.0
                if tv_hist_day.get(sym) != today and tv_sym > 0:
                    hist = list(tv_hist.get(sym) or [])
                    hist.append(tv_sym)
                    tv_hist[sym] = hist[-5:]
                    tv_hist_day[sym] = today
                avg5 = sum(tv_hist.get(sym) or []) / max(1, len(tv_hist.get(sym) or []))
                tv_spike_ok = avg5 <= 0 or tv_sym >= avg5 * 2.0
                weak_rsi_max = float(getattr(cfg, "paper_final_betting_weak_close_rsi_max", 74.0))
                net_buy_rank_ok_eff = bool(net_buy_rank_ok) or bool(entry_rebound_core and flow_ok)
                if rsi14 >= weak_rsi_max and not entry_rebound_core:
                    blocked = "weak_close_rsi_high"
                elif not net_buy_rank_ok_eff:
                    blocked = "net_buy_rank_or_flow_fail"
                elif not ma5_ok_eff:
                    blocked = "close_below_ma5"
                elif not ma20_up_eff:
                    blocked = "ma20_not_rising"
                elif not trade_value_ok:
                    blocked = "trade_value_lt_100eok"
                elif not market_cap_ok:
                    blocked = "market_cap_lt_500eok"
                elif not day_ret_ok_eff:
                    blocked = "day_return_out_of_range"
                elif not candle_ok:
                    blocked = "candle_pattern_fail"
                elif hits_eff < 2 and not flow_ok and not entry_rebound_core:
                    blocked = "signals_weak"
                elif not tv_spike_ok and hits_eff < 3 and not entry_rebound_core:
                    blocked = "trade_value_not_2x_avg5"
                eff_sl_blk, eff_tp_blk, atr_blend_blk = blend_stop_tp_with_atr(
                    fixed_stop_pct=float(cfg.paper_final_betting_stop_loss_pct),
                    fixed_tp_pct=float(cfg.paper_final_betting_target_pct),
                    atr_pct=float(atr_pct),
                    atr_stop_mult=float(getattr(cfg, "paper_final_betting_atr_stop_mult", 1.0)),
                    atr_tp_mult=float(getattr(cfg, "paper_final_betting_atr_tp_mult", 1.0)),
                )
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
                            "ma5_ok": bool(ma5_ok),
                            "ma20_up": bool(ma20_up),
                            "rsi14": round(rsi14, 3),
                            "net_buy_rank_ok": bool(net_buy_rank_ok),
                            "foreign_rank": int(qp_rank_foreign),
                            "institution_rank": int(qp_rank_inst),
                            "day_ret_pct": round(day_ret_pct, 4),
                            "candle_ok": bool(candle_ok),
                            "flow_proxy_score": round(flow_score, 4),
                            "flow_proxy_ok": bool(flow_ok),
                            "trade_value_today": round(tv_sym, 2),
                            "trade_value_avg5": round(avg5, 2),
                            "trade_value_spike_ok": bool(tv_spike_ok),
                            "final_betting_rank": None,
                            "atr14": round(float(atr14), 6),
                            "atr_pct": round(float(atr_pct), 4),
                            "atr_fallback_used": bool(atr_fallback or atr_blend_blk),
                            "exit_mode": "atr_blended" if not atr_blend_blk else "atr_fallback_fixed",
                            "effective_stop_pct": round(float(eff_sl_blk), 4),
                            "effective_take_profit_pct": round(float(eff_tp_blk), 4),
                            "entry_rebound_core": bool(entry_rebound_core),
                            "final_betting_rebound_candidate": bool(rebound_info.get("bearish_rebound_candidate")),
                            **{k: v for k, v in rebound_info.items() if isinstance(k, str)},
                        }
                    )
                    continue

                foreign_amt = _pick_quote_number(
                    qp,
                    ("frgn_ntby_amt", "foreign_net_buy_amount", "frgn_buy_amt", "frgn_ntby_tr_pbmn"),
                    0.0,
                )
                inst_amt = _pick_quote_number(
                    qp,
                    ("orgn_ntby_amt", "inst_net_buy_amount", "organ_buy_amt", "orgn_ntby_tr_pbmn"),
                    0.0,
                )
                net_buy_amt = max(0.0, foreign_amt) + max(0.0, inst_amt)

                ranked.append(
                    (
                        net_buy_amt if net_buy_amt > 0 else tv_sym,
                        sym,
                        {
                            "m": m_score,
                            "a": a_score,
                            "cs": float(close_strength),
                            "hits": hits,
                            "rsi14": rsi14,
                            "flow_proxy_score": flow_score,
                            "avg5": avg5,
                            "net_buy_amt": net_buy_amt,
                            "rebound_entry": bool(entry_rebound_core),
                            "rebound_info": rebound_info,
                        },
                    )
                )

        ranked.sort(key=lambda x: -x[0])
        pool_n = max(3, int(getattr(cfg, "paper_final_betting_rank_pool_top_n", 5)))
        self.last_intraday_signal_breakdown["filtered_universe_count"] = len(ranked)
        self.last_intraday_signal_breakdown["ranking_cutoff_used"] = int(pool_n)
        self.last_intraday_signal_breakdown["universe_filter_block_reason"] = (
            None if len(ranked) > 0 else "no_candidates_passed_gates"
        )
        entries_added = 0
        for rank_i, (_rank_score, sym, _sc_pack) in enumerate(ranked[:pool_n]):
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
            rel_score, rel_ok = _relative_strength_ok(sym, sub_s, kospi_day_ret_for_rel, cohort_tv, min_tv)
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

            eq_base = float(getattr(self, "_final_betting_equity_krw", 0.0) or 0.0)
            eq = max(1.0, eq_base * float(soft.regime_size_multiplier) * float(health_mult))
            min_pct = float(getattr(cfg, "paper_final_betting_min_allocation_pct", 20.0))
            max_pct = float(cfg.paper_final_betting_max_capital_per_position_pct)
            px = float(last_close)
            daily_ohlc2 = build_daily_ohlc_from_intraday(sub)
            atr14_2, atr_pct_2, atr_fb2 = daily_atr14_pct(daily_ohlc2)
            eff_sl, eff_tp, atr_blend_fb = blend_stop_tp_with_atr(
                fixed_stop_pct=float(cfg.paper_final_betting_stop_loss_pct),
                fixed_tp_pct=float(cfg.paper_final_betting_target_pct),
                atr_pct=float(atr_pct_2),
                atr_stop_mult=float(getattr(cfg, "paper_final_betting_atr_stop_mult", 1.0)),
                atr_tp_mult=float(getattr(cfg, "paper_final_betting_atr_tp_mult", 1.0)),
            )
            # `compute_intraday_buy_quantity` defaults max_shares_cap=500; that cap is for generic
            # paper paths. Here feasible = min(risk, position-cap) must not be artifically limited
            # below min-allocation share count (paper_final_betting_min_allocation_pct).
            q_cap_sh = max(1, int((eq * (max_pct / 100.0)) / max(px, 1e-9))) if eq > 0 else 1
            risk_q = compute_intraday_buy_quantity(
                price_krw=px,
                stop_loss_pct_points=float(eff_sl),
                equity_krw=eq,
                intraday_budget_krw=max(eq, 1.0),
                max_position_pct=max_pct,
                risk_per_trade_pct=min(float(cfg.paper_risk_per_trade_pct), float(eff_sl)),
                fallback_qty=1,
                max_shares_cap=q_cap_sh,
            )
            q_risk = int(risk_q)
            q_min = max(1, int((eq * (min_pct / 100.0)) / max(px, 1e-9))) if eq > 0 else 1
            feasible = min(q_risk, q_cap_sh)
            alloc_diag: dict[str, Any] = {
                "final_betting_min_allocation_pct": min_pct,
                "final_betting_max_capital_per_position_pct": max_pct,
                "final_betting_q_min_for_min_alloc": int(q_min),
                "final_betting_q_risk": int(q_risk),
                "final_betting_q_cap_shares": int(q_cap_sh),
                "final_betting_feasible_shares": int(feasible),
            }
            if max_pct + 1e-9 < min_pct:
                diag = {
                    "symbol": sym,
                    "strategy": "final_betting_v1",
                    "entered": False,
                    "blocked_reason": "config_max_pct_lt_min_allocation",
                    **alloc_diag,
                }
                self.last_diagnostics.append(diag)
                continue
            if feasible < q_min:
                diag = {
                    "symbol": sym,
                    "strategy": "final_betting_v1",
                    "entered": False,
                    "blocked_reason": "insufficient_budget_for_min_allocation",
                    "final_betting_allocation_blocked_reason": "risk_or_cap_below_min_shares",
                    **alloc_diag,
                }
                self.last_diagnostics.append(diag)
                continue
            q = int(feasible)
            notional_pct = (q * px / eq * 100.0) if eq > 0 else 0.0
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
                    stop_loss_pct=float(eff_sl),
                    reason="final_betting_v1_entry",
                    strategy_name="final_betting_v1",
                )
            )
            ri = _sc_pack.get("rebound_info") or {}
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
                "final_betting_allocation_pct_equity": round(float(notional_pct), 3),
                "final_betting_min_allocation_pct": min_pct,
                "atr14": round(float(atr14_2), 6),
                "atr_pct": round(float(atr_pct_2), 4),
                "atr_fallback_used": bool(atr_fb2 or atr_blend_fb),
                "effective_stop_pct": round(float(eff_sl), 4),
                "effective_take_profit_pct": round(float(eff_tp), 4),
                "exit_mode": "atr_blended" if not atr_blend_fb else "atr_fallback_fixed",
                "final_betting_entry_aggressive": bool(_sc_pack.get("rebound_entry")),
                "final_betting_rebound_candidate": bool((ri or {}).get("bearish_rebound_candidate")),
                "final_betting_position_alloc_pct": round(float(notional_pct), 3),
                "final_betting_nextday_gap_mode": "atr_scaled",
                **alloc_diag,
                **{k: v for k, v in ri.items() if isinstance(k, str)},
            }
            self.last_diagnostics.append(diag)
            entries_added += 1

        carry["tv_history"] = tv_hist
        carry["tv_history_day"] = tv_hist_day

        self.last_intraday_signal_breakdown["cooldown_diagnostics"] = _fb_cooldown_detail(st, carry)
        return signals


def set_final_betting_debug_now(dt: datetime | None) -> None:
    """테스트에서 KST '현재' 시각을 고정할 때 사용. 운영에서는 None."""
    global _debug_now_kst
    _debug_now_kst = dt
