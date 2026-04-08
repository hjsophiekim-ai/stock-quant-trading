"""KIS 모의 주문 엔진 API (추적·미체결·동기화)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException

from app.orders.models import OrderSignal
from backend.app.core.config import get_backend_settings
from backend.app.orders import build_kis_mock_execution_engine
from backend.app.orders.order_store import TrackedOrderStore

router = APIRouter(prefix="/order-engine", tags=["order-engine"])


def _store_only() -> TrackedOrderStore:
    return TrackedOrderStore(get_backend_settings().order_tracked_store_json)


@router.get("/tracked")
def list_tracked_orders() -> dict[str, Any]:
    store = _store_only()
    rows = [asdict(r) for r in store.list_all()]
    return {"items": rows[-200:], "count": len(rows)}


@router.get("/broker-open")
def list_broker_open_orders() -> dict[str, Any]:
    try:
        eng = build_kis_mock_execution_engine()
        oo = eng.get_broker().get_open_orders()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "items": [
            {
                "order_id": o.order_id,
                "symbol": o.symbol,
                "side": o.side,
                "quantity": o.quantity,
                "remaining_quantity": o.remaining_quantity,
                "price": o.price,
                "created_at": o.created_at.isoformat(),
            }
            for o in oo
        ],
        "count": len(oo),
    }


@router.post("/sync")
def sync_tracked_with_broker() -> dict[str, Any]:
    try:
        eng = build_kis_mock_execution_engine()
        n = eng.sync_open_orders_with_broker()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"updated": n}


@router.post("/cleanup-stale")
def cleanup_stale_orders() -> dict[str, Any]:
    try:
        eng = build_kis_mock_execution_engine()
        ids = eng.cleanup_stale_submitted()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"cleaned_order_ids": ids, "count": len(ids)}


@router.post("/maintenance")
def order_engine_maintenance() -> dict[str, Any]:
    """동기화 + 오래된 미체결 정리(스케줄러에서 주기 호출 권장)."""
    try:
        eng = build_kis_mock_execution_engine()
        synced = eng.sync_open_orders_with_broker()
        cleaned = eng.cleanup_stale_submitted()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"synced_records": synced, "cleaned_order_ids": cleaned, "cleaned_count": len(cleaned)}


@router.post("/execute-signal")
def execute_signal_sample(body: dict[str, Any]) -> dict[str, Any]:
    """
    디버그/수동용: 단일 OrderSignal 을 리스크+KIS 로 전송.
    body: symbol, side, quantity, limit_price?, stop_loss_pct?, strategy_id?, signal_id?
    """
    from app.risk.rules import RiskSnapshot

    sym = str(body.get("symbol") or "").strip()
    side = str(body.get("side") or "buy").lower()
    qty = int(body.get("quantity") or 0)
    if not sym or qty <= 0 or side not in {"buy", "sell"}:
        raise HTTPException(status_code=400, detail="symbol, quantity, side required")
    price = body.get("limit_price")
    lp = float(price) if price is not None else None
    sl = body.get("stop_loss_pct")
    slp = float(sl) if sl is not None else None
    sig = OrderSignal(
        symbol=sym,
        side=side,
        quantity=qty,
        limit_price=lp,
        stop_loss_pct=slp,
        strategy_id=str(body.get("strategy_id") or "api_manual"),
        signal_id=str(body.get("signal_id") or "") or None,
    )
    snap = RiskSnapshot(
        daily_pnl_pct=float(body.get("daily_pnl_pct") or 0),
        total_pnl_pct=float(body.get("total_pnl_pct") or 0),
        equity=float(body.get("equity") or 1_000_000),
        market_filter_ok=bool(body.get("market_filter_ok", True)),
        position_values=dict(body.get("position_values") or {}),
        market_regime=str(body.get("market_regime") or "sideways"),
    )
    try:
        eng = build_kis_mock_execution_engine()
        res = eng.process_signal_tracked(sig, snap)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "accepted": res.accepted,
        "order_id": res.order_id,
        "message": res.message,
        "status": str(res.status),
        "metadata": res.metadata,
    }
