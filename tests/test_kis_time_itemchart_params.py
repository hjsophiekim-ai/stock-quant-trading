"""당일분봉 API: FID_ETC_CLS_CODE 가 GET prune 으로 빠지지 않도록 비어 있지 않은 값을 쓴다."""

from __future__ import annotations

from unittest.mock import patch

from app.clients.kis_contract import TIME_ITEMCHART_FID_ETC_CLS_CODE
from app.clients.kis_client import KISClient, prune_empty_get_params


def test_prune_removes_empty_fid_etc_cls_code() -> None:
    q = prune_empty_get_params(
        {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_ETC_CLS_CODE": "",
        }
    )
    assert q is not None
    assert "FID_ETC_CLS_CODE" not in q


def test_prune_keeps_fid_etc_cls_code_00() -> None:
    q = prune_empty_get_params({"FID_ETC_CLS_CODE": "00"})
    assert q is not None
    assert q.get("FID_ETC_CLS_CODE") == "00"


def test_get_time_itemchartprice_sends_etc_cls_00() -> None:
    client = KISClient(base_url="https://openapivts.koreainvestment.com:29443")
    captured: dict = {}

    def fake_get(self, path: str, *, params=None, tr_id=None, **kw: object) -> dict:  # type: ignore[no-untyped-def]
        captured["params"] = params
        return {"rt_cd": "0", "output2": []}

    with patch.object(KISClient, "_get", fake_get):
        client.get_time_itemchartprice(
            market_div_code="J",
            symbol="005930",
            input_hour_hhmmss="093000",
        )
    pruned = prune_empty_get_params(captured["params"])
    assert pruned is not None
    assert pruned.get("FID_ETC_CLS_CODE") == TIME_ITEMCHART_FID_ETC_CLS_CODE == "00"
