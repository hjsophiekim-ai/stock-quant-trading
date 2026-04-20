"""Momentum continuation entry path for `scalp_rsi_flag_hf_v1` (trend-following, not reversal-only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.strategy.intraday_common import ema, rsi_wilder, session_vwap
from app.strategy.rsi_flag_helpers import rsi_hf_volume_confirmation


def _bar_body_ratio(close: float, open_: float, high: float, low: float) -> float:
    rng = max(high - low, 1e-9)
    return abs(close - open_) / rng


def _close_in_range_pct(close: float, high: float, low: float) -> float:
    rng = max(high - low, 1e-9)
    return (close - low) / rng


def momentum_blow_off_guard(sub: pd.DataFrame) -> tuple[bool, str]:
    """
    Block obvious vertical / exhaustion spikes (not a full TA suite — execution guard).
    Returns (blocked, detail).
    """
    if sub is None or sub.empty or len(sub) < 6:
        return False, ""
    s = sub.sort_values("date")
    close = s["close"].astype(float)
    open_ = s["open"].astype(float)
    high = s["high"].astype(float)
    low = s["low"].astype(float)
    rsi14 = rsi_wilder(close, 14)
    r14 = float(rsi14.iloc[-1]) if len(rsi14) else 50.0
    last_c = float(close.iloc[-1])
    last_o = float(open_.iloc[-1])
    last_h = float(high.iloc[-1])
    last_l = float(low.iloc[-1])
    br = _bar_body_ratio(last_c, last_o, last_h, last_l)
    pos = _close_in_range_pct(last_c, last_h, last_l)
    last_rng_pct = (last_h - last_l) / max(last_c, 1e-9) * 100.0
    day_open = float(open_.iloc[0])
    day_hi = float(high.max())
    day_ret = (last_c / max(day_open, 1e-9) - 1.0) * 100.0 if day_open > 0 else 0.0
    ext_from_hi = (day_hi - last_c) / max(last_c, 1e-9) * 100.0

    if last_rng_pct >= 2.0 and br >= 0.72 and pos >= 0.86:
        return True, "blowoff_single_bar_vertical_spike"

    if br >= 0.82 and pos >= 0.92 and r14 >= 76.0:
        return True, "blowoff_body_near_high_rsi_hot"
    if day_ret >= 8.5 and br >= 0.78 and pos >= 0.88:
        return True, "blowoff_extended_day_vertical"
    if ext_from_hi <= 0.06 and br >= 0.8 and r14 >= 74.0:
        return True, "blowoff_session_high_exhaustion"
    return False, ""


def momentum_late_vertical_spike(sub: pd.DataFrame) -> tuple[bool, str]:
    """Last 2 bars unusually wide vs price — late chase risk."""
    if sub is None or sub.empty or len(sub) < 3:
        return False, ""
    s = sub.sort_values("date")
    high = s["high"].astype(float)
    low = s["low"].astype(float)
    close = s["close"].astype(float)
    h2 = float(high.iloc[-2:].max())
    l2 = float(low.iloc[-2:].min())
    px = max(float(close.iloc[-1]), 1e-9)
    rng_pct = (h2 - l2) / px * 100.0
    if rng_pct >= 2.2 and float(close.iloc[-1]) >= float(close.iloc[-2]):
        return True, f"late_wide_two_bar_rng_pct={rng_pct:.2f}"
    return False, ""


def evaluate_momentum_continuation_entry(
    sub: pd.DataFrame,
    *,
    min_hits: int,
    min_hits_late_session: int,
    minutes_since_open: float,
    late_open_minutes: float,
    volume_z_floor: float,
    volume_ratio_floor: float,
    is_leader: bool,
) -> dict[str, Any]:
    """
    Trend-following continuation: VWAP discipline + shallow pullback + EMA stack + structure + RSI band.
    Volume gate uses adaptive floors from the caller; trend-quality for volume relaxation uses structural hits.
    """
    out: dict[str, Any] = {
        "momentum_continuation_ok": False,
        "momentum_continuation_reason": "",
        "momentum_path_hits": 0,
        "momentum_paths_detail": "",
        "trend_strength_score": 0.0,
        "continuation_quality_score": 0.0,
    }
    if sub is None or sub.empty or len(sub) < 28:
        out["momentum_continuation_reason"] = "insufficient_bars"
        return out

    blow, blow_d = momentum_blow_off_guard(sub)
    if blow:
        out["momentum_continuation_reason"] = blow_d
        return out
    lv, lv_d = momentum_late_vertical_spike(sub)
    if lv:
        out["momentum_continuation_reason"] = lv_d
        return out

    s = sub.sort_values("date")
    close = s["close"].astype(float)
    open_ = s["open"].astype(float)
    high = s["high"].astype(float)
    low = s["low"].astype(float)
    vw = session_vwap(s)
    rsi7 = rsi_wilder(close, 7)
    rsi14 = rsi_wilder(close, 14)
    ema8 = ema(close, 8)
    ema20 = ema(close, 20)

    last_c = float(close.iloc[-1])
    last_l = float(low.iloc[-1])
    last_h = float(high.iloc[-1])
    vwap_last = float(vw.iloc[-1]) if len(vw) else last_c
    r7 = float(rsi7.iloc[-1]) if len(rsi7) else 50.0
    r7p = float(rsi7.iloc[-2]) if len(rsi7) >= 2 else r7
    r14 = float(rsi14.iloc[-1]) if len(rsi14) else 50.0

    e8 = float(ema8.iloc[-1]) if len(ema8) else last_c
    e20 = float(ema20.iloc[-1]) if len(ema20) else last_c
    e20_lag = float(ema20.iloc[-4]) if len(ema20) >= 5 else e20

    # H1: VWAP + micro pullback / reclaim (last 4 bars touched VWAP zone then closed above)
    tail_lo = float(low.iloc[-4:].min())
    h1 = bool(last_c >= vwap_last * 1.0002 and tail_lo <= vwap_last * 1.004)

    # H2: short EMA stack bullish + EMA20 not rolling over
    h2 = bool(e8 >= e20 * 1.0003 and e20 >= e20_lag * 0.9992)

    # H3: breakout / near session highs (leader participation)
    prior_hi = float(high.iloc[-9:-1].max()) if len(high) >= 10 else last_h
    h3 = bool(last_c >= prior_hi * 0.998)

    # H4: RSI continuation band (not oversold requirement)
    h4 = bool(50.0 <= r14 <= 76.0 and r7 >= r7p - 0.35)

    # H5: higher-low sequence vs recent swing
    swing_lo = float(low.iloc[-10:-2].min()) if len(low) >= 12 else last_l
    h5 = bool(last_l >= swing_lo * 1.0004)

    hits = int(h1) + int(h2) + int(h3) + int(h4) + int(h5)
    detail_parts = [
        f"h_vwap_pullback_reclaim={int(h1)}",
        f"h_ema_stack={int(h2)}",
        f"h_near_recent_highs={int(h3)}",
        f"h_rsi_continuation_band={int(h4)}",
        f"h_higher_low_structure={int(h5)}",
    ]
    out["momentum_path_hits"] = hits
    out["momentum_paths_detail"] = ";".join(detail_parts)

    vol_diag = rsi_hf_volume_confirmation(
        s["volume"].astype(float),
        z_floor=float(volume_z_floor),
        ratio_floor=float(volume_ratio_floor),
        is_leader=bool(is_leader),
        trend_quality=int(hits),
    )
    vol_ok = bool(vol_diag.get("volume_confirmation_ok"))

    # Scores (0-100) — simple transparent composites for diagnostics / UI
    vwap_lift = max(0.0, min(1.0, (last_c / max(vwap_last, 1e-9) - 1.0) * 80.0))
    ema_lift = max(0.0, min(1.0, (e8 / max(e20, 1e-9) - 1.0) * 120.0))
    hi_participation = max(0.0, min(1.0, (last_c / max(prior_hi, 1e-9) - 0.995) * 120.0))
    out["trend_strength_score"] = round(float((vwap_lift + ema_lift + hi_participation) / 3.0 * 100.0), 3)

    pullback_depth = 0.0
    if vwap_last > 0:
        pullback_depth = max(0.0, min(1.0, (last_c - tail_lo) / max(last_c * 0.02, vwap_last * 0.01)))
    rsi_mid_strength = max(0.0, min(1.0, (r14 - 48.0) / 28.0))
    out["continuation_quality_score"] = round(
        float((pullback_depth * 0.45 + rsi_mid_strength * 0.35 + (hits / 5.0) * 0.2) * 100.0),
        3,
    )

    need = int(min_hits)
    if float(minutes_since_open) >= float(late_open_minutes):
        need = max(need, int(min_hits_late_session))

    out.update(vol_diag)

    if not vol_ok:
        out["momentum_continuation_reason"] = "volume_confirmation_fail"
        return out

    if hits < need:
        out["momentum_continuation_reason"] = f"momentum_hits_lt_min({hits}<{need})"
        return out

    out["momentum_continuation_ok"] = True
    out["momentum_continuation_reason"] = "ok"
    return out
