from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_live_exec_start_blocked_when_not_live(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_exec_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="paper",
        execution_mode="paper_auto",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_prep_candidates_store_json=str(tmp_path / "candidates.json"),
        live_exec_sessions_store_json=str(tmp_path / "sessions.json"),
    )
    monkeypatch.setattr(live_exec_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_exec_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())

    c = TestClient(app)
    r = c.post(
        "/api/live-exec/start",
        headers={"Authorization": "Bearer t"},
        json={"strategy_id": "final_betting_v1", "market": "domestic", "execution_mode": "live_shadow", "actor": "t", "reason": "xxy"},
    )
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["error"] == "start_blocked"
    assert any("TRADING_MODE is not live" in x for x in detail["blockers"])


def test_live_exec_start_stop_and_status(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_exec_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="paper_auto",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_prep_candidates_store_json=str(tmp_path / "candidates.json"),
        live_exec_sessions_store_json=str(tmp_path / "sessions.json"),
    )
    monkeypatch.setattr(live_exec_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_exec_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())
    monkeypatch.setattr(
        live_exec_routes,
        "runtime_safety_validation_for_user_id",
        lambda _cfg, _uid: {"ok": False, "blockers": ["APP emergency stop is enabled"], "blocker_details": []},
    )

    c = TestClient(app)
    s0 = c.get("/api/live-exec/status", headers={"Authorization": "Bearer t"})
    assert s0.status_code == 200
    assert s0.json()["session_running"] is False

    r1 = c.post(
        "/api/live-exec/start",
        headers={"Authorization": "Bearer t"},
        json={"strategy_id": "final_betting_v1", "market": "domestic", "execution_mode": "live_manual_approval", "actor": "t", "reason": "start"},
    )
    assert r1.status_code == 200
    assert r1.json()["session"]["status"] == "running"

    s1 = c.get("/api/live-exec/status", headers={"Authorization": "Bearer t"})
    assert s1.status_code == 200
    assert s1.json()["session_running"] is True
    assert "APP emergency stop is enabled" in (s1.json().get("blocked", {}).get("submit_blockers") or [])

    r2 = c.post("/api/live-exec/stop", headers={"Authorization": "Bearer t"}, json={"actor": "t", "reason": "stop"})
    assert r2.status_code == 200
    assert r2.json()["stopped"] is True


def test_live_exec_tick_upserts_final_betting_candidates(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_exec_routes
    from backend.app.core.config import BackendSettings
    from backend.app.services.live_prep_store import LiveCandidateStore

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="paper_auto",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_prep_candidates_store_json=str(tmp_path / "candidates.json"),
        live_exec_sessions_store_json=str(tmp_path / "sessions.json"),
    )
    monkeypatch.setattr(live_exec_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_exec_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())
    monkeypatch.setattr(live_exec_routes, "get_broker_service", lambda: object())

    def fake_gen(**_kw):
        return {
            "ok": True,
            "candidates": [
                {
                    "candidate_id": "c1",
                    "status": "approval_pending",
                    "symbol": "005930",
                    "side": "buy",
                    "strategy_id": "final_betting_v1",
                    "score": 1.0,
                    "quantity": 1,
                    "price": None,
                    "stop_loss_pct": None,
                    "rationale": "test",
                    "risk_flags": [],
                    "metadata": {},
                }
            ],
        }

    monkeypatch.setattr(live_exec_routes, "generate_final_betting_shadow_candidates", fake_gen)

    c = TestClient(app)
    c.post(
        "/api/live-exec/start",
        headers={"Authorization": "Bearer t"},
        json={"strategy_id": "final_betting_v1", "market": "domestic", "execution_mode": "live_manual_approval", "actor": "t", "reason": "start"},
    )
    t = c.post("/api/live-exec/tick", headers={"Authorization": "Bearer t"})
    assert t.status_code == 200

    store = LiveCandidateStore(cfg.live_prep_candidates_store_json)
    items = store.list_filtered(strategy_id="final_betting_v1", limit=50)
    assert any(x.candidate_id == "c1" for x in items)

