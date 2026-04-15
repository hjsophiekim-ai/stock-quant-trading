"""
백그라운드 루프: 시장 구간별 market_loop 호출, 실패 누적 시 risk_off, 상태 영속화.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from backend.app.core.config import BackendSettings, get_backend_settings
from backend.app.engine.market_loop import BackendMarketLoop, MarketLoopResult, get_last_kis_token_failure_diag
from backend.app.engine.scheduler import MarketPhase, classify_market_phase, now_kst

logger = logging.getLogger("backend.app.engine.runtime_engine")


class EngineState(StrEnum):
    IDLE = "idle"
    PREMARKET = "premarket"
    RUNNING = "running"
    RISK_OFF = "risk_off"
    STOPPED = "stopped"
    AFTERHOURS = "afterhours"


@dataclass
class PersistedRuntimeState:
    engine_state: str = EngineState.STOPPED.value
    heartbeat_at: str | None = None
    last_loop_at: str | None = None
    last_loop_ok: bool | None = None
    failure_streak: int = 0
    last_error: str | None = None
    market_phase: str | None = None
    last_afterhours_date: str | None = None
    loop_interval_sec: int = 120
    started_at: str | None = None


class RuntimeEngine:
    def __init__(self, settings: BackendSettings | None = None) -> None:
        self._settings = settings or get_backend_settings()
        self._lock = threading.Lock()
        self._run_flag = False
        self._thread: threading.Thread | None = None
        self._state = EngineState.STOPPED
        self._failure_streak = 0
        self._last_result_summary: dict[str, Any] = {}
        self._last_error: str | None = None
        self._loop_interval = max(10, int(self._settings.runtime_loop_interval_sec))
        self._max_failures = max(1, int(self._settings.runtime_max_consecutive_failures))
        self._state_path = Path(self._settings.runtime_state_path)
        self._error_log_path = Path(self._settings.runtime_error_log_path)
        self._reports_dir = Path(self._settings.runtime_reports_dir)
        self._load_persisted()

    def _load_persisted(self) -> None:
        if not self._state_path.is_file():
            return
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._failure_streak = int(raw.get("failure_streak") or 0)
            if self._settings.runtime_auto_resume and raw.get("engine_state") == EngineState.RUNNING.value:
                logger.warning("runtime_auto_resume: 이전 상태가 running 이었습니다. start API로 다시 시작하세요.")
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("persisted state load skipped: %s", exc)

    def _persist(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        snap = PersistedRuntimeState(
            engine_state=self._state.value,
            heartbeat_at=now_kst().isoformat(),
            last_loop_at=self._last_result_summary.get("last_loop_at"),
            last_loop_ok=self._last_result_summary.get("last_loop_ok"),
            failure_streak=self._failure_streak,
            last_error=self._last_error,
            market_phase=self._last_result_summary.get("market_phase"),
            last_afterhours_date=self._last_result_summary.get("last_afterhours_date"),
            loop_interval_sec=self._loop_interval,
            started_at=self._last_result_summary.get("started_at"),
        )
        try:
            self._state_path.write_text(json.dumps(asdict(snap), ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.error("state persist failed: %s", exc)

    def _append_runtime_log(self, level: str, message: str) -> None:
        self._error_log_path.parent.mkdir(parents=True, exist_ok=True)
        line = f"{now_kst().isoformat()} | {level.upper()} | {message}\n"
        try:
            with self._error_log_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError as exc:
            logger.error("error log write failed: %s", exc)

    def _on_loop_exception(self, exc: BaseException) -> None:
        tb = traceback.format_exc()
        with self._lock:
            self._failure_streak += 1
            self._last_error = str(exc)
            streak = self._failure_streak
        logger.exception("runtime loop error (streak=%s)", streak)
        self._append_runtime_log("error", f"{type(exc).__name__}: {exc}\n{tb}")
        if streak >= self._max_failures:
            with self._lock:
                self._state = EngineState.RISK_OFF
            logger.critical(
                "failure_streak=%s >= max=%s → RISK_OFF",
                streak,
                self._max_failures,
            )
            self._append_runtime_log("critical", "STATE -> risk_off (max failures exceeded)")

    def _reset_failures_on_success(self) -> None:
        with self._lock:
            self._failure_streak = 0
            self._last_error = None

    def _loop_body(self, loop: BackendMarketLoop) -> None:
        with self._lock:
            if self._state == EngineState.STOPPED:
                return
        mphase = classify_market_phase()
        self._last_result_summary["market_phase"] = mphase.value
        self._last_result_summary["last_loop_at"] = now_kst().isoformat()

        with self._lock:
            risk_halt = self._state == EngineState.RISK_OFF
        if risk_halt:
            return

        if mphase == MarketPhase.CLOSED:
            with self._lock:
                if self._state not in (EngineState.STOPPED, EngineState.RISK_OFF):
                    self._state = EngineState.IDLE
            self._last_result_summary["note"] = "market_closed"
            self._last_result_summary["last_loop_ok"] = True
            return

        if mphase == MarketPhase.PREMARKET:
            with self._lock:
                self._state = EngineState.PREMARKET
            res = loop.run_premarket()
            self._apply_result(res)

        elif mphase == MarketPhase.SESSION:
            with self._lock:
                self._state = EngineState.RUNNING
            res = loop.run_intraday_tick()
            self._apply_result(res)

        elif mphase == MarketPhase.AFTERHOURS:
            with self._lock:
                self._state = EngineState.AFTERHOURS
            today = now_kst().date().isoformat()
            last_eod = self._last_result_summary.get("last_afterhours_date")
            if last_eod != today:
                res = loop.run_afterhours(self._reports_dir)
                self._apply_result(res)
                if res.ok:
                    self._last_result_summary["last_afterhours_date"] = today
            else:
                self._last_result_summary["last_loop_ok"] = True
                self._last_result_summary["note"] = "afterhours_already_done"

    def _apply_result(self, res: MarketLoopResult) -> None:
        self._last_result_summary["last_phase_ran"] = res.phase
        if res.ok:
            self._reset_failures_on_success()
            self._last_result_summary["last_loop_ok"] = True
            self._last_result_summary["last_summary"] = res.summary
            self._append_runtime_log("info", f"loop ok phase={res.phase}")
            return

        self._last_result_summary["last_loop_ok"] = False
        err = res.error or "unknown_error"
        with self._lock:
            self._failure_streak += 1
            self._last_error = err
        self._append_runtime_log("error", f"phase={res.phase} error={err}")
        if self._failure_streak >= self._max_failures:
            with self._lock:
                self._state = EngineState.RISK_OFF
            self._append_runtime_log("critical", "STATE -> risk_off (max consecutive failures)")

    def _main_loop(self) -> None:
        loop = BackendMarketLoop(self._settings)
        while self._run_flag:
            try:
                if self._state == EngineState.STOPPED:
                    time.sleep(min(self._loop_interval, 5))
                    continue
                self._loop_body(loop)
            except Exception as exc:
                self._on_loop_exception(exc)

            self._persist()
            end = time.monotonic() + self._loop_interval
            while self._run_flag and time.monotonic() < end:
                time.sleep(min(1.0, end - time.monotonic()))

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._state == EngineState.RISK_OFF:
                return {"ok": False, "message": "risk_off 상태입니다. /risk-reset 후 다시 시작하세요."}
            if self._run_flag and self._thread is not None and self._thread.is_alive():
                return {"ok": True, "message": "already_running", "state": self._state.value}
            self._run_flag = True
            if self._thread is None or not self._thread.is_alive():
                self._last_result_summary["started_at"] = now_kst().isoformat()
                self._thread = threading.Thread(target=self._main_loop, name="runtime-engine", daemon=True)
                self._thread.start()
            m = classify_market_phase()
            if m == MarketPhase.CLOSED:
                self._state = EngineState.IDLE
            elif m == MarketPhase.PREMARKET:
                self._state = EngineState.PREMARKET
            elif m == MarketPhase.SESSION:
                self._state = EngineState.RUNNING
            else:
                self._state = EngineState.AFTERHOURS
        self._append_runtime_log("info", f"engine start requested state={self._state.value}")
        self._persist()
        return {"ok": True, "state": self._state.value, "interval_sec": self._loop_interval}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._run_flag = False
            self._state = EngineState.STOPPED
        self._append_runtime_log("warning", "engine stopped by api")
        self._persist()
        return {"ok": True, "state": EngineState.STOPPED.value}

    def risk_reset(self) -> dict[str, Any]:
        """risk_off / 실패 카운터 수동 해제 (운영자 확인 후)."""
        with self._lock:
            self._failure_streak = 0
            self._last_error = None
            if self._state == EngineState.RISK_OFF:
                self._state = EngineState.IDLE if self._run_flag else EngineState.STOPPED
        self._append_runtime_log("warning", "risk_reset invoked")
        self._persist()
        return {"ok": True, "state": self._state.value, "failure_streak": 0}

    def force_risk_off(self) -> dict[str, Any]:
        with self._lock:
            self._state = EngineState.RISK_OFF
        self._append_runtime_log("critical", "STATE -> risk_off (manual)")
        self._persist()
        return {"ok": True, "state": EngineState.RISK_OFF.value}

    def status(self) -> dict[str, Any]:
        with self._lock:
            st = self._state.value
            running = self._run_flag and (self._thread is not None and self._thread.is_alive())
        snap_path = str(self._state_path)
        disk: dict[str, Any] = {}
        if self._state_path.is_file():
            try:
                disk = json.loads(self._state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        return {
            "engine_state": st,
            "loop_thread_alive": running,
            "failure_streak": self._failure_streak,
            "max_failures": self._max_failures,
            "loop_interval_sec": self._loop_interval,
            "last_error": self._last_error,
            "market_phase_now": classify_market_phase().value,
            "persisted_file": snap_path,
            "persisted": disk,
            "volatile_summary": dict(self._last_result_summary),
            "last_kis_token_failure": get_last_kis_token_failure_diag(),
        }


_engine_lock = threading.Lock()
_engine: RuntimeEngine | None = None


def get_runtime_engine() -> RuntimeEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = RuntimeEngine()
        return _engine
