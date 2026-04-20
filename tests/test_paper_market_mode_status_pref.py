from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from backend.app.engine import paper_session_controller as psc_mod
from backend.app.main import app


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


def test_status_payload_pref_user_survives_session_stop(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_SESSION_STATE_PATH", str(tmp_path / "paper_state.json"))
    get_settings.cache_clear()
    monkeypatch.setattr(psc_mod, "get_broker_service", _svc_ok)
    monkeypatch.setattr(psc_mod.threading, "Thread", _DummyThread)

    ctrl = psc_mod.PaperSessionController()
    ctrl.set_paper_market_mode("u-pref", "defensive")
    assert ctrl.status_payload(pref_user_id="u-pref")["manual_market_mode_override"] == "defensive"
    assert ctrl.status_payload()["manual_market_mode_override"] == "auto"

    st = ctrl.start("u-pref", "swing_v1")
    assert st["ok"] is True
    assert ctrl.status_payload()["manual_market_mode_override"] == "defensive"

    ctrl.stop("u-pref")
    assert ctrl.status_payload()["manual_market_mode_override"] == "auto"
    assert ctrl.status_payload(pref_user_id="u-pref")["manual_market_mode_override"] == "defensive"


def test_get_paper_diagnostics_and_engine_status_optional_auth(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_SESSION_STATE_PATH", str(tmp_path / "paper_state_diag.json"))
    get_settings.cache_clear()
    monkeypatch.setattr(psc_mod, "get_broker_service", _svc_ok)
    monkeypatch.setattr(psc_mod.threading, "Thread", _DummyThread)

    monkeypatch.setattr(
        "backend.app.api.paper_trading_routes.get_current_user_from_auth_header",
        lambda _h: SimpleNamespace(id="diag-user"),
    )
    ctrl = psc_mod.PaperSessionController()
    ctrl.set_paper_market_mode("diag-user", "neutral")
    monkeypatch.setattr("backend.app.api.paper_trading_routes.get_paper_session_controller", lambda: ctrl)

    c = TestClient(app)
    d = c.get("/api/paper-trading/diagnostics", headers={"Authorization": "Bearer t"})
    assert d.status_code == 200
    assert d.json().get("manual_market_mode_override") == "neutral"
    e = c.get("/api/paper-trading/engine/status", headers={"Authorization": "Bearer t"})
    assert e.status_code == 200
    assert e.json().get("manual_market_mode_override") == "neutral"


def test_get_paper_status_optional_auth_returns_saved_manual(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPER_SESSION_STATE_PATH", str(tmp_path / "paper_state_x.json"))
    get_settings.cache_clear()
    monkeypatch.setattr(psc_mod, "get_broker_service", _svc_ok)
    monkeypatch.setattr(psc_mod.threading, "Thread", _DummyThread)

    monkeypatch.setattr(
        "backend.app.api.paper_trading_routes.get_current_user_from_auth_header",
        lambda _h: SimpleNamespace(id="api-pref-user"),
    )
    ctrl = psc_mod.PaperSessionController()
    ctrl.set_paper_market_mode("api-pref-user", "aggressive")
    monkeypatch.setattr("backend.app.api.paper_trading_routes.get_paper_session_controller", lambda: ctrl)

    c = TestClient(app)
    r = c.get("/api/paper-trading/status", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    assert r.json().get("manual_market_mode_override") == "aggressive"
