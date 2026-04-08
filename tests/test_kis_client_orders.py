from unittest.mock import MagicMock

from app.clients.kis_client import KISClient


def test_place_order_uses_mock_tr_ids_and_limit_div() -> None:
    client = KISClient(base_url="https://openapivts.koreainvestment.com:29443")
    client.request_hashkey = MagicMock(return_value="fakehash")  # type: ignore[method-assign]
    captured: dict = {}

    def fake_post(path, *, data=None, tr_id=None, extra_headers=None, bearer_token=None):
        captured["tr_id"] = tr_id
        captured["data"] = data
        captured["extra"] = extra_headers
        return {"rt_cd": "0", "output": {"ODNO": "1", "KRX_FWDG_ORD_ORGNO": "00950"}}

    client._post = fake_post  # type: ignore[method-assign]

    out = client.place_order(
        account_no="50000000",
        account_product_code="01",
        symbol="005930",
        side="buy",
        quantity=3,
        price=70000,
    )
    assert captured["tr_id"] == "VTTC0802U"
    assert captured["data"]["ORD_DVSN"] == "00"
    assert captured["data"]["ORD_UNPR"] == "70000"
    assert captured["extra"]["hashkey"] == "fakehash"
    assert out["output"]["ODNO"] == "1"


def test_place_order_market_uses_dvsn_01() -> None:
    client = KISClient(base_url="https://openapivts.koreainvestment.com:29443")
    client.request_hashkey = MagicMock(return_value="h")  # type: ignore[method-assign]
    captured: dict = {}

    def fake_post(path, *, data=None, tr_id=None, extra_headers=None, bearer_token=None):
        captured["data"] = data
        return {"rt_cd": "0", "output": {"ODNO": "9"}}

    client._post = fake_post  # type: ignore[method-assign]
    client.place_order(
        account_no="50000000",
        account_product_code="01",
        symbol="005930",
        side="sell",
        quantity=1,
        price=0,
    )
    assert captured["data"]["ORD_DVSN"] == "01"
    assert captured["data"]["ORD_UNPR"] == "0"


def test_cancel_order_resolves_mock_tr_id() -> None:
    client = KISClient(base_url="https://openapivts.koreainvestment.com:29443")
    client.request_hashkey = MagicMock(return_value="h")  # type: ignore[method-assign]
    captured: dict = {}

    def fake_post(path, *, data=None, tr_id=None, extra_headers=None, bearer_token=None):
        captured["tr_id"] = tr_id
        return {"rt_cd": "0"}

    client._post = fake_post  # type: ignore[method-assign]
    client.cancel_order(
        account_no="50000000",
        account_product_code="01",
        original_order_no="123",
        quantity=0,
        symbol="005930",
        krx_fwdg_ord_orgno="00950",
        cancel_all=True,
    )
    assert captured["tr_id"] == "VTTC0803U"
