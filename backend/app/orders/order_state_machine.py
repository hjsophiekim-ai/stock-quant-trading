"""
주문 상태 전이 (이벤트 기반).

상태: created, approved, submitted, partially_filled, filled, cancelled, rejected, failed
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

OrderEngineState = Literal[
    "created",
    "approved",
    "submitted",
    "partially_filled",
    "filled",
    "cancelled",
    "rejected",
    "failed",
]


class OrderEngineEvent(StrEnum):
    RISK_APPROVED = "risk_approved"
    RISK_REJECTED = "risk_rejected"
    BROKER_ACCEPTED = "broker_accepted"
    BROKER_REJECTED = "broker_rejected"
    PARTIAL_FILL = "partial_fill"
    FULL_FILL = "full_fill"
    CANCELLED = "cancelled"
    RETRY_EXHAUSTED = "retry_exhausted"
    TIMEOUT_ABORT = "timeout_abort"
    STALE_CLEANUP = "stale_cleanup"


_TRANSITIONS: dict[tuple[str, str], OrderEngineState] = {
    ("created", OrderEngineEvent.RISK_APPROVED): "approved",
    ("created", OrderEngineEvent.RISK_REJECTED): "rejected",
    ("created", OrderEngineEvent.TIMEOUT_ABORT): "failed",
    ("approved", OrderEngineEvent.BROKER_ACCEPTED): "submitted",
    ("approved", OrderEngineEvent.BROKER_REJECTED): "failed",
    ("approved", OrderEngineEvent.RETRY_EXHAUSTED): "failed",
    ("approved", OrderEngineEvent.TIMEOUT_ABORT): "failed",
    ("submitted", OrderEngineEvent.PARTIAL_FILL): "partially_filled",
    ("submitted", OrderEngineEvent.FULL_FILL): "filled",
    ("submitted", OrderEngineEvent.CANCELLED): "cancelled",
    ("submitted", OrderEngineEvent.STALE_CLEANUP): "cancelled",
    ("submitted", OrderEngineEvent.TIMEOUT_ABORT): "failed",
    ("partially_filled", OrderEngineEvent.PARTIAL_FILL): "partially_filled",
    ("partially_filled", OrderEngineEvent.FULL_FILL): "filled",
    ("partially_filled", OrderEngineEvent.CANCELLED): "cancelled",
    ("partially_filled", OrderEngineEvent.STALE_CLEANUP): "cancelled",
    ("partially_filled", OrderEngineEvent.TIMEOUT_ABORT): "failed",
}


def transition(current: OrderEngineState, event: OrderEngineEvent) -> OrderEngineState | None:
    return _TRANSITIONS.get((current, event))
