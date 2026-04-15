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

from app.clients.kis_contract import TIME_ITEMCHART_FID_ETC_CLS_CODE
from app.clients.kis_client import KISClient, KISClientError
from app.clients.kis_parsers import output2_rows
_KST = ZoneInfo("Asia/Seoul")
_STOCK_MKT = "J"

# 분봉 수집 실패/구분 코드 (tick_report.intraday_bar_fetch_summary)
FETCH_OK = ""
FETCH_EMPTY_OUTPUT2 = "empty_output2"
FETCH_API_ERROR = "api_error"
FETCH_PARSE_FAILED = "parse_failed"
FETCH_OUTSIDE_SESSION = "outside_session_or_no_data"
FETCH_SKIPPED_OFFSESSION = "skipped_off_session"
FETCH_SKIPPED_PREOPEN_DISABLED = "skipped_preopen_disabled"
FETCH_SKIPPED_AFTERHOURS_DISABLED = "skipped_afterhours_disabled"
FETCH_SKIPPED_CLOSED_SESSION = "skipped_closed_session"


def kis_client_error_to_fetch_row_fields(exc: KISClientError) -> dict[str, Any]:
    """KISClientError.kis_context → intraday_bar_fetch_summary 확장 필드."""
    ctx = getattr(exc, "kis_context", None) or {}
    params = ctx.get("params")
    if isinstance(params, dict):
        params_out: Any = dict(params)
    else:
        params_out = params
    return {
        "fetch_error_detail_full": str(exc),
        "kis_path": ctx.get("path"),
        "kis_tr_id": ctx.get("tr_id"),
        "kis_http_status": ctx.get("http_status"),
        "kis_params": params_out,
        "kis_rate_limit": bool(ctx.get("rate_limit")),
        "kis_rt_cd": ctx.get("rt_cd"),
        "kis_msg_cd": ctx.get("msg_cd"),
        "kis_msg1": ctx.get("msg1"),
    }


def summarize_intraday_fetch_errors(
    summary_rows: list[dict[str, Any]],
    *,
    top_n: int = 3,
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for r in summary_rows:
        key = str(r.get("fetch_error") or "")
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return [{"fetch_error": k, "count": v} for k, v in ordered[: int(top_n)]]


def first_intraday_api_error_row(summary_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for r in summary_rows:
        if str(r.get("fetch_error") or "") == FETCH_API_ERROR:
            return r
    return None


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


def _ts_to_kst_iso(ts: pd.Timestamp | None) -> str | None:
    if ts is None:
        return None
    if isinstance(ts, pd.Timestamp):
        t = ts.tz_convert(_KST) if ts.tzinfo else ts.tz_localize(_KST)
        return t.isoformat()
    return None


def _bar_fetch_row_template(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "bars_1m": 0,
        "first_bar_kst": None,
        "last_bar_kst": None,
        "fetch_error": "",
        "fetch_error_detail": "",
        "fetch_error_detail_full": "",
        "session_state": "",
        "fetch_allowed": True,
        "order_allowed": True,
        "fetch_block_reason": "",
        "kis_path": None,
        "kis_tr_id": None,
        "kis_http_status": None,
        "kis_params": None,
        "kis_rate_limit": False,
        "kis_rt_cd": None,
        "kis_msg_cd": None,
        "kis_msg1": None,
    }


def _df_to_fetch_summary_row(
    symbol: str,
    df: pd.DataFrame,
    fetch_error: str,
    detail: str = "",
    *,
    session_state: str = "",
    fetch_allowed: bool = True,
    order_allowed: bool = True,
    fetch_block_reason: str = "",
) -> dict[str, Any]:
    row = _bar_fetch_row_template(symbol)
    row["fetch_error"] = fetch_error or ""
    row["fetch_error_detail"] = (detail or "")[:500]
    row["session_state"] = session_state or ""
    row["fetch_allowed"] = bool(fetch_allowed)
    row["order_allowed"] = bool(order_allowed)
    row["fetch_block_reason"] = fetch_block_reason or ""
    if df.empty or "date" not in df.columns:
        return row
    sorted_df = df.sort_values("date")
    row["bars_1m"] = int(len(sorted_df))
    first = sorted_df["date"].iloc[0]
    last = sorted_df["date"].iloc[-1]
    row["first_bar_kst"] = _ts_to_kst_iso(first if isinstance(first, pd.Timestamp) else None)
    row["last_bar_kst"] = _ts_to_kst_iso(last if isinstance(last, pd.Timestamp) else None)
    return row


def _cursor_before_minute(hhmmss: str) -> str:
    """다음 페이징용: HHMMSS 에서 1분 전."""
    hs = str(hhmmss or "").strip().zfill(6)[:6]
    try:
        h, m, s = int(hs[:2]), int(hs[2:4]), int(hs[4:6])
        base = datetime(2000, 1, 1, h, m, s, tzinfo=_KST) - timedelta(minutes=1)
        return base.strftime("%H%M%S")
    except (ValueError, TypeError):
        return "090000"


def fetch_today_minute_bars_with_diag(
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
    intraday_fetch_allowed: bool = True,
    intraday_fetch_block_reason: str = "",
    session_state: str = "",
    order_allowed: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    당일 1분 봉 + 심볼별 진단(dict: bars_1m, first/last KST, fetch_error 코드).
    """
    log = logger or logging.getLogger("app.scheduler.kis_intraday")
    today = datetime.now(_KST).strftime("%Y%m%d")
    ck = cache_key or today

    if not intraday_fetch_allowed:
        empty = pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
        code = intraday_fetch_block_reason or FETCH_SKIPPED_CLOSED_SESSION
        detail_map = {
            FETCH_SKIPPED_PREOPEN_DISABLED: "장전 구간이나 설정에서 장전 분봉 조회가 비활성입니다.",
            FETCH_SKIPPED_AFTERHOURS_DISABLED: "장후 구간이나 설정에서 장후 분봉 조회가 비활성입니다.",
            FETCH_SKIPPED_CLOSED_SESSION: "거래일 세션 밖(완전 장외)입니다.",
            FETCH_SKIPPED_OFFSESSION: "세션 정책에 따라 분봉 API 호출을 생략했습니다.",
        }
        detail = detail_map.get(code, "분봉 API 호출을 생략했습니다.")
        d = _df_to_fetch_summary_row(
            symbol,
            empty,
            code,
            detail,
            session_state=session_state,
            fetch_allowed=False,
            order_allowed=order_allowed,
            fetch_block_reason=intraday_fetch_block_reason or code,
        )
        return empty, d

    if cache:
        hit = cache.get_cached(ck, symbol)
        if hit is not None:
            diag = _df_to_fetch_summary_row(
                symbol,
                hit,
                FETCH_OK,
                session_state=session_state,
                fetch_allowed=True,
                order_allowed=order_allowed,
                fetch_block_reason="",
            )
            return hit, diag

    cursor = datetime.now(_KST).strftime("%H%M%S")
    merged_rows: list[dict[str, Any]] = []
    last_exc: KISClientError | None = None
    saw_empty_output2 = False
    pages = 0

    for page in range(max_pages):
        pages += 1
        if cache:
            cache._throttle_symbol(symbol)
        try:
            payload = client.get_time_itemchartprice(
                market_div_code=market_div,
                symbol=symbol,
                input_hour_hhmmss=cursor,
                include_past_data=include_past_data,
                etc_cls_code=TIME_ITEMCHART_FID_ETC_CLS_CODE,
            )
        except KISClientError as exc:
            log.warning("time chart failed symbol=%s page=%s err=%s", symbol, page, exc)
            last_exc = exc
            empty = pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
            d = _df_to_fetch_summary_row(
                symbol,
                empty,
                FETCH_API_ERROR,
                str(exc)[:400],
                session_state=session_state,
                fetch_allowed=intraday_fetch_allowed,
                order_allowed=order_allowed,
                fetch_block_reason=intraday_fetch_block_reason if not intraday_fetch_allowed else "",
            )
            d.update(kis_client_error_to_fetch_row_fields(exc))
            return empty, d

        batch = output2_rows(payload)
        if not batch:
            saw_empty_output2 = True
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

    if df.empty:
        err = FETCH_PARSE_FAILED if merged_rows else (FETCH_EMPTY_OUTPUT2 if saw_empty_output2 or pages else FETCH_OUTSIDE_SESSION)
        detail = ""
        if merged_rows and err == FETCH_PARSE_FAILED:
            detail = f"output2_rows={len(merged_rows)} 이지만 OHLC 파싱 결과 0건"
        elif err == FETCH_EMPTY_OUTPUT2:
            detail = "API output2 비어 있음(또는 첫 페이지 무응답)"
        elif err == FETCH_OUTSIDE_SESSION and not merged_rows:
            detail = "수집 행 없음(장외·당일 분봉 미제공 가능)"
        diag = _df_to_fetch_summary_row(
            symbol,
            df,
            err,
            detail,
            session_state=session_state,
            fetch_allowed=intraday_fetch_allowed,
            order_allowed=order_allowed,
            fetch_block_reason=intraday_fetch_block_reason if not intraday_fetch_allowed else "",
        )
        return df, diag

    if cache is not None:
        cache.put(ck, symbol, df)
    diag = _df_to_fetch_summary_row(
        symbol,
        df,
        FETCH_OK,
        session_state=session_state,
        fetch_allowed=True,
        order_allowed=order_allowed,
        fetch_block_reason="",
    )
    return df, diag


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
    intraday_fetch_allowed: bool = True,
    intraday_fetch_block_reason: str = "",
    session_state: str = "",
    order_allowed: bool = True,
) -> pd.DataFrame:
    """하위 호환: DataFrame 만 반환."""
    df, _ = fetch_today_minute_bars_with_diag(
        client,
        symbol,
        market_div=market_div,
        target_bars=target_bars,
        max_pages=max_pages,
        include_past_data=include_past_data,
        logger=logger,
        cache=cache,
        cache_key=cache_key,
        intraday_fetch_allowed=intraday_fetch_allowed,
        intraday_fetch_block_reason=intraday_fetch_block_reason,
        session_state=session_state,
        order_allowed=order_allowed,
    )
    return df


def build_intraday_universe_1m(
    client: KISClient,
    symbols: list[str],
    *,
    target_bars_per_symbol: int = 120,
    logger: logging.Logger | None = None,
    cache: IntradayChartCache | None = None,
    intraday_fetch_allowed: bool = True,
    intraday_fetch_block_reason: str = "",
    session_state: str = "",
    order_allowed: bool = True,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """
    심볼별 1분 OHLC concat + intraday_bar_fetch_summary (티당 진단).
    """
    frames: list[pd.DataFrame] = []
    summary: list[dict[str, Any]] = []
    for sym in symbols:
        s = sym.strip()
        if not s:
            continue
        df, diag = fetch_today_minute_bars_with_diag(
            client,
            s,
            target_bars=target_bars_per_symbol,
            logger=logger,
            cache=cache,
            intraday_fetch_allowed=intraday_fetch_allowed,
            intraday_fetch_block_reason=intraday_fetch_block_reason,
            session_state=session_state,
            order_allowed=order_allowed,
        )
        summary.append(diag)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"]), summary
    return pd.concat(frames, ignore_index=True), summary


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
