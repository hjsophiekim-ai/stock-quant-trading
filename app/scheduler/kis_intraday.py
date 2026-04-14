"""
KIS 당일 분봉(inquire-time-itemchartprice) 조회·캐시·OHLC 변환.

일봉 유니버스(kis_universe)와 분리된 경로이며, StrategyContext.prices 와 동일 스키마:
(symbol, date, open, high, low, close, volume) — date 는 분봉 시각(KST tz-aware).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from zoneinfo import ZoneInfo

from app.clients.kis_client import KISClient, KISClientError
from app.clients.kis_parsers import output2_rows

_KST = ZoneInfo("Asia/Seoul")
_STOCK_MKT = "J"


def _hhmmss_from_ts(ts: pd.Timestamp) -> str:
    t = ts.tz_convert(_KST) if ts.tzinfo else ts.tz_localize(_KST)
    return t.strftime("%H%M%S")


def _combine_kst_date_time(date_yyyymmdd: str, hhmmss: str) -> pd.Timestamp | None:
    ds = str(date_yyyymmdd or "").strip()
    hs = str(hhmmss or "").strip().zfill(6)[:6]
    if len(ds) < 8 or len(hs) < 6:
        return None
    try:
        base = ds[:8]
        hh, mm, ss = int(hs[:2]), int(hs[2:4]), int(hs[4:6])
        dt = datetime.strptime(base, "%Y%m%d").replace(hour=hh, minute=mm, second=ss, tzinfo=_KST)
        return pd.Timestamp(dt)
    except (ValueError, TypeError):
        return None


def _float_cell(row: dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        if k in row and row[k] is not None and str(row[k]).strip() != "":
            try:
                return float(row[k])
            except (TypeError, ValueError):
                continue
    return None


def kis_time_chart_row_to_bar(row: dict[str, Any], *, symbol: str, default_date_yyyymmdd: str) -> dict[str, Any] | None:
    """output2 한 행 → OHLC dict (실패 시 None). 필드명은 KIS 응답 변형에 대비해 복수 후보."""
    d_raw = row.get("stck_bsop_date") or row.get("stck_bsop_dt") or default_date_yyyymmdd
    ds = str(d_raw or "").strip()
    if len(ds) >= 8:
        ds8 = ds[:8]
    else:
        ds8 = default_date_yyyymmdd[:8]

    h_raw = (
        row.get("stck_cntg_hour")
        or row.get("bsop_hour")
        or row.get("cntg_hour")
        or row.get("stck_cntg_hour1")
    )
    if h_raw is None:
        return None
    hs = str(h_raw).strip().zfill(6)[:6]

    ts = _combine_kst_date_time(ds8, hs)
    if ts is None:
        return None

    o = _float_cell(row, "stck_oprc", "oprc")
    h = _float_cell(row, "stck_hgpr", "hgpr")
    low = _float_cell(row, "stck_lwpr", "lwpr")
    c = _float_cell(row, "stck_clpr", "stck_prpr", "prpr", "clpr")
    vol = _float_cell(row, "cntg_vol", "acml_vol", "vol")
    if c is None or c <= 0:
        return None
    if vol is None:
        vol = 0.0
    if o is None or o <= 0:
        o = c
    if h is None or h <= 0:
        h = c
    if low is None or low <= 0:
        low = c

    return {
        "symbol": symbol,
        "date": ts,
        "open": float(o),
        "high": float(h),
        "low": float(low),
        "close": float(c),
        "volume": float(vol),
    }


def kis_time_chart_rows_to_ohlc_df(
    rows: list[dict[str, Any]],
    *,
    symbol: str,
    default_date_yyyymmdd: str,
) -> pd.DataFrame:
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        bar = kis_time_chart_row_to_bar(row, symbol=symbol, default_date_yyyymmdd=default_date_yyyymmdd)
        if bar:
            parsed.append(bar)
    if not parsed:
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(parsed)
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return df


def resample_minute_ohlc(df_1m: pd.DataFrame, bar_minutes: int) -> pd.DataFrame:
    """1분 OHLC DataFrame → N분 봉(라벨 좌측, KST 인덱스)."""
    if df_1m.empty or bar_minutes <= 1:
        return df_1m.copy() if not df_1m.empty else df_1m
    if "date" not in df_1m.columns:
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    sym = str(df_1m["symbol"].iloc[0]) if "symbol" in df_1m.columns and len(df_1m) else ""
    x = df_1m.sort_values("date").set_index("date")
    if isinstance(x.index, pd.DatetimeIndex):
        if x.index.tz is None:
            x.index = x.index.tz_localize(_KST)
        else:
            x.index = x.index.tz_convert(_KST)
    rule = f"{int(bar_minutes)}min"
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    out = x.groupby(pd.Grouper(freq=rule, label="left", closed="left")).agg(agg)
    out = out.dropna(subset=["close"])
    out = out.reset_index()
    out["symbol"] = sym
    return out[["symbol", "date", "open", "high", "low", "close", "volume"]]


@dataclass
class _CacheEntry:
    df: pd.DataFrame
    mono_ts: float


@dataclass
class IntradayChartCache:
    """심볼별 분봉 캐시 + 호스트 단위 최소 재요청 간격."""

    ttl_sec: float = 45.0
    min_interval_sec: float = 0.35
    _entries: dict[tuple[str, str], _CacheEntry] = field(default_factory=dict)
    _next_allowed: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _throttle_symbol(self, symbol: str) -> None:
        key = symbol.strip()
        with self._lock:
            now = time.monotonic()
            earliest = self._next_allowed.get(key, 0.0)
            if now < earliest:
                time.sleep(earliest - now)
            self._next_allowed[key] = time.monotonic() + max(0.0, float(self.min_interval_sec))

    def get_cached(self, cache_key: str, symbol: str) -> pd.DataFrame | None:
        k = (cache_key, symbol.strip())
        with self._lock:
            ent = self._entries.get(k)
            if ent is None:
                return None
            if (time.monotonic() - ent.mono_ts) > float(self.ttl_sec):
                return None
            return ent.df.copy()

    def put(self, cache_key: str, symbol: str, df: pd.DataFrame) -> None:
        k = (cache_key, symbol.strip())
        with self._lock:
            self._entries[k] = _CacheEntry(df=df.copy(), mono_ts=time.monotonic())


def _cursor_before_minute(hhmmss: str) -> str:
    """다음 페이징용: HHMMSS 에서 1분 전."""
    hs = str(hhmmss or "").strip().zfill(6)[:6]
    try:
        h, m, s = int(hs[:2]), int(hs[2:4]), int(hs[4:6])
        base = datetime(2000, 1, 1, h, m, s, tzinfo=_KST) - timedelta(minutes=1)
        return base.strftime("%H%M%S")
    except (ValueError, TypeError):
        return "090000"


def fetch_today_minute_bars(
    client: KISClient,
    symbol: str,
    *,
    market_div: str = _STOCK_MKT,
    target_bars: int = 120,
    max_pages: int = 8,
    include_past_data: str = "Y",
    logger: logging.Logger | None = None,
    cache: IntradayChartCache | None = None,
    cache_key: str | None = None,
) -> pd.DataFrame:
    """
    당일 1분 봉을 페이징으로 수집(최대 target_bars 근접).
    장외·데이터 없음이면 빈 DataFrame.
    """
    log = logger or logging.getLogger("app.scheduler.kis_intraday")
    today = datetime.now(_KST).strftime("%Y%m%d")
    ck = cache_key or today
    if cache:
        hit = cache.get_cached(ck, symbol)
        if hit is not None:
            return hit

    cursor = datetime.now(_KST).strftime("%H%M%S")
    merged_rows: list[dict[str, Any]] = []

    for page in range(max_pages):
        if cache:
            cache._throttle_symbol(symbol)
        try:
            payload = client.get_time_itemchartprice(
                market_div_code=market_div,
                symbol=symbol,
                input_hour_hhmmss=cursor,
                include_past_data=include_past_data,
                etc_cls_code="",
            )
        except KISClientError as exc:
            log.warning("time chart failed symbol=%s page=%s err=%s", symbol, page, exc)
            break
        batch = output2_rows(payload)
        if not batch:
            break
        merged_rows.extend(batch)

        df_partial = kis_time_chart_rows_to_ohlc_df(merged_rows, symbol=symbol, default_date_yyyymmdd=today)
        if len(df_partial) >= target_bars:
            break

        oldest_ts: pd.Timestamp | None = None
        for row in batch:
            bar = kis_time_chart_row_to_bar(row, symbol=symbol, default_date_yyyymmdd=today)
            if bar is None:
                continue
            ts = bar["date"]
            if isinstance(ts, pd.Timestamp):
                if oldest_ts is None or ts < oldest_ts:
                    oldest_ts = ts
        if oldest_ts is None:
            break
        cursor = _cursor_before_minute(_hhmmss_from_ts(oldest_ts))

    df = kis_time_chart_rows_to_ohlc_df(merged_rows, symbol=symbol, default_date_yyyymmdd=today)
    if cache is not None and not df.empty:
        cache.put(ck, symbol, df)
    return df


def build_intraday_universe_1m(
    client: KISClient,
    symbols: list[str],
    *,
    target_bars_per_symbol: int = 120,
    logger: logging.Logger | None = None,
    cache: IntradayChartCache | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for sym in symbols:
        s = sym.strip()
        if not s:
            continue
        df = fetch_today_minute_bars(
            client,
            s,
            target_bars=target_bars_per_symbol,
            logger=logger,
            cache=cache,
        )
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    return pd.concat(frames, ignore_index=True)


def universe_as_timeframe(universe_1m: pd.DataFrame, bar_minutes: int) -> pd.DataFrame:
    """심목별로 묶어 N분 봉으로 변환 후 다시 concat."""
    if universe_1m.empty or bar_minutes <= 1:
        return universe_1m.copy()
    parts: list[pd.DataFrame] = []
    for sym in universe_1m["symbol"].unique():
        sub = universe_1m[universe_1m["symbol"] == sym].copy()
        parts.append(resample_minute_ohlc(sub, bar_minutes))
    if not parts:
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    return pd.concat(parts, ignore_index=True)
