from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.scheduler.jobs import SchedulerJobs, _no_order_reason
from app.strategy.swing_strategy import SwingStrategy
from backend.app.main import app


def test_no_order_reason_candidates_empty() -> None:
    s = _no_order_reason(
        halted=False,
        halt_message=None,
        candidate_count=0,
        generated_order_count=0,
        regime="bullish_trend",
        position_count=0,
    )
    assert "후보" in s


def test_jobs_report_includes_generated_meta() -> None:
    jobs = SchedulerJobs(strategy=SwingStrategy(), broker=MagicMock())
    jobs.broker.get_cash.return_value = 1_000_000.0
    jobs.broker.get_positions.return_value = []
    jobs.broker.initial_cash = 1_000_000.0
    out = jobs.run_daily_cycle()
    assert "candidate_count" in out
    assert "generated_order_count" in out
    assert "no_order_reason" in out
    assert "regime" in out
    assert isinstance(out.get("generated_orders"), list)
    assert "candidate_filter_breakdown" in out
    assert isinstance(out.get("candidate_filter_breakdown"), list)


def test_paper_dashboard_data_endpoint_requires_auth() -> None:
    c = TestClient(app)
    r = c.get("/api/paper-trading/dashboard-data")
    assert r.status_code == 401


def test_paper_dashboard_data_ok_when_session_matches_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.app.api.paper_trading_routes.get_current_user_from_auth_header",
        lambda _h: SimpleNamespace(id="u-paper"),
    )
    ctrl = MagicMock()
    ctrl.get_dashboard_payload.return_value = {
        "ok": True,
        "status": "running",
        "strategy_id": "swing_v1",
        "failure_streak": 0,
        "last_error": None,
        "last_tick_at": "2020-01-01T00:00:00+00:00",
        "last_tick_summary": {},
        "positions": [{"symbol": "005930", "quantity": 1, "average_price": 70000}],
        "open_orders": [{"order_id": "x", "symbol": "005930"}],
        "open_orders_error": None,
        "recent_fills": [],
        "recent_fills_error": None,
        "diagnostics": {},
        "candidate_count": 2,
        "ranking": [{"symbol": "005930", "score": 0.5, "reasons": ["ok"]}],
        "generated_order_count": 0,
        "generated_orders": [],
        "accepted_orders": 0,
        "rejected_orders": 0,
        "no_order_reason": "후보는 있으나 전략 진입 조건 미충족",
        "regime": "bullish_trend",
        "last_diagnostics": [],
        "candidates": ["005930"],
    }
    monkeypatch.setattr(
        "backend.app.api.paper_trading_routes.get_paper_session_controller",
        lambda: ctrl,
    )

    c = TestClient(app)
    r = c.get("/api/paper-trading/dashboard-data", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert body.get("positions")
    assert body.get("open_orders")
    assert body.get("no_order_reason")
    ctrl.get_dashboard_payload.assert_called_once()


def test_dashboard_summary_prefers_paper_fills_when_running(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.api.routes import dashboard as dash_mod

    monkeypatch.setattr(
        dash_mod,
        "_try_current_user",
        lambda _h: SimpleNamespace(id="u1"),
    )
    monkeypatch.setattr(
        dash_mod,
        "_user_broker_snapshot",
        lambda _uid: {"connection_status": "success"},
    )
    monkeypatch.setattr(
        dash_mod,
        "_paper_trading_status",
        lambda: {
            "session_user_id": "u1",
            "status": "running",
            "user_session_active": True,
            "strategy_id": "swing_v1",
        },
    )

    fake_ctrl = MagicMock()

    def _payload(uid: str) -> dict:
        assert uid == "u1"
        return {
            "ok": True,
            "open_orders": [],
            "open_orders_error": None,
            "recent_fills": [{"symbol": "005930", "side": "buy", "quantity": 1, "price": 1.0, "strategy_id": ""}],
            "recent_fills_error": None,
            "positions": [{"symbol": "005930", "quantity": 1, "average_price": 100.0}],
            "ranking": [],
            "regime": "bullish_trend",
            "no_order_reason": "x",
            "generated_order_count": 0,
            "failure_streak": 0,
        }

    fake_ctrl.get_dashboard_payload.side_effect = _payload
    monkeypatch.setattr(
        "backend.app.engine.paper_session_controller.get_paper_session_controller",
        lambda: fake_ctrl,
    )

    c = TestClient(app)
    r = c.get("/api/dashboard/summary", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    body = r.json()
    assert body["data_quality"]["recent_fills_user_scoped"] is True
    assert body["recent_fills"][0]["symbol"] == "005930"
