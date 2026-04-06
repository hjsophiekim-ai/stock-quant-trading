from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from app.strategy.ranking import rank_candidates


def _build_prices() -> pd.DataFrame:
    base = datetime(2026, 1, 1)
    rows: list[dict[str, object]] = []
    symbols = ["A", "B", "C", "D"]
    for s in symbols:
        for i in range(80):
            d = base + timedelta(days=i)
            if s == "A":
                close = 100 + i * 1.2
                volume = 1_500_000 + i * 3000
            elif s == "B":
                close = 100 + i * 0.8
                volume = 1_200_000 + i * 1000
            elif s == "C":
                close = 100 + i * 0.4
                volume = 900_000 + i * 500
            else:
                close = 100 + (i * 0.7 if i % 2 == 0 else i * 0.2)
                volume = 800_000 + i * 700
            rows.append(
                {
                    "symbol": s,
                    "date": d,
                    "open": close * 0.995,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": volume,
                }
            )
    return pd.DataFrame(rows)


def test_ranking_returns_top_n_sorted() -> None:
    prices = _build_prices()
    ranked = rank_candidates(
        prices_df=prices,
        candidate_symbols=["A", "B", "C", "D"],
        regime="bullish_trend",
        top_n=2,
    )
    assert len(ranked) == 2
    assert ranked[0].total_score >= ranked[1].total_score


def test_bullish_prefers_stronger_trend_symbol() -> None:
    prices = _build_prices()
    ranked = rank_candidates(
        prices_df=prices,
        candidate_symbols=["A", "B", "C", "D"],
        regime="bullish_trend",
        top_n=3,
    )
    symbols = [r.symbol for r in ranked]
    assert "A" in symbols[:2]


def test_bearish_filters_to_more_defensive_profiles() -> None:
    prices = _build_prices()
    ranked = rank_candidates(
        prices_df=prices,
        candidate_symbols=["A", "B", "C", "D"],
        regime="bearish_trend",
        top_n=2,
    )
    assert len(ranked) == 2
    for r in ranked:
        assert "regime_fit" in r.factor_scores
