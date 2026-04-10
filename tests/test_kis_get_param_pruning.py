"""KIS GET prune_empty_get_params 및 주요 inquire 최종 params."""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

from app.clients.kis_client import KISClient, prune_empty_get_params


def test_prune_removes_none_empty_whitespace() -> None:
    p = prune_empty_get_params(
        {"A": None, "B": "", "C": "  ", "D": "x", "E": 0, "F": "0", "G": "00"},
    )
    assert p is not None
    assert "A" not in p and "B" not in p and "C" not in p
    assert p.get("D") == "x"
    assert p.get("E") == 0
    assert p.get("F") == "0"
    assert p.get("G") == "00"


def test_prune_allow_empty_keys() -> None:
    p = prune_empty_get_params({"X": ""}, allow_empty_keys=frozenset({"X"}))
    assert p == {"X": ""}


def test_inquire_psbl_market_sends_ord_unpr_zero_no_ctx() -> None:
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
    q = captured["params"]
    assert q.get("ORD_UNPR") == "0"
    assert q.get("CMA_EVLU_AMT_ICLD_YN") == "N"
    assert q.get("OVRS_ICLD_YN") == "N"
    assert "CTX_AREA_FK100" not in q
    assert q.get("PDNO") == "005930"


def test_inquire_nccs_delegates_to_daily_ccld_unfilled() -> None:
    client = KISClient(base_url="https://openapivts.koreainvestment.com:29443", kis_min_request_interval_ms=0)
    captured: dict = {}

    def fake_request(self, method, path, *, params=None, **_k):
        captured["path"] = path
        captured["params"] = dict(params or {})
        return {"rt_cd": "0"}

    client._request = types.MethodType(fake_request, client)  # type: ignore[method-assign]
    client._validate_kis_business_success = MagicMock()  # type: ignore[method-assign]

    client.inquire_nccs(account_no="50000000", account_product_code="01", symbol="")
    assert captured["path"] == "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
    assert "PDNO" not in captured["params"]
    assert captured["params"].get("CCLD_DVSN") == "02"


def test_inquire_daily_ccld_omits_empty_dvsn_and_pdno() -> None:
    client = KISClient(base_url="https://openapivts.koreainvestment.com:29443", kis_min_request_interval_ms=0)
    captured: dict = {}

    def fake_request(self, method, path, *, params=None, **_k):
        captured["params"] = dict(params or {})
        return {"rt_cd": "0"}

    client._request = types.MethodType(fake_request, client)  # type: ignore[method-assign]
    client._validate_kis_business_success = MagicMock()  # type: ignore[method-assign]

    client.inquire_daily_ccld(account_no="50000000", account_product_code="01", symbol="")
    q = captured["params"]
    assert "INQR_DVSN_1" not in q
    assert "INQR_DVSN_2" not in q
    assert "PDNO" not in q
    assert q.get("INQR_DVSN_3") == "00"
