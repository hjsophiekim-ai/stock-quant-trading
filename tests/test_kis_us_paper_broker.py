import pytest

from app.brokers.kis_us_paper_broker import KisUsPaperBroker
from app.clients.kis_client import KISClient


def test_kis_us_paper_broker_rejects_live_domain() -> None:
    client = KISClient(base_url="https://openapi.koreainvestment.com:9443")
    with pytest.raises(ValueError, match="openapivts"):
        KisUsPaperBroker(
            kis_client=client,
            account_no="12345678",
            account_product_code="01",
        )


def test_kis_us_paper_broker_accepts_mock_host_and_has_initial_cash() -> None:
    client = KISClient(base_url="https://openapivts.koreainvestment.com:29443")
    b = KisUsPaperBroker(
        kis_client=client,
        account_no="12345678",
        account_product_code="01",
    )
    assert b.account_no == "12345678"
    assert b.initial_cash == 100_000.0
