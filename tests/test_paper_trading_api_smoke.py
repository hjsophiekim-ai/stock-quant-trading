from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_debug_storage_paths_returns_paths() -> None:
    c = TestClient(app)
    r = c.get("/api/debug/storage-paths")
    assert r.status_code == 200
    body = r.json()
    assert "auth_users" in body
    assert "broker_accounts_db" in body
    assert body["auth_users"]["path"]


def test_paper_trading_diagnostics_endpoint() -> None:
    c = TestClient(app)
    r = c.get("/api/paper-trading/diagnostics")
    assert r.status_code == 200
    body = r.json()
    assert "session_status" in body or "session_last_error" in body
