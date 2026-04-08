"""주문 리스크 판정 감사 로깅용 훅 (백엔드가 콜백 등록)."""

from __future__ import annotations

from typing import Any, Callable

from app.orders.models import OrderRequest
from app.risk.rules import RiskDecision, RiskSnapshot

RiskAuditFn = Callable[[OrderRequest, RiskSnapshot, RiskDecision], None]

_callback: RiskAuditFn | None = None


def register_risk_audit_callback(fn: RiskAuditFn | None) -> None:
    global _callback
    _callback = fn


def emit_risk_audit(order: OrderRequest, snapshot: RiskSnapshot, decision: RiskDecision) -> None:
    if _callback is None:
        return
    try:
        _callback(order, snapshot, decision)
    except Exception:
        pass
