"""
Paper 멀티 전략(스윙 일봉 + 인트라데이 스캘프) 라우팅·자금 버킷(노셔널) 계산.

- 실제 현금은 브로커 단일 풀; 버킷은 신호·수량 산정용 가이드(순차 틱에서 스윙 → 단타).
- 종목 중복 시 한 레그만 배정(기본: 스캘프 우선).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _parse_csv(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


@dataclass(frozen=True)
class MultiLegRouteResult:
    swing_symbols: list[str]
    scalp_symbols: list[str]
    diagnostics: list[dict[str, Any]]


def route_swing_vs_scalp_symbols(
    *,
    swing_csv: str,
    intraday_symbols: list[str],
    prefer_scalp_on_overlap: bool = True,
) -> MultiLegRouteResult:
    """스윙 후보(PAPER_TRADING_SYMBOLS)와 인트라데이 후보의 교집합을 한쪽으로만 배정."""
    swing = set(_parse_csv(swing_csv))
    scalp = set(str(x).strip() for x in intraday_symbols if str(x).strip())
    overlap = swing & scalp
    diag: list[dict[str, Any]] = []
    swing_only = set(swing)
    scalp_only = set(scalp)
    for sym in sorted(overlap):
        if prefer_scalp_on_overlap:
            swing_only.discard(sym)
            diag.append(
                {
                    "symbol": sym,
                    "assigned_leg": "scalp",
                    "reason": "both_universes_priority_scalp",
                }
            )
        else:
            scalp_only.discard(sym)
            diag.append(
                {
                    "symbol": sym,
                    "assigned_leg": "swing",
                    "reason": "both_universes_priority_swing",
                }
            )
    return MultiLegRouteResult(
        swing_symbols=sorted(swing_only),
        scalp_symbols=sorted(scalp_only),
        diagnostics=diag,
    )


def notionals_for_legs(
    *,
    equity_krw: float,
    cash_krw: float,
    swing_pct: float,
    intraday_pct: float,
) -> dict[str, float]:
    """레그별 가용 노셔널(원). 현금이 더 작으면 현금 비율로 축소."""
    eq = max(0.0, float(equity_krw))
    cash = max(0.0, float(cash_krw))
    sp = max(0.0, float(swing_pct))
    ip = max(0.0, float(intraday_pct))
    denom = sp + ip
    if denom <= 0:
        return {"swing_notional_krw": 0.0, "intraday_notional_krw": 0.0, "cash_krw": cash, "equity_krw": eq}
    swing_target = eq * (sp / denom)
    intra_target = eq * (ip / denom)
    if cash <= 0:
        return {"swing_notional_krw": 0.0, "intraday_notional_krw": 0.0, "cash_krw": cash, "equity_krw": eq}
    if swing_target + intra_target <= cash:
        return {
            "swing_notional_krw": swing_target,
            "intraday_notional_krw": intra_target,
            "cash_krw": cash,
            "equity_krw": eq,
        }
    scale = cash / (swing_target + intra_target)
    return {
        "swing_notional_krw": swing_target * scale,
        "intraday_notional_krw": intra_target * scale,
        "cash_krw": cash,
        "equity_krw": eq,
    }
