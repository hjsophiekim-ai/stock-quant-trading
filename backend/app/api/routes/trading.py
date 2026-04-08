from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query

from backend.app.core.config import get_backend_settings
from backend.app.portfolio.sync_engine import read_jsonl_tail

router = APIRouter(prefix="/trading", tags=["trading"])


@router.get("/mode")
def get_mode() -> dict[str, str]:
    return {"default_mode": "paper", "live_status": "locked"}


@router.get("/orders")
def get_orders() -> dict[str, list[dict[str, str]]]:
    return {"items": []}


@router.get("/recent-trades")
def recent_trades(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, object]:
    """포트폴리오 동기화가 적재한 `fills.jsonl` 기반 최근 체결(없으면 빈 목록)."""
    cfg = get_backend_settings()
    p = Path(cfg.portfolio_data_dir) / "fills.jsonl"
    raw = read_jsonl_tail(p, max_lines=min(2000, limit * 5))
    items: list[dict[str, object]] = []
    for r in reversed(raw):
        if len(items) >= limit:
            break
        eid = str(r.get("exec_id") or "")
        odt = str(r.get("ord_dt") or "")
        otm = str(r.get("ord_tmd") or "").ljust(6, "0")[:6]
        filled_at = ""
        if len(odt) == 8 and len(otm) >= 6:
            filled_at = f"{odt[:4]}-{odt[4:6]}-{odt[6:8]}T{otm[:2]}:{otm[2:4]}:{otm[4:6]}+09:00"
        items.append(
            {
                "trade_id": eid or f"fill-{odt}-{otm}",
                "symbol": r.get("symbol"),
                "side": r.get("side"),
                "quantity": r.get("quantity"),
                "price": r.get("price"),
                "filled_at": filled_at or odt + otm,
                "status": "filled",
                "strategy_id": r.get("strategy_id"),
                "order_no": r.get("order_no"),
            }
        )
    return {"items": items, "source": "portfolio_fills", "count": len(items)}
