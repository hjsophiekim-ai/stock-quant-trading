"""LiveBroker 미체결·체결 조회가 KISClient·파서와 연결되는지 검증."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.brokers.live_broker import LiveBroker
from app.clients.kis_client import KISClient


def test_live_broker_get_open_orders_parses_payload() -> None:
    client = MagicMock(spec=KISClient)
    client.inquire_nccs.return_value = {
        "rt_cd": "0",
        "output1": [
            {
                "pdno": "005930",
                "odno": "0000123456",
                "ord_qty": "10",
                "tot_ccld_qty": "0",
                "rmn_qty": "10",
                "sll_buy_dvsn_cd": "02",
                "ord_unpr": "70000",
                "ord_tmd": "090001",
            }
        ],
    }
    b = LiveBroker(
        kis_client=client,
        account_no="12345678",
        account_product_code="01",
        live_trading_enabled=True,
        live_trading_confirm=True,
        live_trading_extra_confirm=True,
        trading_mode="live",
    )
    oo = b.get_open_orders()
    assert len(oo) == 1
    assert oo[0].symbol == "005930"
    assert oo[0].remaining_quantity == 10
    client.inquire_nccs.assert_called_once()


def test_live_broker_get_fills_parses_payload() -> None:
    client = MagicMock(spec=KISClient)
    client.inquire_daily_ccld.return_value = {
        "rt_cd": "0",
        "output1": [
            {
                "pdno": "005930",
                "ccld_qty": "3",
                "ccld_untp": "71000",
                "sll_buy_dvsn_cd": "02",
                "odno": "0000999",
                "ord_dt": "20260101",
                "ord_tmd": "090102",
            }
        ],
    }
    b = LiveBroker(
        kis_client=client,
        account_no="12345678",
        account_product_code="01",
        live_trading_enabled=True,
        live_trading_confirm=True,
        live_trading_extra_confirm=True,
        trading_mode="live",
    )
    fills = b.get_fills()
    assert len(fills) == 1
    assert fills[0].symbol == "005930"
    assert fills[0].quantity == 3
    client.inquire_daily_ccld.assert_called_once()
