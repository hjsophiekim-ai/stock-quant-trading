"""
Paper market adaptation: 3-mode (aggressive / neutral / defensive) + auto classifier.

Manual UI selection: auto | aggressive | neutral | defensive.
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from app.config import Settings
from app.strategy.market_regime import MarketRegimeConfig, MarketRegimeInputs, classify_market_regime
from app.strategy.market_mode_policy import ManualMarketMode, MarketMode, compose_effective_policy, kospi_realized_vol_stress

MarketModeSource = Literal["auto", "manual_override"]


def normalize_manual_mode(raw: str | None) -> ManualMarketMode:
    s = (raw or "auto").strip().lower()
    if s in ("auto", "aggressive", "neutral", "defensive"):
        return s  # type: ignore[return-value]
    return "auto"


def normalize_active_mode(raw: str | None) -> MarketMode:
    s = (raw or "neutral").strip().lower()
    if s in ("aggressive", "neutral", "defensive"):
        return s  # type: ignore[return-value]
    return "neutral"


def _auto_mode_from_regime_and_scores(
    *,
    regime: str,
    kospi_ret: float,
    k20: float,
    k60: float,
    vol_level: float,
    vol_change_pct: float,
    kospi_rv_stress: float,
) -> tuple[MarketMode, float, str]:
    """
    Composite score roughly in [-12, 12]; mapped to 3 modes.
    high_volatility_risk -> always defensive (capital protection).
    """
    if regime == "high_volatility_risk":
        return (
            "defensive",
            -8.0,
            "auto: regime=high_volatility_risk (volatility / shock risk)",
        )

    score = 0.0
    score += float(kospi_ret) * 0.12
    score += (float(k20) + float(k60)) * 0.85
    if regime == "bullish_trend":
        score += 3.2
    elif regime == "bearish_trend":
        score -= 3.8
    elif regime == "sideways":
        score -= 0.9

    vol_pen = max(0.0, float(vol_level) - 18.0) * 0.12
    vol_pen += max(0.0, float(vol_change_pct) - 1.5) * 0.25
    vol_pen += max(0.0, float(kospi_rv_stress) - 14.0) * 0.18
    score -= vol_pen

    if score >= 3.2:
        mode: MarketMode = "aggressive"
        reason = f"auto: composite={score:.2f} (strong tape / positive KOSPI dynamics)"
    elif score <= -3.2:
        mode = "defensive"
        reason = f"auto: composite={score:.2f} (weak trend / elevated stress)"
    else:
        mode = "neutral"
        reason = f"auto: composite={score:.2f} (mixed / sideways bias)"

    return mode, float(score), reason


def classify_auto_market_mode(
    *,
    kospi: pd.DataFrame,
    sp500: pd.DataFrame,
    volatility: pd.DataFrame,
    regime_config: MarketRegimeConfig | None = None,
) -> dict[str, Any]:
    rcfg = regime_config or MarketRegimeConfig()
    mr = classify_market_regime(
        MarketRegimeInputs(kospi=kospi, sp500=sp500, volatility=volatility),
        rcfg,
    )
    f = mr.features
    rv_stress = kospi_realized_vol_stress(kospi)
    mode, sc, reason = _auto_mode_from_regime_and_scores(
        regime=mr.regime,
        kospi_ret=float(f.kospi_return_pct),
        k20=float(f.kospi_ma20_slope_pct),
        k60=float(f.kospi_ma60_slope_pct),
        vol_level=float(f.volatility_level),
        vol_change_pct=float(f.volatility_change_pct),
        kospi_rv_stress=rv_stress,
    )
    return {
        "auto_market_mode": mode,
        "market_mode_score": round(sc, 4),
        "auto_market_mode_reason": reason,
        "underlying_regime": mr.regime,
        "kospi_return_pct": round(float(f.kospi_return_pct), 4),
        "kospi_ma20_slope_pct": round(float(f.kospi_ma20_slope_pct), 4),
        "kospi_ma60_slope_pct": round(float(f.kospi_ma60_slope_pct), 4),
        "volatility_level": round(float(f.volatility_level), 4),
        "volatility_change_pct": round(float(f.volatility_change_pct), 4),
        "kospi_realized_vol_stress": round(float(rv_stress), 4),
        "volatility_risk_score": round(
            max(0.0, float(f.volatility_level) - 14.0) * 0.35 + max(0.0, rv_stress - 14.0) * 0.2,
            4,
        ),
        "kospi_trend_score": round(float(f.kospi_return_pct) * 0.12 + (float(f.kospi_ma20_slope_pct) + float(f.kospi_ma60_slope_pct)) * 0.85, 4),
    }


def resolve_market_mode(*, manual: ManualMarketMode, auto_blob: dict[str, Any]) -> tuple[MarketMode, MarketModeSource, str]:
    auto_m = normalize_active_mode(str(auto_blob.get("auto_market_mode") or "neutral"))
    if manual == "auto":
        return auto_m, "auto", str(auto_blob.get("auto_market_mode_reason") or "")
    m = normalize_active_mode(manual)
    return m, "manual_override", f"manual_override: forced {m}"


def build_status_line(*, active: MarketMode, source: MarketModeSource, auto_reason: str, manual: ManualMarketMode) -> str:
    if source == "manual_override":
        return f"Manual mode override: {active.capitalize()}"
    return f"Auto mode: {active.capitalize()} ({auto_reason})"


def compose_paper_market_mode_bundle(
    *,
    manual_selection: str | None,
    kospi: pd.DataFrame,
    sp500: pd.DataFrame,
    volatility: pd.DataFrame,
    settings: Settings,
    regime_config: MarketRegimeConfig | None = None,
) -> dict[str, Any]:
    manual = normalize_manual_mode(manual_selection)
    auto_blob = classify_auto_market_mode(
        kospi=kospi,
        sp500=sp500,
        volatility=volatility,
        regime_config=regime_config,
    )
    active, source, reason = resolve_market_mode(manual=manual, auto_blob=auto_blob)
    pol = compose_effective_policy(active_mode=active, cfg=settings)
    status = build_status_line(
        active=active,
        source=source,
        auto_reason=str(auto_blob.get("auto_market_mode_reason") or ""),
        manual=manual,
    )
    out: dict[str, Any] = {
        "market_mode_active": active,
        "market_mode_source": source,
        "market_mode_reason": reason,
        "market_mode_score": auto_blob.get("market_mode_score"),
        "manual_market_mode_override": manual,
        "auto_market_mode": auto_blob.get("auto_market_mode"),
        "auto_market_mode_reason": auto_blob.get("auto_market_mode_reason"),
        "underlying_regime": auto_blob.get("underlying_regime"),
        "kospi_trend_score": auto_blob.get("kospi_trend_score"),
        "volatility_risk_score": auto_blob.get("volatility_risk_score"),
        "kospi_realized_vol_stress": auto_blob.get("kospi_realized_vol_stress"),
        "status_line": status,
        "policy": pol,
    }
    return out


def attach_market_mode_to_strategy(
    strategy: Any,
    *,
    manual: str | None,
    kospi: pd.DataFrame,
    sp500: pd.DataFrame,
    volatility: pd.DataFrame,
    settings: Settings,
) -> dict[str, Any]:
    rcfg = getattr(strategy, "regime_config", None)
    bundle = compose_paper_market_mode_bundle(
        manual_selection=manual,
        kospi=kospi,
        sp500=sp500,
        volatility=volatility,
        settings=settings,
        regime_config=rcfg if isinstance(rcfg, MarketRegimeConfig) else None,
    )
    setattr(strategy, "_paper_market_mode_snapshot", bundle)
    return bundle
