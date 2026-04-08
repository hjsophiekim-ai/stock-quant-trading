"""
KIS 모의투자와 직접 연결되는 주문 오케스트레이션.

전략 신호 → 리스크 → 재시도·타임아웃 정책 → KisPaperBroker → 상태 저장.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.brokers.base_broker import BaseBroker
from app.clients.kis_client import KISClientError
from app.orders.models import OrderRequest, OrderResult, OrderSignal, OrderStatus
from app.orders.order_manager import OrderManager
from app.risk.rules import RiskRules, RiskSnapshot

from backend.app.orders.order_state_machine import OrderEngineEvent, transition
from backend.app.orders.order_store import TrackedOrderRecord, TrackedOrderStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrderRetryPolicy:
    max_attempts: int = 3
    backoff_base_sec: float = 0.6


@dataclass(frozen=True)
class OrderTimeoutPolicy:
    """stale_submitted: 브로커 미체결로 오래 남은 내부 레코드 정리 기준."""

    stale_submitted_minutes: float = 180.0


class KisMockExecutionEngine:
    """
    `OrderManager` + `TrackedOrderStore` + 상태 전이.
    브로커는 반드시 모의투자용 `KisPaperBroker` 등 `BaseBroker` 구현.
    """

    def __init__(
        self,
        *,
        broker: BaseBroker,
        risk_rules: RiskRules,
        store: TrackedOrderStore,
        retry_policy: OrderRetryPolicy | None = None,
        timeout_policy: OrderTimeoutPolicy | None = None,
    ) -> None:
        self._inner = OrderManager(broker=broker, risk_rules=risk_rules)
        self.store = store
        self.retry_policy = retry_policy or OrderRetryPolicy()
        self.timeout_policy = timeout_policy or OrderTimeoutPolicy()

    def create_order_from_signal(self, signal: OrderSignal) -> OrderRequest:
        return self._inner.create_order_from_signal(signal)

    def get_broker(self) -> BaseBroker:
        return self._inner.broker

    def _apply_transition(self, rec: TrackedOrderRecord, event: OrderEngineEvent) -> None:
        nxt = transition(rec.status, event)  # type: ignore[arg-type]
        if nxt:
            rec.status = str(nxt)

    def process_signal_tracked(self, signal: OrderSignal, snapshot: RiskSnapshot) -> OrderResult:
        oid = self.store.new_id()
        order = self._inner.create_order_from_signal(signal)
        rec = TrackedOrderRecord(
            order_id=oid,
            status="created",
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            requested_price=order.price,
            signal_id=signal.signal_id,
            strategy_id=order.strategy_id,
        )
        self.store.upsert(rec)

        intent = self._inner.evaluate_signal(signal, snapshot)
        if not intent.approved:
            rec.failure_reason = f"{intent.reason_code}: {intent.reason}"
            self._apply_transition(rec, OrderEngineEvent.RISK_REJECTED)
            self.store.upsert(rec)
            return OrderResult(
                order_id=oid,
                accepted=False,
                message=rec.failure_reason or "rejected",
                status=OrderStatus.REJECTED_RISK,
            )

        self._apply_transition(rec, OrderEngineEvent.RISK_APPROVED)
        self.store.upsert(rec)

        return self._submit_with_retry(rec, order, snapshot)

    def _submit_with_retry(self, rec: TrackedOrderRecord, order: OrderRequest, snapshot: RiskSnapshot) -> OrderResult:
        last_msg = ""
        for attempt in range(1, self.retry_policy.max_attempts + 1):
            rec.attempts = attempt
            self.store.upsert(rec)
            try:
                decision = self._inner.risk_rules.approve_order(order=order, snapshot=snapshot)
                if not decision.approved:
                    rec.failure_reason = f"{decision.reason_code}: {decision.reason}"
                    rec.status = "rejected"
                    self.store.upsert(rec)
                    return OrderResult(
                        order_id=rec.order_id,
                        accepted=False,
                        message=rec.failure_reason,
                        status=OrderStatus.REJECTED_RISK,
                    )

                result = self._inner.broker.place_order(order)
                last_msg = result.message
                if result.accepted and result.order_id:
                    rec.broker_order_id = result.order_id
                    rec.last_broker_message = result.message
                    if result.metadata and "masked_broker_response" in result.metadata:
                        rec.last_masked_response_log = str(result.metadata["masked_broker_response"])[:4000]
                    self._apply_transition(rec, OrderEngineEvent.BROKER_ACCEPTED)
                    self.store.upsert(rec)
                    return OrderResult(
                        order_id=rec.order_id,
                        accepted=True,
                        message=result.message,
                        status=result.status,
                        filled_quantity=result.filled_quantity,
                        avg_fill_price=result.avg_fill_price,
                        metadata={"internal_order_id": rec.order_id, "broker_order_id": result.order_id, **(result.metadata or {})},
                    )

                rec.failure_reason = result.message
                last_msg = result.message
                if attempt >= self.retry_policy.max_attempts:
                    break
            except KISClientError as exc:
                last_msg = str(exc)
                rec.failure_reason = last_msg
                logger.warning(
                    "KIS place_order attempt %s/%s failed symbol=%s err=%s",
                    attempt,
                    self.retry_policy.max_attempts,
                    order.symbol,
                    exc,
                )
                if attempt >= self.retry_policy.max_attempts:
                    self._apply_transition(rec, OrderEngineEvent.RETRY_EXHAUSTED)
                    self.store.upsert(rec)
                    return OrderResult(
                        order_id=rec.order_id,
                        accepted=False,
                        message=last_msg,
                        status=OrderStatus.FAILED,
                        metadata={"internal_order_id": rec.order_id},
                    )
            if attempt < self.retry_policy.max_attempts:
                time.sleep(self.retry_policy.backoff_base_sec * (2 ** (attempt - 1)))

        self._apply_transition(rec, OrderEngineEvent.RETRY_EXHAUSTED)
        rec.failure_reason = last_msg or "broker rejected"
        self.store.upsert(rec)
        return OrderResult(
            order_id=rec.order_id,
            accepted=False,
            message=rec.failure_reason,
            status=OrderStatus.FAILED,
            metadata={"internal_order_id": rec.order_id},
        )

    def sync_open_orders_with_broker(self) -> int:
        """미체결 조회로 부분/전량 체결 반영. 갱신된 레코드 수 반환."""
        try:
            open_list = self._inner.broker.get_open_orders()
        except Exception as exc:
            logger.warning("get_open_orders failed: %s", exc)
            return 0
        by_broker = {o.order_id: o for o in open_list}
        updated = 0
        for rec in self.store.list_all():
            if rec.status not in {"submitted", "partially_filled"} or not rec.broker_order_id:
                continue
            oo = by_broker.get(rec.broker_order_id)
            if oo is None:
                rec.filled_quantity = rec.quantity
                rec.fill_price = rec.requested_price
                self._apply_transition(rec, OrderEngineEvent.FULL_FILL)
                self.store.upsert(rec)
                updated += 1
                continue
            filled = max(oo.quantity - oo.remaining_quantity, 0)
            rec.filled_quantity = filled
            if oo.price and oo.price > 0:
                rec.fill_price = float(oo.price)
            if oo.remaining_quantity <= 0:
                self._apply_transition(rec, OrderEngineEvent.FULL_FILL)
            elif filled > 0 and oo.remaining_quantity > 0:
                self._apply_transition(rec, OrderEngineEvent.PARTIAL_FILL)
            self.store.upsert(rec)
            updated += 1
        return updated

    def cleanup_stale_submitted(self) -> list[str]:
        """오래된 submitted/partial 을 취소 시도 후 상태 정리."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        cleaned: list[str] = []
        stale_min = self.timeout_policy.stale_submitted_minutes
        for rec in self.store.list_all():
            if rec.status not in {"submitted", "partially_filled"}:
                continue
            try:
                ts = datetime.fromisoformat(rec.updated_at_utc.replace("Z", "+00:00"))
            except ValueError:
                continue
            age_min = (now - ts).total_seconds() / 60.0
            if age_min < stale_min:
                continue
            if rec.broker_order_id:
                try:
                    self._inner.broker.cancel_order(rec.broker_order_id)
                    self._apply_transition(rec, OrderEngineEvent.STALE_CLEANUP)
                    rec.failure_reason = "stale_cleanup_cancel"
                except Exception as exc:
                    rec.failure_reason = f"stale_cleanup_failed: {exc}"
                    self._apply_transition(rec, OrderEngineEvent.TIMEOUT_ABORT)
            else:
                self._apply_transition(rec, OrderEngineEvent.TIMEOUT_ABORT)
                rec.failure_reason = "stale_no_broker_id"
            self.store.upsert(rec)
            cleaned.append(rec.order_id)
        return cleaned
