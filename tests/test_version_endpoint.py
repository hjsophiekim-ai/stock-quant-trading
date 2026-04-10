from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_api_version_returns_keys() -> None:
    c = TestClient(app)
    r = c.get("/api/version")
    assert r.status_code == 200
    body = r.json()
    assert "git_sha" in body
    assert "build_time" in body
    assert "app_version" in body
    assert isinstance(body["app_version"], str)
