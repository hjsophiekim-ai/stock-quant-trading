from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from app.clients.kis_client import KISClient, KISClientError

_KST = ZoneInfo("Asia/Seoul")
_STOCK_MKT = "J"
_INDEX_MKT = "U"
_KOSPI_CODE = "0001"


def _yyyymmdd(d: datetime) -> str:
    return d.strftime("%Y%m%d")


def _rows_from_chart_payload(payload: dict) -> list[dict]:
    out = payload.get("output2")
    if not isinstance(out, list):
        return []
    return [x for x in out if isinstance(x, dict)]


def kis_chart_to_ohlc_df(rows: list[dict], *, symbol: str) -> pd.DataFrame:
    """Map KIS inquire-daily-itemchartprice output2 rows to strategy OHLC schema."""
    parsed: list[dict] = []
    for row in rows:
        d_raw = row.get("stck_bsop_date") or row.get("stck_bsop_dt")
        if not d_raw:
            continue
        ds = str(d_raw).strip()
        try:
            if len(ds) >= 8:
                ts = pd.Timestamp(ds[:8], tz=_KST)
            else:
                continue
        except (ValueError, TypeError):
            continue
        try:
            o = float(row.get("stck_oprc", 0) or 0)
            h = float(row.get("stck_hgpr", 0) or 0)
            l_ = float(row.get("stck_lwpr", 0) or 0)
            c = float(row.get("stck_clpr", 0) or 0)
            vol = float(row.get("acml_vol", 0) or 0)
        except (TypeError, ValueError):
            continue
        if c <= 0:
            continue
        parsed.append(
            {
                "symbol": symbol,
                "date": ts,
                "open": o if o > 0 else c,
                "high": h if h > 0 else c,
                "low": l_ if l_ > 0 else c,
                "close": c,
                "volume": vol,
            }
        )
    if not parsed:
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(parsed)
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return df


def fetch_symbol_history(
    client: KISClient,
    symbol: str,
    *,
    market_div: str = _STOCK_MKT,
    lookback_calendar_days: int = 180,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    log = logger or logging.getLogger("app.scheduler.kis_universe")
    end = datetime.now(_KST)
    start = end - timedelta(days=lookback_calendar_days)
    try:
        payload = client.get_daily_itemchartprice(
            market_div_code=market_div,
            symbol=symbol,
            start_date_yyyymmdd=_yyyymmdd(start),
            end_date_yyyymmdd=_yyyymmdd(end),
        )
    except KISClientError as exc:
        log.error("KIS daily chart failed symbol=%s err=%s", symbol, exc)
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    rows = _rows_from_chart_payload(payload)
    return kis_chart_to_ohlc_df(rows, symbol=symbol)


def build_kis_stock_universe(
    client: KISClient,
    symbols: list[str],
    *,
    lookback_calendar_days: int = 180,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for sym in symbols:
        sym = sym.strip()
        if not sym:
            continue
        df = fetch_symbol_history(
            client,
            sym,
            lookback_calendar_days=lookback_calendar_days,
            logger=logger,
        )
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    return pd.concat(frames, ignore_index=True)


def build_kospi_index_series(
    client: KISClient,
    *,
    lookback_calendar_days: int = 180,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    df = fetch_symbol_history(
        client,
        _KOSPI_CODE,
        market_div=_INDEX_MKT,
        lookback_calendar_days=lookback_calendar_days,
        logger=logger,
    )
    if df.empty:
        return df
    return df[["date", "close"]].copy()


def build_mock_sp500_proxy_from_kospi(kospi: pd.DataFrame) -> pd.DataFrame:
    """S&P500 series is not fetched via domestic KIS chart in this build; mirror KOSPI shape for regime math."""
    if kospi.empty or "close" not in kospi.columns:
        end = datetime.now(_KST).date()
        rows = []
        for i in range(40):
            d = end - timedelta(days=40 - i)
            rows.append({"date": pd.Timestamp(d, tz=_KST), "close": float(4500 + i)})
        return pd.DataFrame(rows)
    out = kospi.sort_values("date").copy()
    out["close"] = out["close"].astype("float64") * 0.00025 + 4000.0
    return out[["date", "close"]]


def build_mock_volatility_series(kospi: pd.DataFrame) -> pd.DataFrame:
    if kospi.empty:
        end = datetime.now(_KST).date()
        rows = []
        for i in range(20):
            d = end - timedelta(days=20 - i)
            rows.append({"date": pd.Timestamp(d, tz=_KST), "value": 18.0 + i * 0.05})
        return pd.DataFrame(rows)
    base = kospi.sort_values("date")[["date"]].copy()
    base["value"] = 18.0
    return base
