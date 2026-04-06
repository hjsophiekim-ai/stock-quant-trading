from __future__ import annotations

from dataclasses import dataclass

from app.orders.models import OrderRequest, OrderResult, OrderStatus, OrderSignal
from app.risk.rules import RiskSnapshot


@dataclass(frozen=True)
class ExecutionStep:
    step: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class ExecutionReport:
    signal_id: str | None
    accepted: bool
    steps: list[ExecutionStep]
    result: OrderResult | None


def split_order(order: OrderRequest, parts: int) -> list[OrderRequest]:
    if parts <= 1 or order.quantity <= 1:
        return [order]
    base_qty = max(order.quantity // parts, 1)
    chunks: list[OrderRequest] = []
    remaining = order.quantity
    for _ in range(parts - 1):
        chunks.append(OrderRequest(symbol=order.symbol, side=order.side, quantity=base_qty, price=order.price, stop_loss_pct=order.stop_loss_pct))
        remaining -= base_qty
    chunks.append(OrderRequest(symbol=order.symbol, side=order.side, quantity=remaining, price=order.price, stop_loss_pct=order.stop_loss_pct))
    return chunks


def signal_to_order(signal: OrderSignal) -> OrderRequest:
    return OrderRequest(
        symbol=signal.symbol,
        side=signal.side,
        quantity=signal.quantity,
        price=signal.limit_price,
        stop_loss_pct=signal.stop_loss_pct,
        strategy_id=signal.strategy_id,
        signal_id=signal.signal_id,
    )


def execute_signal_with_manager(
    *,
    order_manager: object,
    signal: OrderSignal,
    snapshot: RiskSnapshot,
) -> ExecutionReport:
    """
    Generic orchestration helper for:
    strategy signal -> risk approval -> order submit.
    `order_manager` must expose `evaluate_signal` and `submit`.
    """
    steps: list[ExecutionStep] = []
    order = signal_to_order(signal)
    steps.append(ExecutionStep(step="order_created", ok=True, detail=f"{order.symbol}/{order.side}/{order.quantity}"))

    intent = order_manager.evaluate_signal(signal, snapshot)
    if not intent.approved:
        steps.append(ExecutionStep(step="risk_approval", ok=False, detail=f"{intent.reason_code}: {intent.reason}"))
        return ExecutionReport(signal_id=signal.signal_id, accepted=False, steps=steps, result=None)

    steps.append(ExecutionStep(step="risk_approval", ok=True, detail=f"{intent.reason_code}: {intent.reason}"))
    result = order_manager.submit(order, snapshot)
    steps.append(ExecutionStep(step="order_submit", ok=result.accepted, detail=result.message))
    return ExecutionReport(signal_id=signal.signal_id, accepted=result.accepted, steps=steps, result=result)


def normalize_rejected_result(message: str) -> OrderResult:
    return OrderResult(order_id="", accepted=False, message=message, status=OrderStatus.REJECTED_RISK)
