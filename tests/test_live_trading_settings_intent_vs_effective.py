from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app


def test_save_full_unlock_intent_persists_even_when_paper_readiness_fails(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_trading_routes
    from backend.app.core.config import BackendSettings
    from backend.app.risk.live_unlock_gate import PaperReadinessResult

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        live_trading=True,
        live_trading_confirm=True,
        live_trading_extra_confirm=True,
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_trading_safety_state_store_json=str(tmp_path / "safety_state.json"),
    )

    def fake_eval(_cfg):
        return PaperReadinessResult(
            ok=False,
            bypassed=False,
            user_message_ko="모의투자 자동 검증 미통과(테스트)",
            technical_summary="TEST_FAIL",
        )

    monkeypatch.setattr(live_trading_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_trading_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())
    monkeypatch.setattr(live_trading_routes, "evaluate_paper_readiness", fake_eval)
    monkeypatch.setattr(live_trading_routes, "paper_readiness_to_dict", lambda _pr: {"ok": False, "bypassed": False})

    c = TestClient(app)

    r = c.post(
        "/api/live-trading/settings",
        headers={"Authorization": "Bearer t"},
        json={
            "live_trading_flag": True,
            "secondary_confirm_flag": True,
            "extra_approval_flag": True,
            "reason": "enable all",
            "actor": "t",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["settings_saved"] is True
    assert data["live_trading_flag"] is True
    assert data["secondary_confirm_flag"] is True
    assert data["extra_approval_flag"] is True
    assert data["requested_live_trading_flag"] is True
    assert data["requested_secondary_confirm_flag"] is True
    assert data["requested_extra_approval_flag"] is True
    assert data["can_place_live_order"] is False
    assert data["unlock_pending_due_to_paper_readiness"] is True
    assert data["settings_saved_but_not_effective"] is True
    assert any("모의투자 자동 검증 미통과" in x for x in (data.get("pending_blockers") or []))
    assert not any("APP live trading flag is not enabled" in x for x in (data.get("pending_blockers") or []))

    s = c.get("/api/live-trading/status", headers={"Authorization": "Bearer t"})
    assert s.status_code == 200
    st = s.json()
    assert st["live_trading_flag"] is True
    assert st["secondary_confirm_flag"] is True
    assert st["extra_approval_flag"] is True
    assert st["can_place_live_order"] is False
    assert st["unlock_pending_due_to_paper_readiness"] is True


def test_save_full_unlock_intent_becomes_effective_when_paper_readiness_passes(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_trading_routes
    from backend.app.core.config import BackendSettings
    from backend.app.risk.live_unlock_gate import PaperReadinessResult

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        live_trading=True,
        live_trading_confirm=True,
        live_trading_extra_confirm=True,
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_trading_safety_state_store_json=str(tmp_path / "safety_state.json"),
    )

    def fake_eval(_cfg):
        return PaperReadinessResult(ok=True, bypassed=False, user_message_ko="OK", technical_summary="OK")

    monkeypatch.setattr(live_trading_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_trading_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())
    monkeypatch.setattr(live_trading_routes, "evaluate_paper_readiness", fake_eval)
    monkeypatch.setattr(live_trading_routes, "paper_readiness_to_dict", lambda _pr: {"ok": True, "bypassed": False})

    c = TestClient(app)
    r = c.post(
        "/api/live-trading/settings",
        headers={"Authorization": "Bearer t"},
        json={
            "live_trading_flag": True,
            "secondary_confirm_flag": True,
            "extra_approval_flag": True,
            "reason": "enable all",
            "actor": "t",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["settings_saved"] is True
    assert data["unlock_pending_due_to_paper_readiness"] is False
    assert data["settings_saved_but_not_effective"] is False
    assert data["can_place_live_order"] is True


def test_partial_save_persists_and_does_not_trigger_pending_readiness(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_trading_routes
    from backend.app.core.config import BackendSettings
    from backend.app.risk.live_unlock_gate import PaperReadinessResult

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        live_trading=True,
        live_trading_confirm=True,
        live_trading_extra_confirm=True,
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_trading_safety_state_store_json=str(tmp_path / "safety_state.json"),
    )

    def fake_eval(_cfg):
        return PaperReadinessResult(ok=False, bypassed=False, user_message_ko="FAIL", technical_summary="FAIL")

    monkeypatch.setattr(live_trading_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_trading_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())
    monkeypatch.setattr(live_trading_routes, "evaluate_paper_readiness", fake_eval)
    monkeypatch.setattr(live_trading_routes, "paper_readiness_to_dict", lambda _pr: {"ok": False, "bypassed": False})

    c = TestClient(app)
    r = c.post(
        "/api/live-trading/settings",
        headers={"Authorization": "Bearer t"},
        json={
            "live_trading_flag": True,
            "secondary_confirm_flag": False,
            "extra_approval_flag": False,
            "reason": "partial",
            "actor": "t",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["settings_saved"] is True
    assert data["live_trading_flag"] is True
    assert data["secondary_confirm_flag"] is False
    assert data["extra_approval_flag"] is False
    assert data["unlock_pending_due_to_paper_readiness"] is False
    assert data["can_place_live_order"] is False


def test_runtime_safety_validation_route_does_not_require_user_id_query(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_trading_routes
    from backend.app.core.config import BackendSettings
    from backend.app.risk.live_unlock_gate import PaperReadinessResult

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_trading_safety_state_store_json=str(tmp_path / "safety_state.json"),
    )
    monkeypatch.setattr(live_trading_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_trading_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())
    monkeypatch.setattr(
        live_trading_routes,
        "evaluate_paper_readiness",
        lambda _cfg: PaperReadinessResult(ok=True, bypassed=True, user_message_ko="bypass", technical_summary="bypass"),
    )
    monkeypatch.setattr(live_trading_routes, "paper_readiness_to_dict", lambda _pr: {"ok": True, "bypassed": True})

    c = TestClient(app)
    r = c.get("/api/live-trading/runtime-safety-validation", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    data = r.json()
    assert "blocker_details" in data


def test_ui_contains_saved_vs_effective_messages() -> None:
    root = Path(__file__).resolve().parents[1]
    desktop = (root / "apps" / "desktop" / "src" / "live-trading.html").read_text(encoding="utf-8")
    mobile = (root / "apps" / "mobile" / "src" / "screens" / "LiveTradingSettingsScreen.tsx").read_text(encoding="utf-8")

    for s in [
        "설정 저장 완료. 실거래 제출은 아직 잠금 상태입니다.",
        "설정 저장 완료. Paper readiness 통과 후 실거래 제출이 가능합니다.",
        "설정 저장 완료. 현재 LIVE 주문 가능 상태입니다.",
    ]:
        assert s in desktop
        assert s in mobile

