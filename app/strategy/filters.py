from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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


def filter_relaxed_swing_candidates(prices_df: pd.DataFrame) -> list[str]:
    """
    Paper 검증용: swing_v1 보다 완화된 품질 필터(60일 수익률 상위 55%·거래량 조건 생략·MA60 기울기만).
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
        row = g2.iloc[-1]
        if pd.isna(row["ma60"]) or pd.isna(row["ret_60d_pct"]):
            continue
        per_symbol.append(
            {
                "symbol": symbol,
                "ma60_slope_up": bool(row["ma60"] > g2.iloc[-2]["ma60"]) if len(g2) >= 61 else False,
                "ret_60d_pct": float(row["ret_60d_pct"]),
            }
        )

    if not per_symbol:
        return []

    snap = pd.DataFrame(per_symbol)
    cutoff = snap["ret_60d_pct"].quantile(0.45)
    selected = snap[(snap["ma60_slope_up"]) & (snap["ret_60d_pct"] >= cutoff)]
    return selected["symbol"].tolist()


def explain_swing_candidate_filters(prices_df: pd.DataFrame) -> list[dict[str, Any]]:
    """
    후보가 0일 때 종목별로 어떤 조건에서 걸렸는지 설명(Paper 대시보드용).
    """
    required = {"symbol", "date", "close", "volume"}
    missing = required - set(prices_df.columns)
    if missing:
        return [{"error": f"Missing columns: {sorted(missing)}"}]

    df = prices_df.sort_values(["symbol", "date"]).copy()
    per_symbol: list[dict[str, Any]] = []
    for symbol, g in df.groupby("symbol", sort=False):
        g2 = g.copy()
        g2["ma60"] = g2["close"].rolling(60, min_periods=60).mean()
        g2["ret_60d_pct"] = g2["close"].pct_change(60) * 100.0
        g2["vol20"] = g2["volume"].rolling(20, min_periods=20).mean()
        row = g2.iloc[-1]
        if pd.isna(row["ma60"]) or pd.isna(row["ret_60d_pct"]) or pd.isna(row["vol20"]):
            per_symbol.append(
                {
                    "symbol": symbol,
                    "skipped": True,
                    "reason": "데이터 부족(MA60·60일수익률·거래량20일 미계산)",
                }
            )
            continue
        ma60_slope_up = bool(row["ma60"] > g2.iloc[-2]["ma60"]) if len(g2) >= 61 else False
        volume_ok = bool(float(row["volume"]) >= float(row["vol20"]))
        ret_60d_pct = float(row["ret_60d_pct"])
        per_symbol.append(
            {
                "symbol": symbol,
                "ma60_slope_up": ma60_slope_up,
                "volume_ok": volume_ok,
                "ret_60d_pct": round(ret_60d_pct, 4),
                "volume_vs_vol20": round(float(row["volume"]) / float(row["vol20"]), 4) if float(row["vol20"]) > 0 else None,
            }
        )

    if not per_symbol:
        return []

    snap = pd.DataFrame([r for r in per_symbol if not r.get("skipped")])
    if snap.empty:
        return per_symbol

    cutoff = float(snap["ret_60d_pct"].quantile(0.70))
    out: list[dict[str, Any]] = []
    for r in per_symbol:
        if r.get("skipped"):
            out.append(r)
            continue
        sym = r["symbol"]
        failed: list[str] = []
        if not r["ma60_slope_up"]:
            failed.append("MA60 기울기 하락(전일 대비)")
        if not r["volume_ok"]:
            failed.append("당일 거래량 < 20일 평균")
        if float(r["ret_60d_pct"]) < cutoff:
            failed.append(f"60일 수익률이 유니버스 70분위({cutoff:.2f}%) 미만")
        passed = not failed
        out.append({**r, "ret_60d_cutoff_pct": round(cutoff, 4), "passed_strict_filter": passed, "failed_reasons": failed})
    return out


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
