from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_runtime_info_returns_module_paths_and_version() -> None:
    c = TestClient(app)
    r = c.get("/api/debug/runtime-info")
    assert r.status_code == 200
    body = r.json()
    assert "backend_git_sha" in body
    assert "backend_build_time" in body
    assert "python_executable" in body
    files = body.get("module_files") or {}
    assert str(files.get("app.clients.kis_client") or "").endswith("kis_client.py")
    assert str(files.get("backend.app.engine.user_paper_loop") or "").endswith("user_paper_loop.py")
    assert str(files.get("app.brokers.kis_paper_broker") or "").endswith("kis_paper_broker.py")
