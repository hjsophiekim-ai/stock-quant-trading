"""CTX_AREA_* 첫 페이지 미전송 — inquire_psbl_order 등 (OPSQ2001 예방)."""

from __future__ import annotations

import types
from unittest.mock import MagicMock

from app.clients.kis_client import KISClient, omit_empty_ctx_params


def test_omit_empty_ctx_removes_blank_ctx_keys() -> None:
    p = omit_empty_ctx_params({"CTX_AREA_FK100": "", "CTX_AREA_NK100": "x", "CANO": "1"})
    assert "CTX_AREA_FK100" not in p
    assert p.get("CTX_AREA_NK100") == "x"


def test_inquire_psbl_order_first_page_no_ctx_keys() -> None:
    client = KISClient(base_url="https://openapivts.koreainvestment.com:29443", kis_min_request_interval_ms=0)
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
