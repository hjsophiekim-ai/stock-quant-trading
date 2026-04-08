"""종목 스크리닝 스냅샷 조회·수동 갱신."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.strategy.screener import ScreeningSnapshot, get_screener_engine

router = APIRouter(prefix="/screening", tags=["screening"])


def _snapshot_payload(snap: ScreeningSnapshot | None) -> dict[str, Any]:
    if snap is None:
        return {
            "status": "empty",
            "message": "스크리닝 미실행. POST /api/screening/refresh 로 갱신하세요.",
        }
    return {
        "status": "ok" if not snap.blocked else "blocked",
        "updated_at_utc": snap.updated_at_utc,
        "regime": snap.regime,
        "regime_detail": snap.regime_detail,
        "regime_adjustment_reasons": snap.regime_adjustment_reasons,
        "blocked": snap.blocked,
        "block_reason": snap.block_reason,
        "universe_symbols": snap.universe_symbols,
        "candidates": snap.candidates,
        "filter_audit": snap.filter_audit,
        "top_n_effective": snap.top_n_effective,
        "return_percentile_threshold_pct": snap.return_percentile_threshold_pct,
    }


@router.get("/latest")
def get_latest_screening() -> dict[str, Any]:
    snap = get_screener_engine().get_snapshot()
    return _snapshot_payload(snap)


@router.post("/refresh")
def refresh_screening() -> dict[str, Any]:
    try:
        snap = get_screener_engine().refresh()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"screener refresh failed: {exc}") from exc
    return _snapshot_payload(snap)
