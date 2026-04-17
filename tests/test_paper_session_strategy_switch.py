from __future__ import annotations

from types import SimpleNamespace

from backend.app.engine import paper_session_controller as mod


class _DummyThread:
    def __init__(self, target=None, name=None, daemon=None):
        self._alive = False

    def start(self) -> None:
        self._alive = True

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout=None) -> None:
        self._alive = False


class _AlwaysAliveThread:
    def __init__(self):
        self._alive = True

    def is_alive(self) -> bool:
        return True

    def join(self, timeout=None) -> None:
        self._alive = False


def _stub_broker_service() -> SimpleNamespace:
    return SimpleNamespace(
        get_account=lambda _u: SimpleNamespace(trading_mode="paper", connection_status="success"),
        _resolve_kis_api_base=lambda _m: "https://openapivts.koreainvestment.com:29443",
        ensure_cached_token_for_paper_start=lambda _u: SimpleNamespace(
            ok=True,
            token_cache_hit=True,
            token_cache_source="unit-test",
            token_cache_persisted=True,
            cache_miss_reason=None,
            message=None,
            token_error_code=None,
            failure_code=None,
        ),
    )


def test_start_switches_strategy_when_same_user_running(monkeypatch) -> None:
    monkeypatch.setattr(mod, "get_broker_service", lambda: _stub_broker_service())
    monkeypatch.setattr(mod, "paper_final_betting_enabled_fresh", lambda: False)
    monkeypatch.setattr(mod, "paper_final_betting_diagnostics", lambda: {"settings_cache_mismatch": False})
    monkeypatch.setattr(mod.threading, "Thread", _DummyThread)

    c = mod.PaperSessionController()
    monkeypatch.setattr(c, "_save_desired_state", lambda: None)
    monkeypatch.setattr(c, "_append_log", lambda *_a, **_k: None)
    monkeypatch.setattr(c, "_clear_desired_state", lambda: None)
    c._run_flag = True
    c._thread = _AlwaysAliveThread()
    c._user_id = "u1"
    c._status = "running"
    c._strategy_id = "final_betting_v1"
    c._paper_market = "domestic"

    out = c.start("u1", "scalp_momentum_v3", market="domestic")
    assert out["ok"] is True
    assert c._strategy_id == "scalp_momentum_v3"
    assert c._paper_market == "domestic"


def test_start_returns_already_running_when_same_strategy(monkeypatch) -> None:
    monkeypatch.setattr(mod, "get_broker_service", lambda: _stub_broker_service())
    monkeypatch.setattr(mod, "paper_final_betting_enabled_fresh", lambda: False)
    monkeypatch.setattr(mod, "paper_final_betting_diagnostics", lambda: {"settings_cache_mismatch": False})

    c = mod.PaperSessionController()
    c._run_flag = True
    c._thread = _AlwaysAliveThread()
    c._user_id = "u1"
    c._status = "running"
    c._strategy_id = "scalp_momentum_v3"
    c._paper_market = "domestic"
    out = c.start("u1", "scalp_momentum_v3", market="domestic")
    assert out["message"] == "already_running"
