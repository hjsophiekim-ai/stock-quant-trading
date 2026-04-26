from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from backend.app.main import app

_KST = ZoneInfo("Asia/Seoul")


def test_sell_only_arm_set_and_get(monkeypatch, tmp_path: Path) -> None:
    from backend.app.api import live_prep_routes
    from backend.app.core.config import BackendSettings

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_shadow",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_prep_candidates_store_json=str(tmp_path / "candidates.json"),
        live_prep_equity_tracker_path=str(tmp_path / "eq.json"),
        live_prep_sell_only_arm_store_json=str(tmp_path / "arm.json"),
        live_prep_liquidation_plans_store_json=str(tmp_path / "plans.json"),
    )
    monkeypatch.setattr(live_prep_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_prep_routes, "is_execution_mode_allowed", lambda _cfg: True)
    monkeypatch.setattr(live_prep_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())

    c = TestClient(app)
    r0 = c.get("/api/live-prep/sell-only-arm/status", headers={"Authorization": "Bearer t"})
    assert r0.status_code == 200
    assert r0.json()["state"] is None

    r1 = c.post(
        "/api/live-prep/sell-only-arm",
        headers={"Authorization": "Bearer t"},
        json={"enabled": True, "armed_for_kst_date": "20260430", "actor": "tester", "reason": "arm"},
    )
    assert r1.status_code == 200
    assert r1.json()["state"]["enabled"] is True
    assert r1.json()["state"]["armed_for_kst_date"] == "20260430"

    r2 = c.get("/api/live-prep/sell-only-arm/status", headers={"Authorization": "Bearer t"})
    assert r2.status_code == 200
    assert r2.json()["state"]["enabled"] is True


def test_batch_liquidation_prepare_and_execute(monkeypatch, tmp_path: Path) -> None:
    from backend.app.api import live_prep_routes
    from backend.app.core.config import BackendSettings
    from app.orders.models import OrderResult

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_manual_approval",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_prep_candidates_store_json=str(tmp_path / "candidates.json"),
        live_prep_equity_tracker_path=str(tmp_path / "eq.json"),
        live_prep_sell_only_arm_store_json=str(tmp_path / "arm.json"),
        live_prep_liquidation_plans_store_json=str(tmp_path / "plans.json"),
    )
    monkeypatch.setattr(live_prep_routes, "get_backend_settings", lambda: cfg)
    monkeypatch.setattr(live_prep_routes, "is_execution_mode_allowed", lambda _cfg: True)
    monkeypatch.setattr(
        live_prep_routes,
        "runtime_safety_validation_for_user_id",
        lambda _cfg, _uid: {"ok": True, "blockers": [], "blocker_details": []},
    )
    monkeypatch.setattr(live_prep_routes, "is_live_order_execution_configured", lambda _cfg: True)
    monkeypatch.setattr(live_prep_routes, "get_current_user_from_auth_header", lambda _h: type("U", (), {"id": "u1"})())

    class Svc:
        def get_plain_credentials(self, _uid):
            return ("k", "s", "acct", "prod", "live")

        def ensure_cached_token_for_paper_start(self, _uid):
            return type(
                "T",
                (),
                {
                    "ok": True,
                    "access_token": "tok",
                    "failure_code": None,
                    "message": "",
                    "token_cache_hit": True,
                    "token_cache_source": "t",
                    "token_cache_persisted": True,
                },
            )()

        def _resolve_kis_api_base(self, _mode):
            return "https://openapi.koreainvestment.com:9443"

    monkeypatch.setattr(live_prep_routes, "get_broker_service", lambda: Svc())

    class FakeClient:
        def get_quote(self, _sym):
            return {"stck_prpr": "70000"}

    monkeypatch.setattr(live_prep_routes, "build_kis_client_for_live_user", lambda **_kw: FakeClient())

    from app.brokers import live_broker as live_broker_mod

    monkeypatch.setattr(
        live_broker_mod.LiveBroker,
        "get_positions",
        lambda self: [type("P", (), {"symbol": "005930", "quantity": 2, "average_price": 68000.0})()],
    )
    monkeypatch.setattr(live_broker_mod.LiveBroker, "get_open_orders", lambda self: [])
    monkeypatch.setattr(live_broker_mod.LiveBroker, "place_order", lambda self, order: OrderResult(order_id="OID", accepted=True, message="ok"))

    c = TestClient(app)
    rp = c.post(
        "/api/live-prep/batch-liquidation/prepare",
        headers={"Authorization": "Bearer t"},
        json={"use_market_order": True, "actor": "tester", "reason": "prep"},
    )
    assert rp.status_code == 200
    plan = rp.json()["plan"]
    assert plan["status"] == "prepared"
    assert plan["items"][0]["symbol"] == "005930"

    bad = c.post(
        f"/api/live-prep/batch-liquidation/{plan['plan_id']}/execute",
        headers={"Authorization": "Bearer t"},
        json={"confirm": "NO", "actor": "tester", "reason": "exec"},
    )
    assert bad.status_code == 400

    ok = c.post(
        f"/api/live-prep/batch-liquidation/{plan['plan_id']}/execute",
        headers={"Authorization": "Bearer t"},
        json={"confirm": "LIQUIDATE_ALL", "actor": "tester", "reason": "exec"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["plan"]["status"] == "executed"
    assert len(body["submitted"]) == 1


def test_sell_only_tick_calls_submit_when_armed(monkeypatch, tmp_path: Path) -> None:
    from backend.app.engine import live_sell_only_loop as mod
    from backend.app.core.config import BackendSettings
    from backend.app.services.live_exec_session_store import LiveExecSession, LiveExecSessionStore
    from backend.app.services.live_sell_arm_store import SellOnlyArmStore, SellOnlyArmState

    cfg = BackendSettings(
        trading_mode="live",
        execution_mode="live_manual_approval",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_prep_sell_only_arm_store_json=str(tmp_path / "arm.json"),
        live_exec_sessions_store_json=str(tmp_path / "sessions.json"),
        live_prep_sell_only_window_start_hhmm="090000",
        live_prep_sell_only_window_end_hhmm="110000",
        live_prep_sell_only_max_orders_per_tick=10,
    )
    store = SellOnlyArmStore(cfg.live_prep_sell_only_arm_store_json)
    store.upsert(SellOnlyArmState(user_id="u1", enabled=True, armed_for_kst_date="20260430"))

    sess_store = LiveExecSessionStore(cfg.live_exec_sessions_store_json)
    sess_store.upsert(
        LiveExecSession(
            session_id=sess_store.new_id(),
            user_id="u1",
            status="running",
            strategy_id="final_betting_v1",
            market="domestic",
            execution_mode="live_manual_approval",
            started_at_utc=datetime(2026, 4, 29, 0, 0, tzinfo=ZoneInfo("UTC")).isoformat(),
        )
    )

    monkeypatch.setattr(mod, "kst_now", lambda: datetime(2026, 4, 30, 9, 10, tzinfo=_KST))
    monkeypatch.setattr(
        mod,
        "compute_final_betting_exit_orders_live",
        lambda **_kw: {
            "ok": True,
            "sell_orders": [
                {
                    "symbol": "005930",
                    "side": "sell",
                    "quantity": 3,
                    "price": None,
                    "stop_loss_pct": None,
                    "strategy_id": "final_betting_v1",
                    "signal_id": None,
                    "signal_reason": "hard_exit_1100",
                    "created_at": datetime(2026, 4, 30, 0, 0, tzinfo=ZoneInfo("UTC")),
                }
            ],
        },
    )
    called = {"n": 0}

    def _fake_place(**_kw):
        called["n"] += 1
        return {"ok": True, "submitted": [{"symbol": "005930"}], "skipped": []}

    monkeypatch.setattr(mod, "_place_live_sell_orders", _fake_place)

    out = mod.run_sell_only_tick(cfg=cfg, broker_service=object(), arm_store=store, risk_events_jsonl=str(tmp_path / "events.jsonl"))
    assert out["ok"] is True
    assert called["n"] == 1

