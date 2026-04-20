from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


def test_market_mode_get_requires_auth() -> None:
    c = TestClient(app)
    r = c.get("/api/paper-trading/market-mode")
    assert r.status_code == 401


def test_market_mode_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.app.api.paper_trading_routes.get_current_user_from_auth_header",
        lambda _h: SimpleNamespace(id="u-mm"),
    )
    ctrl = MagicMock()
    ctrl.get_paper_market_mode.return_value = {
        "ok": True,
        "manual_market_mode_override": "defensive",
        "market_mode_active": "defensive",
        "market_mode_source": "manual_override",
    }
    ctrl.set_paper_market_mode.return_value = {"ok": True, "manual_market_mode_override": "auto"}
    monkeypatch.setattr(
        "backend.app.api.paper_trading_routes.get_paper_session_controller",
        lambda: ctrl,
    )
    c = TestClient(app)
    g = c.get("/api/paper-trading/market-mode", headers={"Authorization": "Bearer t"})
    assert g.status_code == 200
    assert g.json().get("manual_market_mode_override") == "defensive"

    p = c.post(
        "/api/paper-trading/market-mode",
        headers={"Authorization": "Bearer t", "Content-Type": "application/json"},
        json={"manual_market_mode": "auto"},
    )
    assert p.status_code == 200
    assert p.json().get("manual_market_mode_override") == "auto"
    ctrl.set_paper_market_mode.assert_called_once()
