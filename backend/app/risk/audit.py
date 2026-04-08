"""주문별 리스크 스냅샷·판정 영구 기록 (JSONL)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.orders.models import OrderRequest
from app.risk.rules import RiskDecision, RiskSnapshot

_lock = threading.Lock()


def risk_snapshot_to_jsonable(snapshot: RiskSnapshot) -> dict[str, Any]:
    return {
        "daily_pnl_pct": snapshot.daily_pnl_pct,
        "total_pnl_pct": snapshot.total_pnl_pct,
        "equity": snapshot.equity,
        "market_filter_ok": snapshot.market_filter_ok,
        "position_values": dict(snapshot.position_values),
        "market_regime": snapshot.market_regime,
        "recent_trade_pnls": list(snapshot.recent_trade_pnls),
        "consecutive_losses": snapshot.consecutive_losses,
        "latest_entry_score": snapshot.latest_entry_score,
        "todays_new_entries": snapshot.todays_new_entries,
        "trading_cooldown_until": snapshot.trading_cooldown_until.isoformat()
        if snapshot.trading_cooldown_until
        else None,
        "cooldown_until": {k: v.isoformat() for k, v in snapshot.cooldown_until.items()},
    }


def append_order_risk_audit(path: str | Path, order: OrderRequest, snapshot: RiskSnapshot, decision: RiskDecision) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": order.symbol,
        "side": order.side,
        "quantity": order.quantity,
        "price": order.price,
        "stop_loss_pct": order.stop_loss_pct,
        "strategy_id": order.strategy_id,
        "signal_id": order.signal_id,
        "decision": {
            "approved": decision.approved,
            "reason_code": decision.reason_code,
            "reason": decision.reason,
            "is_hard_stop": decision.is_hard_stop,
        },
        "snapshot": risk_snapshot_to_jsonable(snapshot),
    }
    line = json.dumps(row, ensure_ascii=False)
    with _lock:
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def append_risk_event(path: str | Path, event: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, ensure_ascii=False)
    with _lock:
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def read_jsonl_tail(path: str | Path, *, max_lines: int = 100) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-max_lines:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
