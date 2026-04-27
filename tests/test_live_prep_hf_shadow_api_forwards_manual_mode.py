from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app.main import app


def test_live_prep_hf_shadow_generate_forwards_manual_mode(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_prep_routes
    from backend.app.core.config import BackendSettings
    from backend.app.services.live_market_mode_store import LiveMarketModeStore

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_prep_candidates_store_json=str(tmp_path / "candidates.json"),
        live_exec_sessions_store_json=str(tmp_path / "sessions.json"),
        live_market_mode_store_json=str(tmp_path / "market_mode.json"),
    )
    monkeypatch.setattr(live_prep_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_prep_routes, "get_current_user_from_auth_header", lambda _h: SimpleNamespace(id="u1"))

    LiveMarketModeStore(cfg.live_market_mode_store_json).set("u1", market="domestic", manual_market_mode="aggressive")

    monkeypatch.setattr(live_prep_routes, "get_broker_service", lambda: object())

    seen = {"manual": None}

    def fake_generate_intraday_shadow_report(*, manual_market_mode=None, **_kw):
        seen["manual"] = manual_market_mode
        return {"ok": True, "strategy_id": "scalp_rsi_flag_hf_v1", "generated_order_count": 0, "generated_orders": [], "market_mode": {}}

    monkeypatch.setattr(live_prep_routes, "generate_intraday_shadow_report", fake_generate_intraday_shadow_report)

    c = TestClient(app)
    r = c.post(
        "/api/live-prep/hf-shadow/generate?strategy_id=scalp_rsi_flag_hf_v1&execution_mode=live_shadow",
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True
    assert seen["manual"] == "aggressive"

