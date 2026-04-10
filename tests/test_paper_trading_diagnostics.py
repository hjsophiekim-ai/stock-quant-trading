from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.engine.paper_session_controller import PaperSessionController
from backend.app.main import app


def test_diagnostics_includes_failure_fields() -> None:
    c = TestClient(app)
    r = c.get("/api/paper-trading/diagnostics")
    assert r.status_code == 200
    body = r.json()
    assert "session_status" in body
    assert "failure_kind" in body or body.get("failure_kind") is None
    assert "backend_git_sha" in body
    assert "backend_build_time" in body
    assert "backend_app_version" in body


def test_apply_tick_diagnostics_includes_budget_fields() -> None:
    ctl = PaperSessionController()
    ctl._apply_paper_tick_diagnostics(
        {
            "ok": True,
            "token_source": "test_connection_reuse",
            "universe_cache_hit": True,
            "kospi_cache_hit": False,
            "request_budget_mode": "paper_conserve",
            "throttled_mode": True,
            "paper_tick_interval_sec": 600,
        },
    )
    d = ctl._paper_diagnostics
    assert d.get("universe_cache_hit") is True
    assert d.get("kospi_cache_hit") is False
    assert d.get("request_budget_mode") == "paper_conserve"
    assert d.get("throttled_mode") is True
    assert d.get("paper_tick_interval_sec") == 600
    assert d.get("failure_kind") is None
