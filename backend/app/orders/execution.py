"""
엔드투엔드 실행: 신호 → (엔진) 리스크+KIS+추적.

`execute_signal_with_manager`(app)와 병행하되, 추적·재시도는 `KisMockExecutionEngine` 사용 시에만 기록됩니다.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.orders.execution import ExecutionStep
from app.orders.models import OrderResult, OrderSignal
from app.risk.rules import RiskSnapshot

from backend.app.orders.order_manager import KisMockExecutionEngine


@dataclass(frozen=True)
class TrackedExecutionReport:
    signal_id: str | None
    accepted: bool
    steps: list[ExecutionStep]
    result: OrderResult | None


def execute_signal_with_kis_engine(
    *,
    engine: KisMockExecutionEngine,
    signal: OrderSignal,
    snapshot: RiskSnapshot,
) -> TrackedExecutionReport:
    steps: list[ExecutionStep] = []
    order = engine.create_order_from_signal(signal)
    steps.append(ExecutionStep(step="order_created", ok=True, detail=f"{order.symbol}/{order.side}/{order.quantity}"))

    result = engine.process_signal_tracked(signal, snapshot)
    if not result.accepted:
        steps.append(
            ExecutionStep(
                step="risk_or_broker",
                ok=False,
                detail=result.message,
            )
        )
        return TrackedExecutionReport(signal_id=signal.signal_id, accepted=False, steps=steps, result=result)

    steps.append(ExecutionStep(step="risk_approval_and_submit", ok=True, detail=result.message))
    return TrackedExecutionReport(signal_id=signal.signal_id, accepted=True, steps=steps, result=result)
