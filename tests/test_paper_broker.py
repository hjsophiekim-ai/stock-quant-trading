from app.brokers.paper_broker import PaperBroker
from app.orders.models import OrderRequest


def test_paper_broker_buy_fill_success() -> None:
    broker = PaperBroker(initial_cash=1_000_000.0, price_provider=lambda _s: 10_000.0)
    result = broker.place_order(OrderRequest(symbol="005930", side="buy", quantity=10, price=None, stop_loss_pct=4.0))
    assert result.accepted is True
    assert broker.get_cash() == 900_000.0
    assert len(broker.get_positions()) == 1
    assert len(broker.get_fills()) == 1


def test_paper_broker_rejects_buy_when_insufficient_cash() -> None:
    broker = PaperBroker(initial_cash=50_000.0, price_provider=lambda _s: 10_000.0)
    result = broker.place_order(OrderRequest(symbol="005930", side="buy", quantity=10, price=None, stop_loss_pct=4.0))
    assert result.accepted is False
    assert "Insufficient paper cash" in result.message


def test_paper_broker_rejects_sell_when_no_position() -> None:
    broker = PaperBroker(initial_cash=1_000_000.0, price_provider=lambda _s: 10_000.0)
    result = broker.place_order(OrderRequest(symbol="005930", side="sell", quantity=1, price=None, stop_loss_pct=None))
    assert result.accepted is False
    assert "Insufficient paper position" in result.message
