from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_live_prep_reads_execution_mode_from_active_live_exec_session(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_exec_routes, live_prep_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="paper_auto",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_exec_sessions_store_json=str(tmp_path / "sessions.json"),
        live_prep_candidates_store_json=str(tmp_path / "candidates.json"),
        live_prep_sell_only_arm_store_json=str(tmp_path / "sell_only_arm.json"),
        live_prep_liquidation_plans_store_json=str(tmp_path / "liq_plans.json"),
        live_trading_safety_state_store_json=str(tmp_path / "safety_state.json"),
    )
    monkeypatch.setattr(live_exec_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_prep_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_exec_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())
    monkeypatch.setattr(live_prep_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())

    c = TestClient(app)
    s = c.post(
        "/api/live-exec/start",
        headers={"Authorization": "Bearer t"},
        json={
            "strategy_id": "final_betting_v1",
            "market": "domestic",
            "execution_mode": "live_manual_approval",
            "actor": "t",
            "reason": "start",
        },
    )
    assert s.status_code == 200

    r1 = c.get("/api/live-prep/candidates?strategy_id=final_betting_v1&limit=1", headers={"Authorization": "Bearer t"})
    assert r1.status_code == 200
    assert "live 실행 모드가 설정되지 않았습니다" not in str(r1.json())

    r2 = c.get("/api/live-prep/sell-only-arm/status", headers={"Authorization": "Bearer t"})
    assert r2.status_code == 200
    assert "live 실행 모드가 설정되지 않았습니다" not in str(r2.json())


def test_live_prep_accepts_execution_mode_hint_when_session_not_visible(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_prep_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="paper_auto",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_exec_sessions_store_json=str(tmp_path / "sessions.json"),
        live_prep_candidates_store_json=str(tmp_path / "candidates.json"),
        live_prep_sell_only_arm_store_json=str(tmp_path / "sell_only_arm.json"),
        live_prep_liquidation_plans_store_json=str(tmp_path / "liq_plans.json"),
        live_trading_safety_state_store_json=str(tmp_path / "safety_state.json"),
    )
    monkeypatch.setattr(live_prep_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_prep_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())

    c = TestClient(app)
    r1 = c.get(
        "/api/live-prep/candidates?strategy_id=final_betting_v1&limit=1&execution_mode=live_manual_approval",
        headers={"Authorization": "Bearer t"},
    )
    assert r1.status_code == 200

    r2 = c.get(
        "/api/live-prep/sell-only-arm/status?execution_mode=live_manual_approval",
        headers={"Authorization": "Bearer t"},
    )
    assert r2.status_code == 200

