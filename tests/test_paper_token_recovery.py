from __future__ import annotations

import time
import pytest

from app.config import get_settings
from backend.app.auth.kis_auth import KISTokenResult
from backend.app.engine.paper_session_controller import PaperSessionController
from backend.app.engine.user_paper_loop import UserPaperTradingLoop


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_interval_probe_skips_oauth_when_token_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_KIS_TOKEN_REFRESH_SEC", "60")
    get_settings.cache_clear()
    calls = {"n": 0}

    def fake_issue(**_kwargs) -> KISTokenResult:
        calls["n"] += 1
        return KISTokenResult(True, "should-not", "ok", "OK", status_code=200)

    monkeypatch.setattr("backend.app.engine.user_paper_loop.issue_access_token", fake_issue)
    loop = UserPaperTradingLoop(
        app_key="k",
        app_secret="s",
        account_no="1234567890",
        product_code="01",
        api_base="https://openapivts.koreainvestment.com:29443",
        strategy_id="swing_relaxed_v2",
        user_tag="u1",
        initial_access_token="mem-tok",
        initial_token_source_label="sqlite_encrypted",
        reload_cached_token_fn=lambda: None,
    )
    monkeypatch.setattr(loop, "_probe_token_valid", lambda _t: True)
    loop._token_monotonic = time.monotonic() - 120.0
    tok = loop._ensure_valid_access_token()
    assert tok == "mem-tok"
    assert calls["n"] == 0
    assert loop._token_recovery_mode == "interval_probe_valid"


def test_oauth_failure_keeps_in_memory_when_probe_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_KIS_TOKEN_REFRESH_SEC", "60")
    monkeypatch.setenv("PAPER_KIS_TOKEN_FORCE_REISSUE_WALL_SEC", "86400")
    get_settings.cache_clear()

    def fake_issue(**_kwargs) -> KISTokenResult:
        return KISTokenResult(
            False,
            None,
            "http 403",
            "TOKEN_HTTP_ERROR",
            status_code=403,
        )

    monkeypatch.setattr("backend.app.engine.user_paper_loop.issue_access_token", fake_issue)
    monkeypatch.setattr("backend.app.engine.user_paper_loop.time.sleep", lambda _s: None)
    loop = UserPaperTradingLoop(
        app_key="k",
        app_secret="s",
        account_no="1234567890",
        product_code="01",
        api_base="https://openapivts.koreainvestment.com:29443",
        strategy_id="swing_relaxed_v2",
        user_tag="u1",
        initial_access_token="mem-tok",
        reload_cached_token_fn=lambda: None,
    )
    _pc = {"n": 0}

    def probe(t: str) -> bool:
        _pc["n"] += 1
        if _pc["n"] == 1:
            return False
        return t == "mem-tok"

    monkeypatch.setattr(loop, "_probe_token_valid", probe)
    loop._token_monotonic = time.monotonic() - 120.0
    tok = loop._ensure_valid_access_token()
    assert tok == "mem-tok"
    assert loop._token_recovery_mode == "in_memory_stale_after_oauth_fail"


def test_sqlite_cached_fallback_when_memory_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_KIS_TOKEN_REFRESH_SEC", "60")
    monkeypatch.setenv("PAPER_KIS_TOKEN_FORCE_REISSUE_WALL_SEC", "86400")
    get_settings.cache_clear()

    monkeypatch.setattr("backend.app.engine.user_paper_loop.issue_access_token", lambda **_k: KISTokenResult(False, None, "x", "TOKEN_HTTP_ERROR", status_code=403))
    monkeypatch.setattr("backend.app.engine.user_paper_loop.time.sleep", lambda _s: None)

    def probe(t: str) -> bool:
        return t == "db-tok"

    loop = UserPaperTradingLoop(
        app_key="k",
        app_secret="s",
        account_no="1234567890",
        product_code="01",
        api_base="https://openapivts.koreainvestment.com:29443",
        strategy_id="swing_relaxed_v2",
        user_tag="u1",
        initial_access_token="dead",
        reload_cached_token_fn=lambda: "db-tok",
    )
    monkeypatch.setattr(loop, "_probe_token_valid", probe)
    loop._token_monotonic = time.monotonic() - 120.0
    tok = loop._ensure_valid_access_token()
    assert tok == "db-tok"
    assert loop._token_recovery_mode == "sqlite_cached_fallback"


def test_hard_failure_raises_token_hard_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_KIS_TOKEN_REFRESH_SEC", "60")
    get_settings.cache_clear()
    monkeypatch.setattr("backend.app.engine.user_paper_loop.issue_access_token", lambda **_k: KISTokenResult(False, None, "x", "TOKEN_HTTP_ERROR", status_code=403))
    monkeypatch.setattr("backend.app.engine.user_paper_loop.time.sleep", lambda _s: None)
    loop = UserPaperTradingLoop(
        app_key="k",
        app_secret="s",
        account_no="1234567890",
        product_code="01",
        api_base="https://openapivts.koreainvestment.com:29443",
        strategy_id="swing_relaxed_v2",
        user_tag="u1",
        initial_access_token="dead",
        reload_cached_token_fn=lambda: None,
    )
    monkeypatch.setattr(loop, "_probe_token_valid", lambda _t: False)
    loop._token_monotonic = time.monotonic() - 120.0
    with pytest.raises(RuntimeError, match="TOKEN_HARD_FAILURE"):
        loop._ensure_valid_access_token()


def test_kis_token_error_dict_failure_kinds() -> None:
    loop = UserPaperTradingLoop(
        app_key="k",
        app_secret="s",
        account_no="1234567890",
        product_code="01",
        api_base="https://openapivts.koreainvestment.com:29443",
        strategy_id="swing_relaxed_v2",
        user_tag="u1",
        initial_access_token="x",
    )
    d = loop._kis_token_error_dict(RuntimeError("TOKEN_RECOVERY_WAIT: backoff"))
    assert d["failure_kind"] == "token_recovery_wait"
    d2 = loop._kis_token_error_dict(RuntimeError("TOKEN_HARD_FAILURE: x"))
    assert d2["failure_kind"] == "token_hard_failure"
    assert "paper_token_recovery_mode" in d2


def test_diagnostics_payload_includes_token_streak_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_SESSION_MAX_TOKEN_FAILURES_BEFORE_RISK_OFF", "15")
    get_settings.cache_clear()
    c = PaperSessionController()
    c._token_failure_streak = 2
    c._risk_off_reason = None
    d = c.diagnostics_payload()
    assert d.get("token_failure_streak") == 2
    assert d.get("max_token_failures_before_risk_off") == 15


def test_apply_tick_diagnostics_merges_paper_token_keys() -> None:
    ctl = PaperSessionController()
    ctl._apply_paper_tick_diagnostics(
        {
            "ok": True,
            "token_source": "interval_probe_valid",
            "paper_token_recovery_mode": "interval_probe_valid",
            "paper_consecutive_token_hard_failures": 0,
        },
    )
    assert ctl._paper_diagnostics.get("paper_token_recovery_mode") == "interval_probe_valid"
