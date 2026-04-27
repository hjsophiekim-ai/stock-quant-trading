from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LiveCandidateScore:
    symbol: str
    score: float
    reason: str


def score_candidate(
    *,
    symbol: str,
    order_price: float | None,
    market_mode: dict[str, Any] | None,
    already_holding: bool,
    has_open_order: bool,
    rr_proxy: float | None = None,
    liquidity_proxy: float | None = None,
    volatility_proxy: float | None = None,
) -> LiveCandidateScore:
    sym = str(symbol or "").strip()
    if not sym:
        return LiveCandidateScore(symbol="", score=-999.0, reason="empty_symbol")

    mode = (market_mode or {}).get("market_mode_active") if isinstance(market_mode, dict) else None
    mode = str(mode or "").strip().lower()

    score = 0.0
    parts: list[str] = []

    if mode == "aggressive":
        score += 0.8
        parts.append("mode=aggressive +0.8")
    elif mode == "defensive":
        score -= 0.9
        parts.append("mode=defensive -0.9")
    else:
        parts.append(f"mode={mode or 'neutral'} +0.0")

    if already_holding:
        score -= 2.5
        parts.append("already_holding -2.5")
    if has_open_order:
        score -= 3.5
        parts.append("duplicate_open_order -3.5")

    if rr_proxy is not None:
        rr = float(rr_proxy)
        score += max(-1.0, min(1.2, rr - 1.0))
        parts.append(f"rr_proxy={rr:.2f}")
    if liquidity_proxy is not None:
        liq = float(liquidity_proxy)
        score += max(-0.8, min(0.8, liq))
        parts.append(f"liquidity={liq:.2f}")
    if volatility_proxy is not None:
        vol = float(volatility_proxy)
        score -= max(0.0, min(1.2, vol))
        parts.append(f"volatility_penalty={vol:.2f}")

    if order_price is None or float(order_price or 0.0) <= 0:
        score -= 0.4
        parts.append("missing_price -0.4")

    return LiveCandidateScore(symbol=sym, score=float(score), reason="; ".join(parts)[:600])

