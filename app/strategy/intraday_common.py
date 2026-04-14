"""인트라데이 단타 전략용 지표·세션 유틸 (Paper 검증용)."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")


def kst_now() -> datetime:
    return datetime.now(_KST)


def is_regular_krx_session(now: datetime | None = None) -> bool:
    n = now or kst_now()
    if n.tzinfo is None:
        n = n.replace(tzinfo=_KST)
    else:
        n = n.astimezone(_KST)
    if n.weekday() >= 5:
        return False
    hm = n.time()
    return time(9, 0) <= hm <= time(15, 30)


def minutes_since_session_open_kst(now: datetime | None = None) -> float:
    """정규장 기준 개장 후 분(장외·주말은 음수/큰 값으로 비정상)."""
    n = now or kst_now()
    if n.tzinfo is None:
        n = n.replace(tzinfo=_KST)
    else:
        n = n.astimezone(_KST)
    open_dt = n.replace(hour=9, minute=0, second=0, microsecond=0)
    if n < open_dt:
        return -1.0
    return (n - open_dt).total_seconds() / 60.0


def should_force_flatten_before_close_kst(
    *,
    now: datetime | None = None,
    minutes_before_close: int = 15,
) -> bool:
    """장 종료 N분 전부터 당일 청산(overnight 금지)용."""
    n = now or kst_now()
    if n.tzinfo is None:
        n = n.replace(tzinfo=_KST)
    else:
        n = n.astimezone(_KST)
    if n.weekday() >= 5:
        return True
    close_dt = n.replace(hour=15, minute=30, second=0, microsecond=0)
    trigger = close_dt - pd.Timedelta(minutes=int(minutes_before_close))
    return n >= trigger


def quote_liquidity_from_payload(payload: dict[str, Any]) -> dict[str, float]:
    out = payload.get("output")
    if not isinstance(out, dict):
        return {"acml_vol": 0.0, "acml_tr_pbmn": 0.0, "bidp": 0.0, "askp": 0.0, "spread_pct": 99.0}
    def _f(k: str) -> float:
        try:
            return float(out.get(k) or 0)
        except (TypeError, ValueError):
            return 0.0

    bid = _f("bidp")
    ask = _f("askp")
    mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else max(bid, ask, 1.0)
    spread_pct = ((ask - bid) / mid) * 100.0 if mid > 0 else 99.0
    return {
        "acml_vol": _f("acml_vol"),
        "acml_tr_pbmn": _f("acml_tr_pbmn"),
        "bidp": bid,
        "askp": ask,
        "spread_pct": float(spread_pct),
    }


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=int(span), adjust=False).mean()


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """분봉 OHLC: typical price * volume 누적."""
    if df.empty:
        return pd.Series(dtype="float64")
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].clip(lower=0.0)
    cum_vp = (tp * vol).cumsum()
    cum_v = vol.cumsum().replace(0, np.nan)
    return cum_vp / cum_v


def opening_range_high(df: pd.DataFrame, first_n_bars: int) -> float | None:
    if df.empty or len(df) < 2:
        return None
    head = df.sort_values("date").head(max(1, int(first_n_bars)))
    return float(head["high"].max())


def volume_zscore_recent(vol: pd.Series, window: int = 20) -> float | None:
    if len(vol) < window:
        return None
    tail = vol.iloc[-window:]
    mu = float(tail.mean())
    sd = float(tail.std()) or 1e-9
    return float((tail.iloc[-1] - mu) / sd)


def last_bar_body_pct(df: pd.DataFrame) -> float | None:
    if df.empty:
        return None
    last = df.sort_values("date").iloc[-1]
    o, h, low, c = float(last["open"]), float(last["high"]), float(last["low"]), float(last["close"])
    rng = h - low
    if rng <= 0:
        return 0.0
    return abs(c - o) / rng * 100.0
