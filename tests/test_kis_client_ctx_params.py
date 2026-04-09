from __future__ import annotations

import types
from unittest.mock import MagicMock

from app.clients.kis_client import KISClient, omit_empty_ctx_params


def test_first_page_inquire_psbl_order_omits_ctx_in_http_params() -> None:
    client = KISClient(base_url="https://openapivts.koreainvestment.com:29443")
    captured: dict = {}

    def fake_request(
        self,
        method: str,
        path: str,
        *,
        params=None,
        data=None,
        tr_id=None,
        bearer_token=None,
        extra_headers=None,
    ):
        captured["params"] = dict(params or {})
        return {"rt_cd": "0"}

    client._request = types.MethodType(fake_request, client)  # type: ignore[method-assign]
    client._validate_kis_business_success = MagicMock()  # type: ignore[method-assign]

    client.inquire_psbl_order(
        account_no="50000000",
        account_product_code="01",
        symbol="005930",
        order_div="01",
    )
    assert "CTX_AREA_FK100" not in captured["params"]
    assert "CTX_AREA_NK100" not in captured["params"]


def test_ctx_preserved_when_non_empty() -> None:
    raw = {"CTX_AREA_FK100": "abc", "CTX_AREA_NK100": ""}
    out = omit_empty_ctx_params(raw)
    assert out["CTX_AREA_FK100"] == "abc"
    assert "CTX_AREA_NK100" not in out
