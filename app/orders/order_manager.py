from dataclasses import dataclass

from app.brokers.base_broker import BaseBroker
from app.orders.models import OrderIntent, OrderRequest, OrderResult, OrderSignal, OrderStatus
from app.portfolio.positions import Position, apply_buy_fill, apply_sell_fill, update_high_watermark
from app.risk.audit_hook import emit_risk_audit
from app.risk.rules import RiskRules, RiskSnapshot


@dataclass
class OrderManager:
    broker: BaseBroker
    risk_rules: RiskRules

    def create_order_from_signal(self, signal: OrderSignal) -> OrderRequest:
        return OrderRequest(
            symbol=signal.symbol,
            side=signal.side,
            quantity=signal.quantity,
            price=signal.limit_price,
            stop_loss_pct=signal.stop_loss_pct,
            strategy_id=signal.strategy_id,
            signal_id=signal.signal_id,
        )

    def evaluate_signal(self, signal: OrderSignal, snapshot: RiskSnapshot) -> OrderIntent:
        order = self.create_order_from_signal(signal)
        decision = self.risk_rules.approve_order(order=order, snapshot=snapshot)
        emit_risk_audit(order, snapshot, decision)
        return OrderIntent(
            signal=signal,
            approved=decision.approved,
            reason_code=decision.reason_code,
            reason=decision.reason,
        )

    def process_signal(self, signal: OrderSignal, snapshot: RiskSnapshot) -> OrderResult:
        intent = self.evaluate_signal(signal, snapshot)
        if not intent.approved:
            return OrderResult(
                order_id="",
                accepted=False,
                message=f"{intent.reason_code}: {intent.reason}",
                status=OrderStatus.REJECTED_RISK,
            )
        return self.submit(self.create_order_from_signal(signal), snapshot)

    def submit(self, order: OrderRequest, snapshot: RiskSnapshot) -> OrderResult:
        decision = self.risk_rules.approve_order(order=order, snapshot=snapshot)
        if not decision.approved:
            return OrderResult(
                order_id="",
                accepted=False,
                message=f"{decision.reason_code}: {decision.reason}",
                status=OrderStatus.REJECTED_RISK,
            )
        result = self.broker.place_order(order)
        if not result.accepted:
            return OrderResult(
                order_id=result.order_id,
                accepted=False,
                message=result.message,
                status=OrderStatus.FAILED,
                filled_quantity=result.filled_quantity,
                avg_fill_price=result.avg_fill_price,
            )
        return OrderResult(
            order_id=result.order_id,
            accepted=True,
            message=result.message,
            status=result.status if result.status else OrderStatus.SUBMITTED,
            filled_quantity=result.filled_quantity,
            avg_fill_price=result.avg_fill_price,
        )

    def apply_fill_to_position(
        self,
        *,
        position: Position | None,
        order: OrderRequest,
        fill_price: float,
        filled_quantity: int | None = None,
        mark_first_take_profit: bool = False,
    ) -> Position | None:
        qty = filled_quantity if filled_quantity is not None and filled_quantity > 0 else order.quantity
        if qty <= 0:
            return position
        if order.side == "buy":
            updated = apply_buy_fill(position=position, quantity=qty, fill_price=fill_price, symbol=order.symbol)
            return update_high_watermark(updated, fill_price)
        if position is None:
            return None
        return apply_sell_fill(position=position, quantity=qty, mark_first_take_profit=mark_first_take_profit)
