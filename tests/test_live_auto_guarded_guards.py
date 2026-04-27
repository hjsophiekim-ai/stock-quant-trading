from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app.main import app


def _auth_ok(monkeypatch) -> None:
    from backend.app.api import live_exec_routes

    monkeypatch.setattr(live_exec_routes, "get_current_user_from_auth_header", lambda _h: SimpleNamespace(id="u1"))


def test_auto_guarded_tick_blocked_when_not_live_auto_guarded(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_exec_routes
    from backend.app.core.config import BackendSettings

    _auth_ok(monkeypatch)
    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto.json"),
        live_exec_sessions_store_json=str(tmp_path / "sessions.json"),
    )
    monkeypatch.setattr(live_exec_routes, "get_backend_settings", lambda: cfg)

    c = TestClient(app)
    r = c.post("/api/live-exec/auto-guarded/tick", headers={"Authorization": "Bearer t"})
    assert r.status_code == 403


def test_auto_guarded_tick_no_order_when_live_auto_order_false(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_exec_routes
    from backend.app.core.config import BackendSettings
    from backend.app.services.live_auto_guarded_store import LiveAutoGuardedStore

    _auth_ok(monkeypatch)
    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_auto_guarded",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto.json"),
        live_exec_sessions_store_json=str(tmp_path / "sessions.json"),
        live_auto_order=False,
    )
    monkeypatch.setattr(live_exec_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_exec_routes, "runtime_safety_validation_for_user_id", lambda *_a, **_k: {"ok": True, "blockers": [], "blocker_details": []})
    monkeypatch.setattr(live_exec_routes, "get_broker_service", lambda: object())

    st = LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).get("u1")
    st.enabled = True
    LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).upsert(st)

    c = TestClient(app)
    r = c.post("/api/live-exec/auto-guarded/tick", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert j.get("skipped") is True


def test_auto_guarded_tick_blocked_when_safety_fails(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_exec_routes
    from backend.app.core.config import BackendSettings
    from backend.app.services.live_auto_guarded_store import LiveAutoGuardedStore

    _auth_ok(monkeypatch)
    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_auto_guarded",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto.json"),
        live_exec_sessions_store_json=str(tmp_path / "sessions.json"),
        live_auto_order=True,
    )
    monkeypatch.setattr(live_exec_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(
        live_exec_routes,
        "runtime_safety_validation_for_user_id",
        lambda *_a, **_k: {"ok": False, "blockers": ["APP emergency stop is enabled"], "blocker_details": []},
    )
    monkeypatch.setattr(live_exec_routes, "get_broker_service", lambda: object())

    st = LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).get("u1")
    st.enabled = True
    LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).upsert(st)

    c = TestClient(app)
    r = c.post("/api/live-exec/auto-guarded/tick", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert j.get("blocked_before_order") is True
    assert isinstance(j.get("last_diagnostics"), list)

