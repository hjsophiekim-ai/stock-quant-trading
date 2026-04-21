from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import get_settings
from backend.app.engine import paper_session_controller as psc_mod


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


def test_paper_sessions_are_isolated_by_market(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_SESSION_STATE_PATH", str(tmp_path / "paper_state.json"))
    get_settings.cache_clear()
    monkeypatch.setattr(psc_mod, "get_broker_service", _svc_ok)
    monkeypatch.setattr(psc_mod.threading, "Thread", _DummyThread)

    hub = psc_mod.PaperSessionHub()

    s_us = hub.start("u1", "us_swing_relaxed_v1", market="us")
    assert s_us["ok"] is True
    assert hub.status_payload(market="us")["paper_market"] == "us"
    assert hub.status_payload(market="us")["strategy_id"] == "us_swing_relaxed_v1"

    s_kr = hub.start("u1", "swing_relaxed_v2", market="domestic")
    assert s_kr["ok"] is True
    assert hub.status_payload(market="domestic")["paper_market"] == "domestic"
    assert hub.status_payload(market="domestic")["strategy_id"] == "swing_relaxed_v2"

    assert hub.status_payload(market="us")["paper_market"] == "us"
    assert hub.status_payload(market="us")["strategy_id"] == "us_swing_relaxed_v1"

    hub.stop("u1", market="domestic")
    assert hub.status_payload(market="domestic")["status"] == "stopped"
    assert hub.status_payload(market="us")["status"] == "running"


def test_paper_logs_are_market_scoped(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_SESSION_STATE_PATH", str(tmp_path / "paper_state_logs.json"))
    get_settings.cache_clear()
    monkeypatch.setattr(psc_mod, "get_broker_service", _svc_ok)
    monkeypatch.setattr(psc_mod.threading, "Thread", _DummyThread)

    hub = psc_mod.PaperSessionHub()
    hub.start("u1", "us_swing_relaxed_v1", market="us")
    hub.start("u1", "swing_relaxed_v2", market="domestic")

    us_logs = hub.logs_payload(market="us")["items"]
    dom_logs = hub.logs_payload(market="domestic")["items"]

    assert any(x.get("paper_market") == "us" for x in us_logs)
    assert any(x.get("paper_market") == "domestic" for x in dom_logs)

