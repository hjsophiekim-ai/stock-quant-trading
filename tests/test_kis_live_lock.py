import pytest

from app.clients.kis_client import KISClient, KISLiveTradingLockedError


def test_place_order_blocked_on_live_host_without_unlock() -> None:
    client = KISClient(
        base_url="https://openapi.koreainvestment.com:9443",
        live_execution_unlocked=False,
    )
    with pytest.raises(KISLiveTradingLockedError):
        client.place_order(
            account_no="12345678",
            account_product_code="01",
            symbol="005930",
            side="buy",
            quantity=1,
            price=0,
        )


def test_place_order_allowed_on_live_host_when_unlocked() -> None:
    client = KISClient(
        base_url="https://openapi.koreainvestment.com:9443",
        live_execution_unlocked=True,
    )
    client.request_hashkey = lambda _b: "h"  # type: ignore[method-assign]
    client._post = lambda *a, **k: {"rt_cd": "0", "output": {"ODNO": "1"}}  # type: ignore[method-assign]
    out = client.place_order(
        account_no="12345678",
        account_product_code="01",
        symbol="005930",
        side="buy",
        quantity=1,
        price=0,
    )
    assert out["output"]["ODNO"] == "1"
