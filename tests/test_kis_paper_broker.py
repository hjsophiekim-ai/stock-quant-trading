import pytest

from app.brokers.kis_paper_broker import KisPaperBroker
from app.clients.kis_client import KISClient


def test_kis_paper_broker_rejects_live_domain() -> None:
    client = KISClient(base_url="https://openapi.koreainvestment.com:9443")
    with pytest.raises(ValueError, match="openapivts"):
        KisPaperBroker(
            kis_client=client,
            account_no="12345678",
            account_product_code="01",
        )


def test_kis_paper_broker_accepts_mock_host() -> None:
    client = KISClient(base_url="https://openapivts.koreainvestment.com:29443")
    b = KisPaperBroker(
        kis_client=client,
        account_no="12345678",
        account_product_code="01",
    )
    assert b.account_no == "12345678"
