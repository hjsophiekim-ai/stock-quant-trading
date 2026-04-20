from __future__ import annotations

import pandas as pd

from app.config import get_settings
from app.strategy.market_mode_engine import (
    classify_auto_market_mode,
    compose_paper_market_mode_bundle,
    normalize_manual_mode,
    resolve_market_mode,
)
from app.strategy.market_mode_policy import compose_effective_policy


def _trending_kospi() -> pd.DataFrame:
    rows = []
    base = 2500.0
    for i in range(80):
        base *= 1.004
        rows.append({"date": pd.Timestamp(f"2024-01-{1 + (i % 28):02d}"), "close": base})
    return pd.DataFrame(rows)


def test_normalize_manual_mode() -> None:
    assert normalize_manual_mode("AUTO") == "auto"
    assert normalize_manual_mode("Defensive") == "defensive"
    assert normalize_manual_mode("nope") == "auto"


def test_resolve_manual_overrides_auto() -> None:
    auto_blob = {"auto_market_mode": "defensive", "auto_market_mode_reason": "weak"}
    m, src, reason = resolve_market_mode(manual="aggressive", auto_blob=auto_blob)  # type: ignore[arg-type]
    assert m == "aggressive"
    assert src == "manual_override"
    assert "manual" in reason.lower()


def test_resolve_auto_uses_auto_blob() -> None:
    auto_blob = {"auto_market_mode": "neutral", "auto_market_mode_reason": "x"}
    m, src, reason = resolve_market_mode(manual="auto", auto_blob=auto_blob)  # type: ignore[arg-type]
    assert m == "neutral"
    assert src == "auto"
    assert reason == "x"


def test_auto_mode_classifies_three_modes() -> None:
    k = _trending_kospi()
    sp = k.copy()
    vol = pd.DataFrame({"date": k["date"], "value": 16.0})
    out = classify_auto_market_mode(kospi=k, sp500=sp, volatility=vol)
    assert out["auto_market_mode"] in ("aggressive", "neutral", "defensive")
    assert isinstance(float(out["market_mode_score"]), float)


def test_compose_bundle_has_policy_and_status() -> None:
    k = _trending_kospi()
    sp = k.copy()
    vol = pd.DataFrame({"date": k["date"], "value": 16.0})
    b = compose_paper_market_mode_bundle(
        manual_selection="auto",
        kospi=k,
        sp500=sp,
        volatility=vol,
        settings=get_settings(),
    )
    assert b.get("market_mode_active") in ("aggressive", "neutral", "defensive")
    assert b.get("policy", {}).get("final_betting")
    assert isinstance(b.get("status_line"), str)


def test_final_betting_policy_aggressive_vs_defensive() -> None:
    cfg = get_settings()
    a = compose_effective_policy(active_mode="aggressive", cfg=cfg)["final_betting"]
    d = compose_effective_policy(active_mode="defensive", cfg=cfg)["final_betting"]
    assert float(a["us_night_hard_delta"]) < float(d["us_night_hard_delta"])
    assert int(a["max_new_positions_delta"]) > int(d["max_new_positions_delta"])


def test_final_betting_aggressive_materially_easier_than_neutral() -> None:
    """Aggressive must widen FB gates vs neutral by a clear margin (not cosmetic)."""
    cfg = get_settings()
    a = compose_effective_policy(active_mode="aggressive", cfg=cfg)["final_betting"]
    n = compose_effective_policy(active_mode="neutral", cfg=cfg)["final_betting"]
    assert float(a["kospi_hard_delta"]) <= float(n["kospi_hard_delta"]) - 0.35
    assert float(a["us_night_hard_delta"]) <= float(n["us_night_hard_delta"]) - 0.35
    assert int(a["rank_pool_delta"]) >= int(n["rank_pool_delta"]) + 3
