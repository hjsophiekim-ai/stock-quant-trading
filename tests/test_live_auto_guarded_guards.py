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


def _enable_live_flags_for_user(cfg, *, user_id: str) -> None:
    from backend.app.services.live_safety_state_store import LiveSafetyState, LiveSafetyStateStore

    st = LiveSafetyState(
        user_id=user_id,
        live_trading_flag=True,
        secondary_confirm_flag=True,
        extra_approval_flag=True,
        live_emergency_stop=False,
    )
    LiveSafetyStateStore(cfg.live_trading_safety_state_store_json).upsert(st)


def test_live_unlock_bypass_true_allows_can_place_auto_order_even_if_paper_readiness_failed(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_exec_routes
    from backend.app.core.config import BackendSettings
    from backend.app.services.live_auto_guarded_store import LiveAutoGuardedStore

    _auth_ok(monkeypatch)
    cfg = BackendSettings(
        app_env="local",
        backend_data_dir=str(tmp_path / "bd"),
        trading_mode="live",
        execution_mode="live_auto_guarded",
        live_trading=True,
        live_trading_confirm=True,
        live_trading_extra_confirm=True,
        live_auto_order=True,
        live_unlock_enabled=True,
        live_unlock_bypass=True,
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_exec_sessions_store_json=str(tmp_path / "sessions.json"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto.json"),
        live_trading_safety_state_store_json=str(tmp_path / "safety.json"),
        readiness_builder_state_store_json=str(tmp_path / "rb.json"),
    )
    monkeypatch.setattr(live_exec_routes, "get_backend_settings", lambda: cfg)
    _enable_live_flags_for_user(cfg, user_id="u1")

    st = LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).get("u1")
    st.enabled = True
    LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).upsert(st)

    c = TestClient(app)
    r = c.get("/api/live-exec/auto-guarded/status", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    j = r.json()
    assert j.get("safety", {}).get("ok") is True
    assert j.get("can_auto_order") is True
    assert j.get("can_place_auto_order") is True


def test_live_unlock_bypass_false_keeps_paper_readiness_failed_blocker(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_exec_routes
    from backend.app.core.config import BackendSettings
    from backend.app.services.live_auto_guarded_store import LiveAutoGuardedStore

    _auth_ok(monkeypatch)
    cfg = BackendSettings(
        app_env="local",
        backend_data_dir=str(tmp_path / "bd"),
        trading_mode="live",
        execution_mode="live_auto_guarded",
        live_trading=True,
        live_trading_confirm=True,
        live_trading_extra_confirm=True,
        live_auto_order=True,
        live_unlock_enabled=True,
        live_unlock_bypass=False,
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_exec_sessions_store_json=str(tmp_path / "sessions.json"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto.json"),
        live_trading_safety_state_store_json=str(tmp_path / "safety.json"),
        readiness_builder_state_store_json=str(tmp_path / "rb.json"),
    )
    monkeypatch.setattr(live_exec_routes, "get_backend_settings", lambda: cfg)
    _enable_live_flags_for_user(cfg, user_id="u1")

    st = LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).get("u1")
    st.enabled = True
    LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).upsert(st)

    c = TestClient(app)
    r = c.get("/api/live-exec/auto-guarded/status", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    j = r.json()
    assert j.get("safety", {}).get("ok") is False
    codes = [d.get("code") for d in (j.get("safety", {}).get("blocker_details") or []) if isinstance(d, dict)]
    assert "PAPER_READINESS_FAILED" in set(codes)
    assert j.get("can_auto_order") is False
    assert j.get("can_place_auto_order") is False


def test_auto_guarded_tick_returns_clear_message_when_not_started(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_exec_routes
    from backend.app.core.config import BackendSettings

    _auth_ok(monkeypatch)
    cfg = BackendSettings(
        app_env="local",
        backend_data_dir=str(tmp_path / "bd"),
        trading_mode="live",
        execution_mode="live_auto_guarded",
        live_trading=True,
        live_trading_confirm=True,
        live_trading_extra_confirm=True,
        live_auto_order=True,
        live_unlock_enabled=True,
        live_unlock_bypass=True,
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto.json"),
        live_exec_sessions_store_json=str(tmp_path / "sessions.json"),
        live_trading_safety_state_store_json=str(tmp_path / "safety.json"),
        readiness_builder_state_store_json=str(tmp_path / "rb.json"),
    )
    monkeypatch.setattr(live_exec_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_exec_routes, "get_broker_service", lambda: object())
    _enable_live_flags_for_user(cfg, user_id="u1")

    c = TestClient(app)
    r = c.post("/api/live-exec/auto-guarded/tick", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert j.get("blocked_before_start") is True
    assert "Start" in str(j.get("message_ko") or "")


def test_auto_guarded_tick_enters_evaluation_when_enabled_and_bypass_true(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_exec_routes
    from backend.app.core.config import BackendSettings
    from backend.app.services.live_auto_guarded_store import LiveAutoGuardedState, LiveAutoGuardedStore

    _auth_ok(monkeypatch)
    cfg = BackendSettings(
        app_env="local",
        backend_data_dir=str(tmp_path / "bd"),
        trading_mode="live",
        execution_mode="live_auto_guarded",
        live_trading=True,
        live_trading_confirm=True,
        live_trading_extra_confirm=True,
        live_auto_order=True,
        live_unlock_enabled=True,
        live_unlock_bypass=True,
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto.json"),
        live_exec_sessions_store_json=str(tmp_path / "sessions.json"),
        live_trading_safety_state_store_json=str(tmp_path / "safety.json"),
        readiness_builder_state_store_json=str(tmp_path / "rb.json"),
    )
    monkeypatch.setattr(live_exec_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_exec_routes, "get_broker_service", lambda: object())
    _enable_live_flags_for_user(cfg, user_id="u1")
    LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json).upsert(LiveAutoGuardedState(user_id="u1", enabled=True))

    seen = {"called": False, "safety_ok": None}

    def fake_tick(*, cfg, broker_service, user_id, safety):
        seen["called"] = True
        seen["safety_ok"] = bool(safety.get("ok"))
        return {"ok": True, "entered_evaluation": True}

    monkeypatch.setattr(live_exec_routes, "tick_live_auto_guarded", fake_tick)

    c = TestClient(app)
    r = c.post("/api/live-exec/auto-guarded/tick", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert j.get("entered_evaluation") is True
    assert seen["called"] is True
    assert seen["safety_ok"] is True

