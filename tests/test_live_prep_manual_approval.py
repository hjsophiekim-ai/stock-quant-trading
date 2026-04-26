from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import app


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def test_live_prep_submit_blocked_when_not_manual_mode(monkeypatch, tmp_path: Path) -> None:
    from backend.app.api import live_prep_routes
    from backend.app.core.config import BackendSettings
    from backend.app.services.live_prep_store import LiveCandidate

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_prep_candidates_store_json=str(tmp_path / "candidates.json"),
        live_prep_equity_tracker_path=str(tmp_path / "eq.json"),
    )
    monkeypatch.setattr(live_prep_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_prep_routes, "is_execution_mode_allowed", lambda _cfg: True)
    monkeypatch.setattr(live_prep_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())

    store = live_prep_routes.LiveCandidateStore(cfg.live_prep_candidates_store_json)
    cand = LiveCandidate(
        candidate_id="c1",
        status="approved",
        symbol="005930",
        side="buy",
        strategy_id="final_betting_v1",
        quantity=1,
        price=70000.0,
        stop_loss_pct=2.0,
    )
    store.upsert(cand)

    c = TestClient(app)
    r = c.post("/api/live-prep/candidates/c1/submit", headers={"Authorization": "Bearer test"}, json={"actor": "t", "reason": "x"})
    assert r.status_code == 403


def test_live_prep_requires_approval_before_submit(monkeypatch, tmp_path: Path) -> None:
    from backend.app.api import live_prep_routes
    from backend.app.core.config import BackendSettings
    from backend.app.services.live_prep_store import LiveCandidate

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_manual_approval",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_prep_candidates_store_json=str(tmp_path / "candidates.json"),
        live_prep_equity_tracker_path=str(tmp_path / "eq.json"),
    )
    monkeypatch.setattr(live_prep_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_prep_routes, "is_execution_mode_allowed", lambda _cfg: True)
    monkeypatch.setattr(live_prep_routes, "runtime_safety_validation", lambda: {"ok": True, "blockers": []})
    monkeypatch.setattr(live_prep_routes, "is_live_order_execution_configured", lambda _cfg: True)
    monkeypatch.setattr(live_prep_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())

    class Svc:
        def get_plain_credentials(self, _uid):
            return ("k", "s", "acct", "prod", "live")

        def ensure_cached_token_for_paper_start(self, _uid):
            return type("T", (), {"ok": True, "access_token": "tok", "failure_code": None, "message": "", "token_cache_hit": True, "token_cache_source": "t", "token_cache_persisted": True})()

        def _resolve_kis_api_base(self, _mode):
            return "https://openapi.koreainvestment.com:9443"

    monkeypatch.setattr(live_prep_routes, "get_broker_service", lambda: Svc())
    monkeypatch.setattr(live_prep_routes, "build_kis_client_for_live_user", lambda **_kw: object())

    from app.brokers import live_broker as live_broker_mod
    from app.orders.models import OrderResult

    monkeypatch.setattr(live_broker_mod.LiveBroker, "get_positions", lambda self: [])
    monkeypatch.setattr(live_broker_mod.LiveBroker, "get_open_orders", lambda self: [])
    monkeypatch.setattr(live_broker_mod.LiveBroker, "get_cash", lambda self: 1_000_000.0)
    monkeypatch.setattr(live_broker_mod.LiveBroker, "place_order", lambda self, order: OrderResult(order_id="OID1", accepted=True, message="ok"))

    store = live_prep_routes.LiveCandidateStore(cfg.live_prep_candidates_store_json)
    cand = LiveCandidate(
        candidate_id="c1",
        status="approval_pending",
        symbol="005930",
        side="buy",
        strategy_id="final_betting_v1",
        quantity=1,
        price=70000.0,
        stop_loss_pct=2.0,
    )
    store.upsert(cand)

    c = TestClient(app)
    r0 = c.post("/api/live-prep/candidates/c1/submit", headers={"Authorization": "Bearer test"}, json={"actor": "t", "reason": "x"})
    assert r0.status_code == 409


def test_live_prep_approval_and_submit_flow_writes_audit(monkeypatch, tmp_path: Path) -> None:
    from backend.app.api import live_prep_routes
    from backend.app.core.config import BackendSettings
    from backend.app.services.live_prep_store import LiveCandidate

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_manual_approval",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_prep_candidates_store_json=str(tmp_path / "candidates.json"),
        live_prep_equity_tracker_path=str(tmp_path / "eq.json"),
        live_prep_daily_loss_limit_pct=2.0,
        live_prep_max_positions=6,
    )
    monkeypatch.setattr(live_prep_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_prep_routes, "is_execution_mode_allowed", lambda _cfg: True)
    monkeypatch.setattr(live_prep_routes, "runtime_safety_validation", lambda: {"ok": True, "blockers": []})
    monkeypatch.setattr(live_prep_routes, "is_live_order_execution_configured", lambda _cfg: True)
    monkeypatch.setattr(live_prep_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())

    class Svc:
        def get_plain_credentials(self, _uid):
            return ("k", "s", "acct", "prod", "live")

        def ensure_cached_token_for_paper_start(self, _uid):
            return type("T", (), {"ok": True, "access_token": "tok", "failure_code": None, "message": "", "token_cache_hit": True, "token_cache_source": "t", "token_cache_persisted": True})()

        def _resolve_kis_api_base(self, _mode):
            return "https://openapi.koreainvestment.com:9443"

    monkeypatch.setattr(live_prep_routes, "get_broker_service", lambda: Svc())
    monkeypatch.setattr(live_prep_routes, "build_kis_client_for_live_user", lambda **_kw: type("C", (), {"get_quote": lambda self, s: {"stck_prpr": "70000"}})())

    from app.brokers import live_broker as live_broker_mod
    from app.orders.models import OrderResult

    monkeypatch.setattr(live_broker_mod.LiveBroker, "get_positions", lambda self: [])
    monkeypatch.setattr(live_broker_mod.LiveBroker, "get_open_orders", lambda self: [])
    monkeypatch.setattr(live_broker_mod.LiveBroker, "get_cash", lambda self: 1_000_000.0)
    monkeypatch.setattr(live_broker_mod.LiveBroker, "place_order", lambda self, order: OrderResult(order_id="OID2", accepted=True, message="ok"))

    store = live_prep_routes.LiveCandidateStore(cfg.live_prep_candidates_store_json)
    cand = LiveCandidate(
        candidate_id="c1",
        status="approval_pending",
        symbol="005930",
        side="buy",
        strategy_id="final_betting_v1",
        quantity=1,
        price=70000.0,
        stop_loss_pct=2.0,
    )
    store.upsert(cand)

    c = TestClient(app)
    ra = c.post("/api/live-prep/candidates/c1/approve", headers={"Authorization": "Bearer test"}, json={"actor": "tester", "reason": "approve"})
    assert ra.status_code == 200

    rs = c.post("/api/live-prep/candidates/c1/submit", headers={"Authorization": "Bearer test"}, json={"actor": "tester", "reason": "submit"})
    assert rs.status_code == 200
    body = rs.json()
    assert body["candidate"]["status"] == "submitted"
    assert body["candidate"]["broker_order_id"] == "OID2"

    rs2 = c.post("/api/live-prep/candidates/c1/submit", headers={"Authorization": "Bearer test"}, json={"actor": "tester", "reason": "submit2"})
    assert rs2.status_code in (409, 403)

    events = _read_jsonl(Path(cfg.risk_events_jsonl))
    types = [e.get("event_type") for e in events]
    assert "LIVE_PREP_CANDIDATE_APPROVED" in types
    assert "LIVE_PREP_SUBMITTED" in types


def test_live_prep_emergency_stop_blocks_submit(monkeypatch, tmp_path: Path) -> None:
    from backend.app.api import live_prep_routes
    from backend.app.core.config import BackendSettings
    from backend.app.services.live_prep_store import LiveCandidate

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_manual_approval",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_prep_candidates_store_json=str(tmp_path / "candidates.json"),
        live_prep_equity_tracker_path=str(tmp_path / "eq.json"),
    )
    monkeypatch.setattr(live_prep_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_prep_routes, "is_execution_mode_allowed", lambda _cfg: True)
    monkeypatch.setattr(live_prep_routes, "runtime_safety_validation", lambda: {"ok": False, "blockers": ["APP emergency stop is enabled"]})
    monkeypatch.setattr(live_prep_routes, "is_live_order_execution_configured", lambda _cfg: True)
    monkeypatch.setattr(live_prep_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())

    store = live_prep_routes.LiveCandidateStore(cfg.live_prep_candidates_store_json)
    cand = LiveCandidate(
        candidate_id="c1",
        status="approved",
        symbol="005930",
        side="buy",
        strategy_id="final_betting_v1",
        quantity=1,
        price=70000.0,
        stop_loss_pct=2.0,
    )
    store.upsert(cand)

    c = TestClient(app)
    r = c.post("/api/live-prep/candidates/c1/submit", headers={"Authorization": "Bearer test"}, json={"actor": "t", "reason": "x"})
    assert r.status_code == 403


def test_live_prep_hf_shadow_endpoint_never_submits(monkeypatch, tmp_path: Path) -> None:
    from backend.app.api import live_prep_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_prep_candidates_store_json=str(tmp_path / "candidates.json"),
        live_prep_equity_tracker_path=str(tmp_path / "eq.json"),
    )
    monkeypatch.setattr(live_prep_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_prep_routes, "is_execution_mode_allowed", lambda _cfg: True)
    monkeypatch.setattr(live_prep_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())
    monkeypatch.setattr(
        live_prep_routes,
        "generate_intraday_shadow_report",
        lambda **_kw: {"ok": True, "strategy_id": "scalp_rsi_flag_hf_v1", "order_allowed": False, "generated_orders": [], "generated_order_count": 0},
    )

    c = TestClient(app)
    r = c.post("/api/live-prep/hf-shadow/generate?strategy_id=scalp_rsi_flag_hf_v1", headers={"Authorization": "Bearer test"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["order_allowed"] is False

