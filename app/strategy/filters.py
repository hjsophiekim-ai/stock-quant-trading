from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class MarketFilterResult:
    allow_new_buy: bool
    reasons: list[str]


def evaluate_global_market_filter(kospi_df: pd.DataFrame, sp500_df: pd.DataFrame) -> MarketFilterResult:
    reasons: list[str] = []
    allow = True

    if _is_downtrend_by_ma20(kospi_df):
        allow = False
        reasons.append("KOSPI downtrend")
    if _is_downtrend_by_ma20(sp500_df):
        allow = False
        reasons.append("S&P500 MA20 downtrend")

    return MarketFilterResult(allow_new_buy=allow, reasons=reasons)


def filter_quality_swing_candidates(prices_df: pd.DataFrame) -> list[str]:
    """
    prices_df columns:
    - symbol, date, open, high, low, close, volume
    """
    required = {"symbol", "date", "close", "volume"}
    missing = required - set(prices_df.columns)
    if missing:
        raise ValueError(f"Missing columns for candidate filtering: {sorted(missing)}")

    df = prices_df.sort_values(["symbol", "date"]).copy()
    per_symbol = []
    for symbol, g in df.groupby("symbol", sort=False):
        g2 = g.copy()
        g2["ma60"] = g2["close"].rolling(60, min_periods=60).mean()
        g2["ret_60d_pct"] = g2["close"].pct_change(60) * 100.0
        g2["vol20"] = g2["volume"].rolling(20, min_periods=20).mean()
        row = g2.iloc[-1]
        if pd.isna(row["ma60"]) or pd.isna(row["ret_60d_pct"]) or pd.isna(row["vol20"]):
            continue
        per_symbol.append(
            {
                "symbol": symbol,
                "ma60_slope_up": bool(row["ma60"] > g2.iloc[-2]["ma60"]) if len(g2) >= 61 else False,
                "ret_60d_pct": float(row["ret_60d_pct"]),
                "volume_ok": bool(float(row["volume"]) >= float(row["vol20"])),
            }
        )

    if not per_symbol:
        return []

    snap = pd.DataFrame(per_symbol)
    cutoff = snap["ret_60d_pct"].quantile(0.70)
    selected = snap[
        (snap["ma60_slope_up"])
        & (snap["volume_ok"])
        & (snap["ret_60d_pct"] >= cutoff)
    ]
    return selected["symbol"].tolist()


def _is_downtrend_by_ma20(index_df: pd.DataFrame) -> bool:
    required = {"date", "close"}
    missing = required - set(index_df.columns)
    if missing:
        raise ValueError(f"Missing columns for market filter: {sorted(missing)}")
    df = index_df.sort_values("date").copy()
    df["ma20"] = df["close"].rolling(20, min_periods=20).mean()
    if len(df) < 21 or pd.isna(df.iloc[-1]["ma20"]) or pd.isna(df.iloc[-2]["ma20"]):
        return False
    return bool(df.iloc[-1]["ma20"] < df.iloc[-2]["ma20"])
