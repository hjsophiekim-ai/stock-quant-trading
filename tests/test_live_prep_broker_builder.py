from __future__ import annotations

from unittest.mock import MagicMock

from app.clients.kis_client import KISClient


def test_live_prep_build_live_broker_for_user_sets_live_flags(monkeypatch) -> None:
    from backend.app.api import live_prep_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        live_trading=True,
        live_trading_confirm=True,
        live_trading_extra_confirm=True,
    )
    client = MagicMock(spec=KISClient)
    b = live_prep_routes._build_live_broker_for_user(cfg=cfg, client=client, account_no="1234", product_code="01", read_only=False)
    assert b.trading_mode == "live"
    assert b.live_trading_enabled is True
    assert b.live_trading_confirm is True
    assert b.live_trading_extra_confirm is True
    assert b.startup_safety_passed is True

