from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_debug_storage_paths_has_writable_flags() -> None:
    c = TestClient(app)
    r = c.get("/api/debug/storage-paths")
    assert r.status_code == 200
    body = r.json()
    assert "backend_data_dir" in body
    assert "backend_data_dir_writable" in body
    assert "auth_users" in body
    assert "broker_accounts_db" in body
    assert isinstance(body["backend_data_dir_writable"], bool)
