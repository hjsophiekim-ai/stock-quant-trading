"""PaperSessionController._account_failed_paper_tick — streak·risk_off 라우팅 회귀 검증."""

from __future__ import annotations

import pytest

from app.config import get_settings
from backend.app.engine.paper_session_controller import PaperSessionController


@pytest.fixture(autouse=True)
def _clear_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_token_recovery_wait_does_not_increment_any_streak() -> None:
    c = PaperSessionController()
    c._status = "running"
    c._failure_streak = 4
    c._token_failure_streak = 3
    c._account_failed_paper_tick(
        {"ok": False, "failure_kind": "token_recovery_wait", "error": "wait"},
    )
    assert c._failure_streak == 4
    assert c._token_failure_streak == 3
    assert c._status == "running"


def test_token_hard_failure_increments_token_streak_resets_general() -> None:
    c = PaperSessionController()
    c._status = "running"
    c._failure_streak = 4
    c._token_failure_streak = 0
    c._account_failed_paper_tick({"ok": False, "failure_kind": "token_hard_failure", "error": "hard"})
    assert c._failure_streak == 0
    assert c._token_failure_streak == 1
    assert c._status == "running"


def test_token_hard_failure_risk_off_after_max_token_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_SESSION_MAX_TOKEN_FAILURES_BEFORE_RISK_OFF", "3")
    get_settings.cache_clear()
    c = PaperSessionController()
    c._status = "running"
    for _ in range(2):
        c._account_failed_paper_tick({"ok": False, "failure_kind": "token_hard_failure", "error": "h"})
    assert c._status == "running"
    c._account_failed_paper_tick({"ok": False, "failure_kind": "token_hard_failure", "error": "h"})
    assert c._status == "risk_off"
    assert c._risk_off_reason == "kis_oauth_token_failures"


def test_non_token_failure_increments_general_streak_resets_token_streak() -> None:
    c = PaperSessionController()
    c._token_failure_streak = 2
    c._failure_streak = 0
    c._account_failed_paper_tick({"ok": False, "failure_kind": "kis_client_error", "error": "api"})
    assert c._failure_streak == 1
    assert c._token_failure_streak == 0


def test_status_payload_includes_token_streak_and_risk_fields() -> None:
    c = PaperSessionController()
    c._token_failure_streak = 2
    c._risk_off_reason = "kis_oauth_token_failures"
    p = c.status_payload()
    assert p.get("token_failure_streak") == 2
    assert p.get("max_token_failures") == get_settings().paper_session_max_token_failures_before_risk_off
    assert p.get("risk_off_reason") == "kis_oauth_token_failures"
