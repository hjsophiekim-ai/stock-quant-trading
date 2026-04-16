"""US Paper 전용: 분봉 조회·OHLC 변환·(스윙용) 일봉 유사 시계열 합성 — import 시 네트워크 없음."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
from zoneinfo import ZoneInfo

from app.clients.kis_client import KISClient, KISClientError
from app.clients.kis_parsers import output1_rows, output2_rows
from app.scheduler.kis_intraday import FETCH_OK, FETCH_API_ERROR, resample_minute_ohlc

from backend.app.market.us_exchange_map import excd_for_price_chart
from backend.app.services.us_symbol_search_service import search_us_symbols_via_kis

_ET = ZoneInfo("America/New_York")
logger = logging.getLogger("backend.app.market.us_paper_universe")


def _float_cell(row: dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        if k in row and row[k] is not None and str(row[k]).strip() != "":
            try:
                return float(row[k])
            except (TypeError, ValueError):
                continue
    return None


def overseas_time_chart_row_to_bar(row: dict[str, Any], *, symbol: str, default_yyyymmdd: str) -> dict[str, Any] | None:
    """해외 분봉 output2 한 행 → OHLC (시각은 ET 기준으로 해석 후 UTC 저장)."""
    d_raw = (
        row.get("xymd")
        or row.get("stck_bsop_date")
        or row.get("stck_bsop_dt")
        or row.get("ovrs_date")
        or default_yyyymmdd
    )
    ds = str(d_raw or "").strip()
    ds8 = ds[:8] if len(ds) >= 8 else default_yyyymmdd[:8]

    h_raw = row.get("xhms") or row.get("stck_cntg_hour") or row.get("cntg_hour") or row.get("bsop_hour")
    if h_raw is None:
        return None
    hs = str(h_raw).strip().zfill(6)[:6]
    try:
        base = datetime.strptime(ds8, "%Y%m%d").replace(
            hour=int(hs[:2]),
            minute=int(hs[2:4]),
            second=int(hs[4:6]),
            tzinfo=_ET,
        )
        ts = pd.Timestamp(base.astimezone(timezone.utc))
    except (ValueError, TypeError):
        return None

    o = _float_cell(row, "open", "oprc", "stck_oprc", "ovrs_nmix_prpr")
    h = _float_cell(row, "high", "hgpr", "stck_hgpr")
    low = _float_cell(row, "low", "lwpr", "stck_lwpr")
    c = _float_cell(row, "last", "prpr", "stck_clpr", "clpr", "stck_prpr")
    vol = _float_cell(row, "tvol", "cntg_vol", "acml_vol", "vol") or 0.0
    if c is None or c <= 0:
        return None
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


def overseas_time_chart_to_ohlc_df(payload: dict[str, Any], *, symbol: str) -> pd.DataFrame:
    rows = output2_rows(payload)
    if not rows:
        rows = output1_rows(payload)
    default_yyyymmdd = datetime.now(_ET).strftime("%Y%m%d")
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        bar = overseas_time_chart_row_to_bar(row, symbol=symbol, default_yyyymmdd=default_yyyymmdd)
        if bar:
            parsed.append(bar)
    if not parsed:
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(parsed)
    return df.sort_values("date").drop_duplicates(subset=["date"], keep="last")


def fetch_us_minute_universe(
    client: KISClient,
    symbols: list[str],
    *,
    nrec: str = "120",
    nmin: str = "1",
    logger_: logging.Logger | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """심볼별 해외 1분봉을 한 DataFrame으로 병합(실패 행은 intraday_bar_fetch_summary 스타일)."""
    log = logger_ or logger
    frames: list[pd.DataFrame] = []
    summary: list[dict[str, Any]] = []
    today_et = datetime.now(_ET).strftime("%Y%m%d")
    for sym in symbols:
        s = str(sym or "").strip().upper()
        if not s:
            continue
        try:
            hits = search_us_symbols_via_kis(client, s, limit=1)
            if not hits:
                summary.append({"symbol": s, "fetch_error": "search_miss", "detail": "no search-info hit"})
                continue
            ov = str(hits[0].get("ovrs_excg_cd") or "NASD")
            ex2 = excd_for_price_chart(ov)
            raw = client.get_overseas_time_itemchartprice(
                auth="",
                excd=ex2,
                symb=s,
                nmin=str(nmin),
                pinc="1",
                next_flag="",
                nrec=str(min(int(nrec), 120)),
                fill="",
                keyb="",
            )
            df1 = overseas_time_chart_to_ohlc_df(raw, symbol=s)
            if df1.empty:
                summary.append({"symbol": s, "fetch_error": "empty_df", "excd": ex2})
            else:
                summary.append({"symbol": s, "fetch_error": FETCH_OK, "excd": ex2, "rows": len(df1)})
                frames.append(df1)
        except KISClientError as exc:
            ctx = getattr(exc, "kis_context", {}) or {}
            summary.append(
                {
                    "symbol": s,
                    "fetch_error": FETCH_API_ERROR,
                    "kis_path": ctx.get("path"),
                    "kis_tr_id": ctx.get("tr_id"),
                    "detail": str(exc)[:300],
                }
            )
            log.warning("us minute fetch %s: %s", s, exc)
        except Exception as exc:
            summary.append({"symbol": s, "fetch_error": type(exc).__name__, "detail": str(exc)[:300]})
            log.warning("us minute fetch %s: %s", s, exc)

    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"]), summary
    out = pd.concat(frames, ignore_index=True)
    return out, summary


def _synthetic_daily_history(*, symbol: str, seed_close: float, days: int = 80) -> pd.DataFrame:
    """스윙 지표(MA60 등)용 — API 일봉 부재 시 시드 종가로부터 결정론적 흔들림 일봉 생성(연구·Paper 전용)."""
    rng_days = max(int(days), 65)
    closes: list[float] = []
    x = float(seed_close)
    for i in range(rng_days):
        delta = 0.008 * (1 if i % 7 != 0 else -1) * ((i % 5) - 2)
        x = max(0.01, x * (1.0 + delta))
        closes.append(x)
    closes.reverse()
    rows: list[dict[str, Any]] = []
    end = datetime.now(_ET).date()
    d = end
    idx = 0
    while idx < len(closes):
        if d.weekday() < 5:
            c = closes[idx]
            o = c * (1.0 - 0.001 * (idx % 3))
            h = max(o, c) * 1.002
            low = min(o, c) * 0.998
            vol = 1_000_000.0 + float(idx % 17) * 10_000.0
            ts = pd.Timestamp(datetime.combine(d, datetime.min.time()).replace(tzinfo=_ET)).tz_convert(timezone.utc)
            rows.append(
                {
                    "symbol": symbol,
                    "date": ts,
                    "open": float(o),
                    "high": float(h),
                    "low": float(low),
                    "close": float(c),
                    "volume": float(vol),
                }
            )
            idx += 1
        d -= timedelta(days=1)
        if (end - d).days > rng_days + 14:
            break
    return pd.DataFrame(rows).sort_values("date")


def build_us_swing_daily_universe(client: KISClient, symbols: list[str]) -> pd.DataFrame:
    """분봉으로 최신가를 얻고, 스윙용 일봉은 합성 시계열로 보강(전량 유니버스 로드 없음)."""
    frames: list[pd.DataFrame] = []
    minute_df, _ = fetch_us_minute_universe(client, symbols, nrec="30", nmin="1")
    for sym in symbols:
        s = str(sym or "").strip().upper()
        if not s:
            continue
        sub = minute_df[minute_df["symbol"] == s] if not minute_df.empty else pd.DataFrame()
        seed = float(sub["close"].iloc[-1]) if not sub.empty else 100.0
        frames.append(_synthetic_daily_history(symbol=s, seed_close=seed, days=85))
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    return pd.concat(frames, ignore_index=True)


def minimal_macro_series() -> tuple[pd.DataFrame, pd.DataFrame]:
    """US Paper에서 코스피·변동성 경로만 통과시키기 위한 최소 더미 시계열(네트워크 없음)."""
    ts = pd.Timestamp(datetime.now(timezone.utc) - timedelta(days=5))
    idx = pd.date_range(ts, periods=30, freq="D", tz="UTC")
    k = pd.DataFrame({"date": idx, "close": [100.0 + 0.05 * i for i in range(len(idx))]})
    sp = pd.DataFrame({"date": idx, "close": [400.0 + 0.03 * i for i in range(len(idx))]})
    return k, sp
