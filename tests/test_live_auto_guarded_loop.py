from __future__ import annotations

import time
from types import SimpleNamespace

from backend.app.core.config import BackendSettings
from backend.app.engine.live_auto_guarded_loop import (
    get_live_auto_guarded_loop_status,
    start_live_auto_guarded_loop,
    stop_live_auto_guarded_loop,
)
from backend.app.services.live_auto_guarded_store import LiveAutoGuardedState, LiveAutoGuardedStore


def _cfg(tmp_path, **kw) -> BackendSettings:
    base = dict(
        trading_mode="live",
        execution_mode="live_auto_guarded",
        risk_events_jsonl=str(tmp_path / "events.jsonl"),
        live_auto_guarded_state_store_json=str(tmp_path / "auto.json"),
        live_auto_loop_enabled=True,
        live_auto_loop_interval_sec=3,
        live_auto_loop_max_consecutive_failures=2,
        live_auto_loop_auto_resume=False,
    )
    base.update(kw)
    return BackendSettings(**base)


def test_loop_start_sets_running(monkeypatch, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    cfg.live_auto_loop_interval_sec = 0
    store = LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json)
    store.upsert(LiveAutoGuardedState(user_id="u1", enabled=True))

    calls = {"n": 0}

    def tick_func(**_kw):
        calls["n"] += 1
        return {"ok": True}

    out = start_live_auto_guarded_loop(cfg=cfg, broker_service=object(), store=store, user_id="u1", tick_func=tick_func, safety_func=lambda *_a: {"ok": True})
    assert out.get("ok") is True
    st = get_live_auto_guarded_loop_status("u1")
    assert st.get("running") is True
    stop_live_auto_guarded_loop(cfg=cfg, user_id="u1")


def test_loop_double_start_does_not_duplicate(monkeypatch, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    cfg.live_auto_loop_interval_sec = 0
    store = LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json)
    store.upsert(LiveAutoGuardedState(user_id="u1", enabled=True))

    calls = {"n": 0}

    def tick_func(**_kw):
        calls["n"] += 1
        return {"ok": True}

    out1 = start_live_auto_guarded_loop(cfg=cfg, broker_service=object(), store=store, user_id="u1", tick_func=tick_func, safety_func=lambda *_a: {"ok": True})
    out2 = start_live_auto_guarded_loop(cfg=cfg, broker_service=object(), store=store, user_id="u1", tick_func=tick_func, safety_func=lambda *_a: {"ok": True})
    assert out1.get("ok") is True
    assert out2.get("already_running") is True
    stop_live_auto_guarded_loop(cfg=cfg, user_id="u1")


def test_loop_stop_transitions_to_stopped(monkeypatch, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    cfg.live_auto_loop_interval_sec = 0
    store = LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json)
    store.upsert(LiveAutoGuardedState(user_id="u1", enabled=True))

    def tick_func(**_kw):
        return {"ok": True}

    start_live_auto_guarded_loop(cfg=cfg, broker_service=object(), store=store, user_id="u1", tick_func=tick_func, safety_func=lambda *_a: {"ok": True})
    stop_live_auto_guarded_loop(cfg=cfg, user_id="u1")
    st = get_live_auto_guarded_loop_status("u1")
    assert st.get("running") is False


def test_loop_disables_after_consecutive_failures(monkeypatch, tmp_path) -> None:
    cfg = _cfg(tmp_path, live_auto_loop_max_consecutive_failures=2)
    cfg.live_auto_loop_interval_sec = 0
    store = LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json)
    store.upsert(LiveAutoGuardedState(user_id="u1", enabled=True))

    def tick_func(**_kw):
        raise RuntimeError("boom")

    start_live_auto_guarded_loop(cfg=cfg, broker_service=object(), store=store, user_id="u1", tick_func=tick_func, safety_func=lambda *_a: {"ok": True})
    time.sleep(0.05)
    st = get_live_auto_guarded_loop_status("u1")
    assert st.get("running") is False
    assert int(st.get("consecutive_failures") or 0) >= 2


def test_loop_does_not_start_when_disabled(monkeypatch, tmp_path) -> None:
    cfg = _cfg(tmp_path, live_auto_loop_enabled=False)
    store = LiveAutoGuardedStore(cfg.live_auto_guarded_state_store_json)
    store.upsert(LiveAutoGuardedState(user_id="u1", enabled=True))
    out = start_live_auto_guarded_loop(cfg=cfg, broker_service=object(), store=store, user_id="u1", tick_func=lambda **_k: {"ok": True}, safety_func=lambda *_a: {"ok": True})
    assert out.get("skipped") is True
    st = get_live_auto_guarded_loop_status("u1")
    assert st.get("running") is False

