from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app.main import app


def test_live_market_mode_requires_auth() -> None:
    c = TestClient(app)
    r = c.get("/api/live-trading/market-mode")
    assert r.status_code == 401


def test_live_market_mode_roundtrip(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_trading_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_trading_safety_state_store_json=str(tmp_path / "safety.json"),
        live_market_mode_store_json=str(tmp_path / "market_mode.json"),
    )
    monkeypatch.setattr(live_trading_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_trading_routes, "get_current_user_from_auth_header", lambda _h: SimpleNamespace(id="u-mm"))

    c = TestClient(app)
    g0 = c.get("/api/live-trading/market-mode", headers={"Authorization": "Bearer t"})
    assert g0.status_code == 200
    assert g0.json().get("manual_market_mode_override") == "auto"

    p = c.post(
        "/api/live-trading/market-mode",
        headers={"Authorization": "Bearer t", "Content-Type": "application/json"},
        json={"manual_market_mode": "defensive"},
    )
    assert p.status_code == 200
    assert p.json().get("manual_market_mode_override") == "defensive"

    g1 = c.get("/api/live-trading/market-mode", headers={"Authorization": "Bearer t"})
    assert g1.status_code == 200
    assert g1.json().get("manual_market_mode_override") == "defensive"

