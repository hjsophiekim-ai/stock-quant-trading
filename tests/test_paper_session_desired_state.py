from __future__ import annotations

import json
from types import SimpleNamespace

from app.config import get_settings
from backend.app.engine import paper_session_controller as mod


class _DummyThread:
    def __init__(self, *args, **kwargs):
        self._alive = False

    def start(self):
        self._alive = True

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        self._alive = False


def _svc_ok():
    return SimpleNamespace(
        get_account=lambda _u: SimpleNamespace(trading_mode="paper", connection_status="success"),
        _resolve_kis_api_base=lambda _m: "https://openapivts.koreainvestment.com:29443",
        ensure_cached_token_for_paper_start=lambda _u: SimpleNamespace(
            ok=True,
            token_cache_hit=True,
            token_cache_source="test",
            token_cache_persisted=True,
            cache_miss_reason=None,
            message="",
            token_error_code=None,
            failure_code=None,
        ),
    )


def test_paper_desired_state_saved_and_cleared(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_SESSION_STATE_PATH", str(tmp_path / "paper_state.json"))
    get_settings.cache_clear()
    monkeypatch.setattr(mod, "get_broker_service", _svc_ok)
    monkeypatch.setattr(mod.threading, "Thread", _DummyThread)

    ctrl = mod.PaperSessionController()
    out = ctrl.start("u1", "swing_v1")
    assert out["ok"] is True
    state_path = tmp_path / "paper_state.json"
    assert state_path.is_file()
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    assert raw["desired_running"] is True
    assert raw["user_id"] == "u1"
    assert raw["strategy_id"] == "swing_v1"

    stop = ctrl.stop("u1")
    assert stop["ok"] is True
    assert not state_path.exists()


def test_paper_auto_resume_from_desired_state(tmp_path, monkeypatch):
    state_path = tmp_path / "paper_state.json"
    state_path.write_text(
        json.dumps(
            {
                "desired_running": True,
                "status": "running",
                "user_id": "resume-user",
                "strategy_id": "swing_v1",
                "started_at_utc": "2026-01-01T00:00:00+00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PAPER_SESSION_STATE_PATH", str(state_path))
    monkeypatch.setenv("PAPER_SESSION_AUTO_RESUME", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(mod, "get_broker_service", _svc_ok)
    monkeypatch.setattr(mod.threading, "Thread", _DummyThread)

    ctrl = mod.PaperSessionController()
    status = ctrl.status_payload()
    assert status["desired_running"] is True
    assert status["session_user_id"] == "resume-user"
    assert status["strategy_id"] == "swing_v1"
    assert status["resume_info"]["restored_from_state"] is True
    assert status["resume_info"]["last_resume_error"] in (None, "")
