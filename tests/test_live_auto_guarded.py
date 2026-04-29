from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_auto_guarded_start_persists_selected_strategy(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_trading_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_trading_safety_state_store_json=str(tmp_path / "live_safety.json"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto_state.json"),
    )
    monkeypatch.setattr(live_trading_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_trading_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())
    monkeypatch.setattr(live_trading_routes, "runtime_safety_validation_for_user_id", lambda *_a, **_k: {"ok": True, "blockers": []})

    c = TestClient(app)
    r = c.post(
        "/api/live-trading/auto-guarded/start",
        headers={"Authorization": "Bearer t"},
        json={"strategy_id": "scalp_macd_rsi_3m_v1", "mode": "passive", "actor": "t", "reason": "start"},
    )
    assert r.status_code == 200
    st = c.get("/api/live-trading/auto-guarded/status", headers={"Authorization": "Bearer t"})
    assert st.status_code == 200
    d = st.json()
    assert d["selected_strategy"] == "scalp_macd_rsi_3m_v1"
    assert d["effective_selected_strategy"] == "scalp_macd_rsi_3m_v1"


def test_live_exec_auto_guarded_tick_prefers_request_strategy_id(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_exec_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_auto_guarded",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto_state.json"),
        live_exec_sessions_store_json=str(tmp_path / "live_exec_sessions.json"),
        readiness_builder_state_store_json=str(tmp_path / "rb.json"),
        live_prep_candidates_store_json=str(tmp_path / "cand.json"),
        live_market_mode_store_json=str(tmp_path / "mm.json"),
    )
    monkeypatch.setattr(live_exec_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_exec_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())
    monkeypatch.setattr(live_exec_routes, "runtime_safety_validation_for_user_id", lambda *_a, **_k: {"ok": True, "blockers": []})
    monkeypatch.setattr(live_exec_routes, "get_broker_service", lambda: object())

    called: list[str] = []

    def fake_tick(**kw):
        called.append(str(kw.get("requested_strategy_id")))
        return {"ok": True, "state": {"last_eval_strategies": [str(kw.get("requested_strategy_id"))]}}

    monkeypatch.setattr(live_exec_routes, "tick_live_auto_guarded", fake_tick)

    c = TestClient(app)
    r = c.post(
        "/api/live-exec/auto-guarded/tick",
        headers={"Authorization": "Bearer t"},
        json={"strategy_id": "scalp_rsi_flag_hf_v1", "mode": "aggressive"},
    )
    assert r.status_code == 200
    assert called == ["scalp_rsi_flag_hf_v1"]


def test_live_exec_auto_guarded_start_persists_selected_strategy(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_exec_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_auto_guarded",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto_state.json"),
        live_exec_sessions_store_json=str(tmp_path / "live_exec_sessions.json"),
        readiness_builder_state_store_json=str(tmp_path / "rb.json"),
        live_prep_candidates_store_json=str(tmp_path / "cand.json"),
        live_market_mode_store_json=str(tmp_path / "mm.json"),
    )
    monkeypatch.setattr(live_exec_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_exec_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())
    monkeypatch.setattr(live_exec_routes, "runtime_safety_validation_for_user_id", lambda *_a, **_k: {"ok": True, "blockers": []})
    monkeypatch.setattr(live_exec_routes, "get_broker_service", lambda: object())
    monkeypatch.setattr(live_exec_routes, "start_readiness_builder", lambda **_kw: {"ok": True})
    monkeypatch.setattr(live_exec_routes, "get_readiness_builder_loop_status", lambda *_a, **_k: {"running": False})
    monkeypatch.setattr(live_exec_routes, "get_live_auto_guarded_loop_status", lambda *_a, **_k: {"running": False})

    c = TestClient(app)
    r = c.post(
        "/api/live-exec/auto-guarded/start",
        headers={"Authorization": "Bearer t"},
        json={"strategy_id": "scalp_rsi_flag_hf_v1", "mode": "aggressive", "actor": "desktop-user", "reason": "start"},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["state"]["selected_strategy"] == "scalp_rsi_flag_hf_v1"


def test_live_exec_start_then_tick_does_not_return_not_started(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_exec_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_auto_guarded",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto_state.json"),
        live_exec_sessions_store_json=str(tmp_path / "live_exec_sessions.json"),
        readiness_builder_state_store_json=str(tmp_path / "rb.json"),
        live_prep_candidates_store_json=str(tmp_path / "cand.json"),
        live_market_mode_store_json=str(tmp_path / "mm.json"),
    )
    monkeypatch.setattr(live_exec_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_exec_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())
    monkeypatch.setattr(live_exec_routes, "runtime_safety_validation_for_user_id", lambda *_a, **_k: {"ok": True, "blockers": []})
    monkeypatch.setattr(live_exec_routes, "get_broker_service", lambda: object())
    monkeypatch.setattr(live_exec_routes, "start_readiness_builder", lambda **_kw: {"ok": True})
    monkeypatch.setattr(live_exec_routes, "get_readiness_builder_loop_status", lambda *_a, **_k: {"running": False})
    monkeypatch.setattr(live_exec_routes, "get_live_auto_guarded_loop_status", lambda *_a, **_k: {"running": False})

    def fake_tick(**kw):
        assert kw["requested_strategy_id"] == "scalp_rsi_flag_hf_v1"
        st = live_exec_routes._auto_store(cfg).get("u1")
        assert st.enabled is True
        return {"ok": True, "state": {"enabled": True, "selected_strategy": st.selected_strategy, "last_eval_strategies": [st.selected_strategy]}}

    monkeypatch.setattr(live_exec_routes, "tick_live_auto_guarded", fake_tick)

    c = TestClient(app)
    s = c.post(
        "/api/live-exec/auto-guarded/start",
        headers={"Authorization": "Bearer t"},
        json={"strategy_id": "scalp_rsi_flag_hf_v1", "mode": "aggressive", "actor": "desktop-user", "reason": "start"},
    )
    assert s.status_code == 200
    t = c.post(
        "/api/live-exec/auto-guarded/tick",
        headers={"Authorization": "Bearer t"},
        json={"strategy_id": "scalp_rsi_flag_hf_v1", "mode": "aggressive"},
    )
    assert t.status_code == 200
    out = t.json()
    assert out["selected_strategy"] == "scalp_rsi_flag_hf_v1"

def test_auto_guarded_tick_uses_selected_strategy_not_default(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_trading_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_trading_safety_state_store_json=str(tmp_path / "live_safety.json"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto_state.json"),
    )
    monkeypatch.setattr(live_trading_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_trading_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())
    monkeypatch.setattr(live_trading_routes, "runtime_safety_validation_for_user_id", lambda *_a, **_k: {"ok": True, "blockers": []})
    monkeypatch.setattr(live_trading_routes, "get_broker_service", lambda: object())

    called: list[str] = []

    def fake_intraday(**kw):
        called.append(str(kw.get("strategy_id")))
        return {
            "ok": True,
            "asof_utc": "2026-01-01T00:00:00+00:00",
            "generated_orders": [
                {"symbol": "005930", "side": "buy", "quantity": 1, "price": 70000.0, "signal_reason": "ok"}
            ],
        }

    monkeypatch.setattr(live_trading_routes, "generate_intraday_shadow_report", fake_intraday)
    monkeypatch.setattr(
        live_trading_routes,
        "generate_final_betting_shadow_candidates",
        lambda **_kw: {"ok": True, "asof_utc": "x", "candidates": []},
    )

    c = TestClient(app)
    c.post(
        "/api/live-trading/auto-guarded/start",
        headers={"Authorization": "Bearer t"},
        json={"strategy_id": "scalp_macd_rsi_3m_v1", "mode": "passive", "actor": "t", "reason": "start"},
    )
    t = c.post("/api/live-trading/auto-guarded/tick", headers={"Authorization": "Bearer t"})
    assert t.status_code == 200
    out = t.json()
    assert out["effective_selected_strategy"] == "scalp_macd_rsi_3m_v1"
    assert out["last_eval_strategies"] == ["scalp_macd_rsi_3m_v1"]
    assert called == ["scalp_macd_rsi_3m_v1"]
    assert out["last_eval_candidates"][0]["strategy_id"] == "scalp_macd_rsi_3m_v1"


def test_auto_guarded_tick_falls_back_to_env_strategy(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_trading_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_trading_safety_state_store_json=str(tmp_path / "live_safety.json"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto_state.json"),
        live_auto_strategy="scalp_rsi_flag_hf_v1",
    )
    monkeypatch.setattr(live_trading_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_trading_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())
    monkeypatch.setattr(live_trading_routes, "runtime_safety_validation_for_user_id", lambda *_a, **_k: {"ok": True, "blockers": []})
    monkeypatch.setattr(live_trading_routes, "get_broker_service", lambda: object())

    def fake_intraday(**kw):
        return {"ok": True, "asof_utc": "x", "generated_orders": [{"symbol": "000660", "side": "buy", "quantity": 1, "price": 100.0}]}

    monkeypatch.setattr(live_trading_routes, "generate_intraday_shadow_report", fake_intraday)

    c = TestClient(app)
    t = c.post("/api/live-trading/auto-guarded/tick", headers={"Authorization": "Bearer t"})
    assert t.status_code == 200
    out = t.json()
    assert out["effective_selected_strategy"] == "scalp_rsi_flag_hf_v1"
    assert out["last_eval_strategies"] == ["scalp_rsi_flag_hf_v1"]


def test_compact_dashboard_includes_last_eval_candidates(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_trading_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_trading_safety_state_store_json=str(tmp_path / "live_safety.json"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto_state.json"),
    )
    monkeypatch.setattr(live_trading_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_trading_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())
    monkeypatch.setattr(live_trading_routes, "runtime_safety_validation_for_user_id", lambda *_a, **_k: {"ok": False, "blockers": ["x"]})
    monkeypatch.setattr(
        live_trading_routes,
        "get_broker_service",
        lambda: type(
            "S",
            (),
            {
                "get_plain_credentials": lambda _self, _uid: ("", "", "", "", "paper"),
            },
        )(),
    )

    st = live_trading_routes.LiveAutoGuardedState(user_id="u1")
    st.selected_strategy = "scalp_macd_rsi_3m_v1"
    st.last_eval_candidates = [{"status": "candidate", "strategy_id": "scalp_macd_rsi_3m_v1", "symbol": "005930", "side": "buy"}]
    store = live_trading_routes.LiveAutoGuardedStateStore(cfg.live_auto_guarded_state_store_json)
    store.upsert(st)

    c = TestClient(app)
    r = c.get("/api/live-trading/compact-dashboard", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    d = r.json()
    assert d["auto"]["last_eval_candidates"][0]["symbol"] == "005930"
    assert d["strategies"]["scalp_macd_rsi_3m_v1"]["auto_candidates"][0]["symbol"] == "005930"

