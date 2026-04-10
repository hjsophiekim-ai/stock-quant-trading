from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.clients.kis_client import KISClient
from app.clients.kis_parsers import is_kis_rate_limit


def test_is_kis_rate_limit_detects_egw00201() -> None:
    assert is_kis_rate_limit(
        payload={"msg_cd": "EGW00201", "msg1": "초당 거래건수를 초과하였습니다."},
        http_body="",
        http_status=500,
    )


def test_kis_client_retries_on_http500_rate_limit_then_ok() -> None:
    """EGW00201 HTTP 500 시 백오프 후 성공하면 dict 반환."""
    responses: list[MagicMock] = []

    def mk_500():
        r = MagicMock()
        r.status_code = 500
        body = {"msg_cd": "EGW00201", "msg1": "초당 거래건수를 초과하였습니다."}
        r.text = json.dumps(body)
        r.content = r.text.encode()
        r.json = lambda: body
        return r

    def mk_200_ok():
        r = MagicMock()
        r.status_code = 200
        body = {"rt_cd": "0", "output2": []}
        r.text = json.dumps(body)
        r.content = r.text.encode()
        r.json = lambda: body
        return r

    responses.extend([mk_500(), mk_200_ok()])

    def fake_request(method, url, **kwargs):
        if not responses:
            raise AssertionError("unexpected extra request")
        return responses.pop(0)

    client = KISClient(
        base_url="https://openapivts.koreainvestment.com:29443",
        kis_min_request_interval_ms=0,
        kis_rate_limit_max_retries=8,
        kis_rate_limit_backoff_base_sec=0.01,
        kis_rate_limit_backoff_cap_sec=0.05,
        max_retries=0,
    )
    client.session.request = fake_request  # type: ignore[method-assign]

    out = client._request(  # noqa: SLF001
        "GET",
        "uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
        params={"FID_INPUT_ISCD": "005930"},
        tr_id="FHKST03010100",
    )
    assert out.get("rt_cd") == "0"


def test_kis_client_retries_on_rt_cd_rate_limit_then_ok() -> None:
    """HTTP 200 + rt_cd≠0 + EGW00201 시 백오프 후 성공."""
    responses: list[MagicMock] = []

    def mk_rl_business():
        r = MagicMock()
        r.status_code = 200
        body = {"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당"}
        r.text = json.dumps(body)
        r.content = r.text.encode()
        r.json = lambda: body
        return r

    def mk_ok():
        r = MagicMock()
        r.status_code = 200
        body = {"rt_cd": "0", "output2": []}
        r.text = json.dumps(body)
        r.content = r.text.encode()
        r.json = lambda: body
        return r

    responses.extend([mk_rl_business(), mk_ok()])

    def fake_request(method, url, **kwargs):
        return responses.pop(0)

    client = KISClient(
        base_url="https://openapivts.koreainvestment.com:29443",
        kis_min_request_interval_ms=0,
        kis_rate_limit_max_retries=8,
        kis_rate_limit_backoff_base_sec=0.01,
        kis_rate_limit_backoff_cap_sec=0.05,
        max_retries=0,
    )
    client.session.request = fake_request  # type: ignore[method-assign]

    out = client._request(  # noqa: SLF001
        "GET",
        "path",
        params={},
        tr_id="TR",
    )
    assert out.get("rt_cd") == "0"
