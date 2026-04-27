from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app.main import app


def _auth_ok(monkeypatch) -> None:
    from backend.app.api import live_trading_routes

    monkeypatch.setattr(live_trading_routes, "get_current_user_from_auth_header", lambda _h: SimpleNamespace(id="u1"))


def test_readiness_builder_status_payload(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_trading_routes
    from backend.app.core.config import BackendSettings

    _auth_ok(monkeypatch)
    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_auto_guarded",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        readiness_builder_state_store_json=str(tmp_path / "rb.json"),
        portfolio_data_dir=str(tmp_path / "portfolio"),
        risk_order_audit_jsonl=str(tmp_path / "risk" / "order_audit.jsonl"),
        readiness_builder_enabled=True,
    )
    monkeypatch.setattr(live_trading_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_trading_routes, "evaluate_paper_readiness", lambda _cfg: SimpleNamespace(ok=False, bypassed=False, reason_code="PAPER_READINESS_FAILED"))
    monkeypatch.setattr(live_trading_routes, "paper_readiness_to_dict", lambda _pr: {"ok": False})
    monkeypatch.setattr(live_trading_routes, "paper_readiness_data_health", lambda _cfg: {"overall_data_ok": False})

    c = TestClient(app)
    r = c.get("/api/live-trading/readiness-builder/status?market=domestic", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert "state" in j
    assert "loop" in j
    assert "data_health" in j
    assert j.get("market") == "domestic"


def test_auto_guarded_start_auto_starts_readiness_builder_when_paper_readiness_failed(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_exec_routes
    from backend.app.core.config import BackendSettings

    monkeypatch.setattr(live_exec_routes, "get_current_user_from_auth_header", lambda _h: SimpleNamespace(id="u1"))
    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_auto_guarded",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto.json"),
        live_exec_sessions_store_json=str(tmp_path / "sessions.json"),
        readiness_builder_state_store_json=str(tmp_path / "rb.json"),
        readiness_builder_enabled=True,
        readiness_builder_auto_start_on_live_auto=True,
    )
    monkeypatch.setattr(live_exec_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(
        live_exec_routes,
        "runtime_safety_validation_for_user_id",
        lambda *_a, **_k: {"ok": False, "blockers": ["x"], "blocker_details": [{"code": "PAPER_READINESS_FAILED", "message": "m"}]},
    )

    class _Svc:
        pass

    monkeypatch.setattr(live_exec_routes, "get_broker_service", lambda: _Svc())
    monkeypatch.setattr(live_exec_routes, "start_live_auto_guarded_loop", lambda **_kw: {"ok": True, "skipped": True})

    started = {"n": 0}

    def _fake_start_readiness_builder(**_kw):
        started["n"] += 1
        return {"ok": True, "started": True}

    monkeypatch.setattr(live_exec_routes, "start_readiness_builder", _fake_start_readiness_builder)

    c = TestClient(app)
    r = c.post(
        "/api/live-exec/auto-guarded/start",
        json={"actor": "test", "reason": "start"},
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert started["n"] == 1
    assert j.get("state", {}).get("last_decision") == "waiting_for_readiness"


def test_readiness_builder_tick_increases_rows_via_injected_warmup(monkeypatch, tmp_path) -> None:
    from backend.app.engine import live_readiness_builder as rb
    from backend.app.core.config import BackendSettings

    base = tmp_path / "data"
    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_auto_guarded",
        backend_data_dir=str(base),
        portfolio_data_dir="backend_data/portfolio",
        risk_order_audit_jsonl="backend_data/risk/order_audit.jsonl",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        readiness_builder_state_store_json=str(tmp_path / "rb.json"),
        readiness_builder_target_pnl_rows=2,
        readiness_builder_target_audit_rows=1,
    )

    pnl = base / "portfolio" / "pnl_history.jsonl"
    pnl.parent.mkdir(parents=True, exist_ok=True)
    pnl.write_text("", encoding="utf-8")

    def fake_eval(_cfg):
        return SimpleNamespace(ok=True, bypassed=False)

    monkeypatch.setattr(rb, "evaluate_paper_readiness", fake_eval)
    monkeypatch.setattr(rb, "_maybe_start_paper_session", lambda *_a, **_k: (True, "paper_session_started"))
    monkeypatch.setattr(rb, "run_portfolio_sync", lambda *_a, **_k: None, raising=False)
    calls = {"n": 0}

    def fake_health(_cfg):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"pnl_rows_found": 0, "audit_rows_found_tail": 0}
        return {"pnl_rows_found": 2, "audit_rows_found_tail": 1}

    monkeypatch.setattr(rb, "paper_readiness_data_health", fake_health)

    wrote = {"n": 0}

    def warmup(_cfg):
        p = base / "risk" / "order_audit.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"ts_utc":"x","decision":{"approved":true}}\n', encoding="utf-8")
        wrote["n"] += 1
        return 1, "ok"

    out = rb.tick_readiness_builder_once(cfg=cfg, broker_service=object(), user_id="u1", warmup_func=warmup)
    assert out.get("ok") is True
    assert wrote["n"] == 1


def test_readiness_builder_paper_session_status_payload_requires_market(monkeypatch, tmp_path) -> None:
    from backend.app.engine import live_readiness_builder as rb
    from backend.app.engine import paper_session_controller as psc
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_auto_guarded",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        readiness_builder_state_store_json=str(tmp_path / "rb.json"),
    )

    calls: dict[str, object] = {}

    class Hub:
        def status_payload(self, *, market: str | None, pref_user_id: str | None = None):
            calls["market"] = market
            calls["pref_user_id"] = pref_user_id
            return {"user_session_active": False}

        def start(self, user_id: str, strategy_id: str, market: str | None = None):
            calls["start_market"] = market
            return {"ok": True}

    monkeypatch.setattr(psc, "get_paper_session_controller", lambda: Hub())
    ok, msg = rb._maybe_start_paper_session(cfg, broker_service=object(), user_id="u1", market="domestic")
    assert ok is True
    assert calls.get("market") == "domestic"
    assert calls.get("start_market") == "domestic"


def test_readiness_builder_tick_api_increments_attempts_and_has_no_last_error(monkeypatch, tmp_path) -> None:
    from backend.app.api import live_trading_routes
    from backend.app.api import broker_routes
    from backend.app.core.config import BackendSettings
    from backend.app.services.live_readiness_builder_store import LiveReadinessBuilderStore

    _auth_ok(monkeypatch)
    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_auto_guarded",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        readiness_builder_state_store_json=str(tmp_path / "rb.json"),
        readiness_builder_enabled=True,
    )
    monkeypatch.setattr(live_trading_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(broker_routes, "get_broker_service", lambda: object())

    def fake_tick(*, cfg, broker_service, user_id, market=None):
        store = LiveReadinessBuilderStore(cfg.readiness_builder_state_store_json)
        st = store.get(user_id)
        st.enabled = True
        st.attempts = int(st.attempts or 0) + 1
        st.last_error = None
        store.upsert(st)
        return {"ok": True, "state": st.__dict__, "status": "building"}

    monkeypatch.setattr(live_trading_routes, "tick_readiness_builder_once", fake_tick)

    c = TestClient(app)
    r = c.post("/api/live-trading/readiness-builder/tick?market=domestic", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    st = LiveReadinessBuilderStore(cfg.readiness_builder_state_store_json).get("u1")
    assert int(st.attempts or 0) == 1
    assert st.last_error is None

