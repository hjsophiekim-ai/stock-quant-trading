from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_live_trading_routes_require_auth(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_trading_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_trading_safety_state_store_json=str(tmp_path / "safety_state.json"),
    )
    monkeypatch.setattr(live_trading_routes, "get_backend_settings", lambda: cfg)

    c = TestClient(app)
    r = c.get("/api/live-trading/status")
    assert r.status_code == 401


def test_live_trading_safety_state_persists_per_user(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_trading_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_trading=True,
        live_trading_confirm=True,
        live_trading_extra_confirm=True,
        live_unlock_bypass=True,
        live_trading_safety_state_store_json=str(tmp_path / "safety_state.json"),
    )
    monkeypatch.setattr(live_trading_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_trading_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())

    c = TestClient(app)
    s0 = c.get("/api/live-trading/status", headers={"Authorization": "Bearer t"})
    assert s0.status_code == 200
    assert s0.json()["can_place_live_order"] is False

    upd = c.post(
        "/api/live-trading/settings",
        headers={"Authorization": "Bearer t"},
        json={
            "live_trading_flag": True,
            "secondary_confirm_flag": True,
            "extra_approval_flag": True,
            "reason": "enable for test",
            "actor": "t",
        },
    )
    assert upd.status_code == 200
    assert upd.json()["live_trading_flag"] is True
    assert upd.json()["secondary_confirm_flag"] is True
    assert upd.json()["extra_approval_flag"] is True

    hist = c.get("/api/live-trading/settings-history", headers={"Authorization": "Bearer t"})
    assert hist.status_code == 200
    items = hist.json()["items"]
    assert isinstance(items, list)
    assert any(x.get("action") == "update_live_safety_settings" for x in items)

    es = c.post(
        "/api/live-trading/emergency-stop",
        headers={"Authorization": "Bearer t"},
        json={"enabled": True, "reason": "stop", "actor": "t"},
    )
    assert es.status_code == 200
    assert es.json()["live_emergency_stop"] is True

    v = c.get("/api/live-trading/runtime-safety-validation", headers={"Authorization": "Bearer t"})
    assert v.status_code == 200
    data = v.json()
    assert data["ok"] is False
    assert "APP emergency stop is enabled" in (data.get("blockers") or [])
    assert any(d.get("code") == "APP_EMERGENCY_STOP_ON" for d in (data.get("blocker_details") or []))

