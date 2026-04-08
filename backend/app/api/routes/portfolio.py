"""포트폴리오 요약·손익·체결 이력 (KIS 모의 동기화 결과)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.app.core.config import get_backend_settings
from backend.app.portfolio.sync_engine import load_last_snapshot, read_jsonl_tail, run_portfolio_sync

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _fills_path() -> Path:
    return Path(get_backend_settings().portfolio_data_dir) / "fills.jsonl"


def _pnl_hist_path() -> Path:
    return Path(get_backend_settings().portfolio_data_dir) / "pnl_history.jsonl"


@router.get("/summary")
def portfolio_summary() -> dict[str, Any]:
    snap = load_last_snapshot()
    if not snap:
        raise HTTPException(
            status_code=404,
            detail="No portfolio snapshot yet. POST /api/portfolio/sync first.",
        )
    return snap


@router.post("/sync")
def portfolio_sync(
    backfill_days: int | None = Query(default=None, ge=1, le=365),
) -> dict[str, Any]:
    s = get_backend_settings()
    days = int(backfill_days) if backfill_days is not None else s.portfolio_sync_backfill_days
    try:
        result = run_portfolio_sync(backfill_days=days, settings=s)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not result.ok:
        raise HTTPException(status_code=503, detail=result.message)
    return {"ok": True, "snapshot": result.snapshot}


@router.get("/pnl-history")
def pnl_history(limit: int = Query(default=200, ge=1, le=5000)) -> dict[str, Any]:
    rows = read_jsonl_tail(_pnl_hist_path(), max_lines=limit)
    return {"items": rows, "count": len(rows)}


@router.get("/fills-history")
def fills_history(limit: int = Query(default=500, ge=1, le=10000)) -> dict[str, Any]:
    rows = read_jsonl_tail(_fills_path(), max_lines=limit)
    return {"items": rows, "count": len(rows)}


@router.get("/pnl-by-symbol")
def pnl_by_symbol() -> dict[str, Any]:
    snap = load_last_snapshot()
    if not snap:
        raise HTTPException(status_code=404, detail="No portfolio snapshot")
    per = snap.get("per_symbol") or {}
    return {"items": per, "count": len(per)}


@router.get("/pnl-by-strategy")
def pnl_by_strategy() -> dict[str, Any]:
    snap = load_last_snapshot()
    if not snap:
        raise HTTPException(status_code=404, detail="No portfolio snapshot")
    per = snap.get("per_strategy") or {}
    return {"items": per, "count": len(per)}


@router.get("/sync-status")
def portfolio_sync_status() -> dict[str, Any]:
    """연속 동기화 실패 횟수·risk 검토 플래그."""
    s = get_backend_settings()
    root = Path(s.portfolio_data_dir)
    fail = root / "sync_failures.json"
    flag = root / "sync_risk_review.flag"
    data: dict[str, Any] = {}
    if fail.is_file():
        try:
            data = json.loads(fail.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    return {
        "consecutive_failures": int(data.get("consecutive_failures") or 0),
        "last_error": data.get("last_error") or "",
        "last_at_utc": data.get("last_at_utc") or "",
        "risk_review_flag": flag.is_file(),
        "sync_interval_sec": s.portfolio_sync_interval_sec,
    }
