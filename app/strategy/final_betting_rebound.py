"""final_betting_v1 — 베어리시 마감 후 익일 반등 후보 패턴 (A/B/C). '낙착칼' 매수 금지: 품질·유동성·패닉 캔들 제외."""

from __future__ import annotations

from typing import Any

import pandas as pd


def daily_atr14_pct(daily_ohlc: pd.DataFrame) -> tuple[float, float, bool]:
    """
    일봉 OHLC(컬럼: high, low, close) 최소 15행 가정.
    반환: (atr14 절대값, atr_pct=atr/close*100, fallback_used)
    """
    if daily_ohlc is None or len(daily_ohlc) < 15:
        return 0.0, 1.5, True
    h = daily_ohlc["high"].astype(float)
    l = daily_ohlc["low"].astype(float)
    c = daily_ohlc["close"].astype(float)
    prev = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    atr = float(tr.tail(14).mean())
    last = float(c.iloc[-1])
    if last <= 0:
        return atr, 1.5, True
    pct = (atr / last) * 100.0
    return atr, float(pct), False


def build_daily_ohlc_from_intraday(sub: pd.DataFrame) -> pd.DataFrame:
    """분봉 유니버스에서 일봉 OHLC 집계."""
    if sub.empty or "date" not in sub.columns:
        return pd.DataFrame(columns=["high", "low", "close"])
    d = sub.copy()
    d["_d"] = pd.to_datetime(d["date"]).dt.date
    g = d.groupby("_d", sort=True).agg(
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        open=("open", "first"),
        volume=("volume", "sum"),
    )
    return g.tail(60)


def evaluate_bearish_rebound_candidate(
    *,
    sub_s: pd.DataFrame,
    day_open: float,
    day_hi: float,
    day_lo: float,
    last_close: float,
    rsi14: float,
    ma20_last: float,
    ma20_prev: float,
    morning: pd.DataFrame,
    afternoon: pd.DataFrame,
    kospi_day_ret: float,
) -> dict[str, Any]:
    """
    패턴 A: 베어 캔들 + 하단부 마감(극단 붕괴 아님) + RSI 과매도권
    패턴 B: 조정 후 베어일 + MA20 우상향 유지
    패턴 C: 장중 저점 대비 종가 회복(레이트 리커버리)
    """
    rng = max(day_hi - day_lo, 1e-9)
    body = abs(last_close - day_open)
    bearish = last_close < day_open
    pos_in_range = (last_close - day_lo) / rng
    panic_long_red = bearish and (body / rng) >= 0.78 and last_close <= day_lo + rng * 0.12

    vol_ok = True
    if len(sub_s) >= 10:
        v = sub_s["volume"].astype(float).tail(120)
        if len(v) >= 6:
            vol_ok = float(v.iloc[-6:].mean()) >= float(v.iloc[-30:-6].mean()) * 0.55 if len(v) >= 30 else True

    # Pattern A
    pa = (
        bearish
        and 0.08 <= pos_in_range <= 0.48
        and rsi14 <= 46.0
        and not panic_long_red
        and vol_ok
    )
    score_a = 0.0
    if bearish:
        score_a = 0.35 * (1.0 if 0.1 <= pos_in_range <= 0.45 else 0.4)
        score_a += 0.3 * (1.0 if rsi14 <= 42 else 0.5 if rsi14 <= 48 else 0.0)
        score_a += 0.2 * (1.0 if not panic_long_red else 0.0)
        score_a += 0.15 * (1.0 if vol_ok else 0.3)

    # Pattern B: uptrend pullback bear day
    uptrend_ma = ma20_last >= ma20_prev * 1.001 and last_close > ma20_last * 0.97
    pb = bearish and uptrend_ma and kospi_day_ret > -1.2
    score_b = 0.0
    if pb:
        score_b = 0.45 + 0.25 * min(1.0, (last_close / ma20_last) - 0.98) * 50.0
        score_b += 0.3 * (1.0 if rsi14 <= 55 else 0.4)

    # Pattern C: recovery from intraday low
    late_recov = False
    if not morning.empty and day_hi > day_lo:
        m_lo = float(morning["low"].min())
        rec = (last_close - m_lo) / max(day_hi - m_lo, 1e-9)
        late_recov = rec >= 0.35 and last_close > m_lo * 1.002
    pc = bearish and late_recov and not panic_long_red
    score_c = 0.5 + 0.5 * min(1.0, (last_close - day_lo) / rng) if pc else 0.0

    patterns = [("A", pa, score_a), ("B", pb, score_b), ("C", pc, score_c)]
    best = max(patterns, key=lambda x: x[2])
    pname, ok, sc = best
    reversal_score = float(max(score_a, score_b, score_c))
    quality_score = min(
        1.0,
        0.4 * (1.0 if not panic_long_red else 0.0)
        + 0.3 * (1.0 if vol_ok else 0.2)
        + 0.3 * min(1.0, reversal_score),
    )
    final_betting_score = round(0.5 * float(quality_score) + 0.5 * min(1.0, float(reversal_score)), 4)

    block = ""
    if panic_long_red:
        block = "panic_crash_candle"
    elif not bearish:
        block = "not_bearish_candle"
    elif reversal_score < 0.35:
        block = "reversal_score_low"

    return {
        "bearish_rebound_candidate": bool(ok or reversal_score >= 0.45) and not panic_long_red and bearish,
        "final_betting_bearish_close_pattern": f"pattern_{pname}" if ok else "none",
        "final_betting_reversal_score": round(reversal_score, 4),
        "final_betting_quality_score": round(quality_score, 4),
        "final_betting_score": final_betting_score,
        "final_betting_rebound_block_reason": block or None,
        "final_betting_block_reason": block or None,
        "pattern_scores": {"A": round(score_a, 4), "B": round(score_b, 4), "C": round(score_c, 4)},
        "panic_candle": bool(panic_long_red),
    }


def blend_stop_tp_with_atr(
    *,
    fixed_stop_pct: float,
    fixed_tp_pct: float,
    atr_pct: float,
    atr_stop_mult: float,
    atr_tp_mult: float,
) -> tuple[float, float, bool]:
    """고정 % 와 ATR% 혼합. atr_pct 신뢰 불가 시 fallback."""
    if atr_pct <= 0 or atr_pct > 25.0:
        return fixed_stop_pct, fixed_tp_pct, True
    dyn_stop = max(fixed_stop_pct * 0.65, min(fixed_stop_pct * 1.35, atr_pct * atr_stop_mult))
    dyn_tp = max(fixed_tp_pct * 0.7, min(fixed_tp_pct * 1.45, atr_pct * atr_tp_mult * 1.15))
    return float(dyn_stop), float(dyn_tp), False
