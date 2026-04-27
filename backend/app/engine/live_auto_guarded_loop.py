from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from backend.app.api.live_trading_routes import runtime_safety_validation_for_user_id
from backend.app.core.config import BackendSettings
from backend.app.engine.live_auto_guarded_engine import tick_live_auto_guarded
from backend.app.risk.audit import append_risk_event
from backend.app.services.broker_secret_service import BrokerSecretService
from backend.app.services.live_auto_guarded_store import LiveAutoGuardedStore

logger = logging.getLogger("backend.app.engine.live_auto_guarded_loop")

_install_lock = threading.Lock()
_installed = False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class LiveAutoLoopRuntime:
    user_id: str
    running: bool = False
    started_at_utc: str | None = None
    stopped_at_utc: str | None = None
    last_tick_at_utc: str | None = None
    consecutive_failures: int = 0
    last_error: str | None = None


@dataclass
class _LoopHandle:
    thread: threading.Thread
    stop_event: threading.Event
    runtime: LiveAutoLoopRuntime


_registry_lock = threading.Lock()
_registry: dict[str, _LoopHandle] = {}


def _event(cfg: BackendSettings, event_type: str, payload: dict[str, Any]) -> None:
    append_risk_event(
        cfg.risk_events_jsonl,
        {
            "ts_utc": _utc_now_iso(),
            "event_type": event_type,
            **payload,
        },
    )


def get_live_auto_guarded_loop_status(user_id: str) -> dict[str, Any]:
    uid = str(user_id or "")
    with _registry_lock:
        h = _registry.get(uid)
        if h is None:
            return {"running": False}
        return asdict(h.runtime)


def start_live_auto_guarded_loop(
    *,
    cfg: BackendSettings,
    broker_service: BrokerSecretService,
    store: LiveAutoGuardedStore,
    user_id: str,
    tick_func: Callable[..., dict[str, Any]] = tick_live_auto_guarded,
    safety_func: Callable[[BackendSettings, str], dict[str, Any]] = runtime_safety_validation_for_user_id,
) -> dict[str, Any]:
    uid = str(user_id or "")
    if not uid:
        return {"ok": False, "error": "empty_user_id"}
    if not bool(getattr(cfg, "live_auto_loop_enabled", False)):
        return {"ok": True, "skipped": True, "reason": "LIVE_AUTO_LOOP_ENABLED is false"}

    with _registry_lock:
        existing = _registry.get(uid)
        if existing is not None and existing.runtime.running:
            _event(cfg, "LIVE_AUTO_LOOP_ALREADY_RUNNING", {"user_id": uid})
            return {"ok": True, "already_running": True, "loop": asdict(existing.runtime)}

        stop_event = threading.Event()
        runtime = LiveAutoLoopRuntime(user_id=uid, running=True, started_at_utc=_utc_now_iso())

        def _runner():
            max_fail = int(getattr(cfg, "live_auto_loop_max_consecutive_failures", 5))
            interval = float(getattr(cfg, "live_auto_loop_interval_sec", 60))
            while not stop_event.is_set():
                st = store.get(uid)
                if not bool(st.enabled):
                    runtime.running = False
                    runtime.stopped_at_utc = _utc_now_iso()
                    _event(cfg, "LIVE_AUTO_LOOP_STOPPED", {"user_id": uid, "reason": "state_disabled"})
                    break
                if (cfg.execution_mode or "").strip().lower() != "live_auto_guarded":
                    runtime.running = False
                    runtime.stopped_at_utc = _utc_now_iso()
                    _event(cfg, "LIVE_AUTO_LOOP_STOPPED", {"user_id": uid, "reason": "wrong_execution_mode"})
                    break
                try:
                    runtime.last_tick_at_utc = _utc_now_iso()
                    safety = safety_func(cfg, uid)
                    out = tick_func(cfg=cfg, broker_service=broker_service, user_id=uid, safety=safety)
                    if not bool(out.get("ok")) and not bool(out.get("skipped")):
                        runtime.consecutive_failures += 1
                        runtime.last_error = str(out.get("error") or "tick_failed")
                        _event(
                            cfg,
                            "LIVE_AUTO_LOOP_TICK_FAILED",
                            {"user_id": uid, "error": runtime.last_error, "consecutive_failures": runtime.consecutive_failures},
                        )
                    else:
                        runtime.consecutive_failures = 0
                        runtime.last_error = None
                    if runtime.consecutive_failures >= max_fail:
                        runtime.running = False
                        runtime.stopped_at_utc = _utc_now_iso()
                        _event(
                            cfg,
                            "LIVE_AUTO_LOOP_DISABLED_AFTER_FAILURES",
                            {"user_id": uid, "consecutive_failures": runtime.consecutive_failures, "max_failures": max_fail},
                        )
                        break
                except Exception as exc:
                    runtime.consecutive_failures += 1
                    runtime.last_error = str(exc)
                    _event(
                        cfg,
                        "LIVE_AUTO_LOOP_TICK_FAILED",
                        {"user_id": uid, "error": runtime.last_error, "consecutive_failures": runtime.consecutive_failures},
                    )
                    if runtime.consecutive_failures >= max_fail:
                        runtime.running = False
                        runtime.stopped_at_utc = _utc_now_iso()
                        _event(
                            cfg,
                            "LIVE_AUTO_LOOP_DISABLED_AFTER_FAILURES",
                            {"user_id": uid, "consecutive_failures": runtime.consecutive_failures, "max_failures": max_fail},
                        )
                        break
                stop_event.wait(interval)

            runtime.running = False

        th = threading.Thread(target=_runner, name=f"live-auto-guarded-loop:{uid[:8]}", daemon=True)
        _registry[uid] = _LoopHandle(thread=th, stop_event=stop_event, runtime=runtime)
        _event(cfg, "LIVE_AUTO_LOOP_STARTED", {"user_id": uid, "interval_sec": float(getattr(cfg, "live_auto_loop_interval_sec", 60))})
        th.start()
        return {"ok": True, "started": True, "loop": asdict(runtime)}


def stop_live_auto_guarded_loop(*, cfg: BackendSettings, user_id: str, reason: str = "stop_requested") -> dict[str, Any]:
    uid = str(user_id or "")
    h = None
    with _registry_lock:
        h = _registry.get(uid)
        if h is None:
            return {"ok": True, "stopped": False, "reason": "not_running"}
        h.stop_event.set()
        h.runtime.running = False
        h.runtime.stopped_at_utc = _utc_now_iso()
    if h is not None:
        try:
            h.thread.join(timeout=2.0)
        except Exception:
            pass
        _event(cfg, "LIVE_AUTO_LOOP_STOPPED", {"user_id": uid, "reason": reason})
        return {"ok": True, "stopped": True, "loop": asdict(h.runtime)}
    return {"ok": True, "stopped": False, "reason": "not_running"}


def install_live_auto_guarded_loop_manager(
    settings: BackendSettings,
    broker_service: BrokerSecretService,
) -> None:
    global _installed
    if (settings.trading_mode or "").strip().lower() != "live":
        return
    with _install_lock:
        if _installed:
            return
        _installed = True

    if not bool(getattr(settings, "live_auto_loop_enabled", False)):
        return
    if not bool(getattr(settings, "live_auto_loop_auto_resume", False)):
        return

    store = LiveAutoGuardedStore(settings.live_auto_guarded_state_store_json)
    for st in store.list_enabled()[:20]:
        start_live_auto_guarded_loop(cfg=settings, broker_service=broker_service, store=store, user_id=str(st.user_id or ""))

