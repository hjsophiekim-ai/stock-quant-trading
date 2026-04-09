"""백엔드 리스크 API·감사·설정 브리지 (핵심 규칙은 app.risk).

`live_unlock_gate` 등 하위 모듈만 필요할 때 무거운 service 로딩을 피하도록 지연 로딩합니다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = [
    "append_order_risk_audit",
    "append_risk_event",
    "read_jsonl_tail",
    "risk_snapshot_to_jsonable",
    "build_public_risk_status",
    "install_risk_audit_from_settings",
]

if TYPE_CHECKING:
    from backend.app.risk.audit import append_order_risk_audit as append_order_risk_audit
    from backend.app.risk.audit import append_risk_event as append_risk_event
    from backend.app.risk.audit import read_jsonl_tail as read_jsonl_tail
    from backend.app.risk.audit import risk_snapshot_to_jsonable as risk_snapshot_to_jsonable


def __getattr__(name: str) -> Any:
    if name in (
        "append_order_risk_audit",
        "append_risk_event",
        "read_jsonl_tail",
        "risk_snapshot_to_jsonable",
    ):
        from backend.app.risk import audit as _audit

        return getattr(_audit, name)
    if name in ("build_public_risk_status", "install_risk_audit_from_settings"):
        from backend.app.risk import service as _service

        return getattr(_service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
