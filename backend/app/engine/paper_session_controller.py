"""
앱 Paper Trading 세션: 사용자 KIS 모의 자격으로 백그라운드 루프(전략·리스크·모의 주문).
전역 RuntimeEngine 과 별도 스레드 — live 경로와 혼합하지 않음.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Any

from backend.app.api.broker_routes import get_broker_service
from backend.app.core.config import get_backend_settings
from backend.app.engine.user_paper_loop import UserPaperTradingLoop
from backend.app.portfolio.sync_engine import run_portfolio_sync

logger = logging.getLogger("backend.app.engine.paper_session_controller")


class PaperSessionController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._run_flag = False
        self._thread: threading.Thread | None = None
        self._user_id: str | None = None
        self._strategy_id: str | None = None
        self._status = "stopped"
        self._failure_streak = 0
        self._last_error: str | None = None
        self._last_tick_at: str | None = None
        self._last_report: dict[str, Any] = {}
        self._last_positions: list[dict[str, Any]] = []
        self._logs: list[dict[str, str]] = []
        self._user_loop: UserPaperTradingLoop | None = None
        self._user_loop_identity: tuple[str, ...] | None = None
        self._paper_diagnostics: dict[str, Any] = {}

    def _max_failures(self) -> int:
        return max(1, int(get_backend_settings().runtime_max_consecutive_failures))

    def _interval_sec(self) -> int:
        return max(25, int(get_backend_settings().runtime_loop_interval_sec))

    def _append_log(self, level: str, msg: str) -> None:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "message": msg[:2000]}
        self._logs.insert(0, entry)
        self._logs = self._logs[:100]

    def _apply_paper_tick_diagnostics(self, out: dict[str, Any]) -> None:
        """틱 결과에서 KIS 실패 맥락·토큰 출처를 누적(진단 API용)."""
        ok = bool(out.get("ok"))
        kis_ctx = out.get("kis_context") if isinstance(out.get("kis_context"), dict) else {}
        if ok:
            self._paper_diagnostics = {
                "last_error": None,
                "last_failed_step": None,
                "last_failed_endpoint": None,
                "last_failed_tr_id": None,
                "sanitized_params": None,
                "token_source": out.get("token_source"),
                "failure_kind": None,
            }
            return
        self._paper_diagnostics = {
            "last_error": out.get("error"),
            "last_failed_step": out.get("failed_step"),
            "last_failed_endpoint": kis_ctx.get("path"),
            "last_failed_tr_id": kis_ctx.get("tr_id"),
            "sanitized_params": kis_ctx.get("params"),
            "token_source": out.get("token_source"),
            "failure_kind": out.get("failure_kind"),
        }

    def _loop(self) -> None:
        settings = get_backend_settings()
        while self._run_flag:
            uid = self._user_id
            sid = self._strategy_id
            if self._status == "risk_off":
                end = time.monotonic() + min(5.0, float(self._interval_sec()))
                while self._run_flag and time.monotonic() < end:
                    time.sleep(0.5)
                continue
            if not uid or not sid:
                time.sleep(1.0)
                continue
            try:
                svc = get_broker_service()
                key, secret, acct, prod, mode = svc.get_plain_credentials(uid)
                if mode != "paper":
                    self._append_log("error", "trading_mode≠paper — 세션 중단 (live 혼선 방지)")
                    self._status = "stopped"
                    self._run_flag = False
                    break
                api_base = svc._resolve_kis_api_base(mode)
                if "openapivts" not in (api_base or ""):
                    raise RuntimeError("모의투자 호스트(openapivts)만 허용됩니다.")
                identity = (uid, sid, key, secret, acct, prod, api_base)
                if self._user_loop is None or self._user_loop_identity != identity:
                    cached_token = svc.get_cached_token(
                        user_id=uid,
                        trading_mode=mode,
                        api_base=api_base,
                        app_key=key,
                    )
                    self._user_loop = UserPaperTradingLoop(
                        app_key=key,
                        app_secret=secret,
                        account_no=acct,
                        product_code=prod,
                        api_base=api_base,
                        strategy_id=sid,
                        user_tag=uid[:12].replace("/", "_").replace("\\", "_"),
                        initial_access_token=cached_token,
                    )
                    self._user_loop_identity = identity
                    self._append_log(
                        "info",
                        "Paper 루프 재초기화 (자격/전략 변경 또는 첫 시작)"
                        + (" · test-connection 토큰 재사용" if cached_token else ""),
                    )
                loop = self._user_loop
                out = loop.run_intraday_tick()
                self._last_tick_at = datetime.now(timezone.utc).isoformat()
                self._apply_paper_tick_diagnostics(out)
                if not out.get("ok"):
                    raise RuntimeError(str(out.get("error") or "tick_failed"))
                self._failure_streak = 0
                self._last_error = None
                rep = out.get("report")
                self._last_report = rep if isinstance(rep, dict) else {}
                try:
                    self._last_positions = loop.snapshot_positions()
                except Exception as snap_e:
                    self._append_log("warning", f"positions snapshot: {snap_e}")
                acc_n = self._last_report.get("accepted_orders")
                rej_n = self._last_report.get("rejected_orders")
                self._append_log("info", f"tick ok accepted={acc_n} rejected={rej_n}")
                if self._last_report.get("halted"):
                    self._append_log(
                        "warning",
                        f"cycle halted kill={self._last_report.get('kill_state')} reason={self._last_report.get('reason')}",
                    )
                try:
                    run_portfolio_sync(backfill_days=settings.portfolio_sync_backfill_days, settings=settings)
                except Exception as sync_e:
                    self._append_log("warning", f"portfolio sync: {sync_e}")
            except Exception as exc:
                self._failure_streak += 1
                self._last_error = str(exc)
                logger.exception("paper session tick error (streak=%s)", self._failure_streak)
                self._append_log("error", f"{type(exc).__name__}: {exc}")
                if self._failure_streak >= self._max_failures():
                    self._status = "risk_off"
                    self._append_log("error", "연속 실패 한도 → risk_off (paper-trading/risk-reset 또는 stop 후 재시작)")
            end = time.monotonic() + float(self._interval_sec())
            while self._run_flag and time.monotonic() < end:
                time.sleep(min(1.0, end - time.monotonic()))

    def start(self, user_id: str, strategy_id: str) -> dict[str, Any]:
        svc = get_broker_service()
        try:
            account = svc.get_account(user_id)
        except ValueError as exc:
            raise ValueError("BROKER_NOT_REGISTERED") from exc
        if account.trading_mode != "paper":
            raise ValueError("PAPER_MODE_REQUIRED")
        if account.connection_status != "success":
            raise ValueError("BROKER_NOT_READY")
        api_base = svc._resolve_kis_api_base(account.trading_mode)
        if "openapivts" not in (api_base or ""):
            raise ValueError("MOCK_HOST_REQUIRED")

        with self._lock:
            if self._run_flag and self._thread is not None and self._thread.is_alive():
                if self._user_id == user_id:
                    return {"ok": True, "message": "already_running", "status": self._status}
                raise RuntimeError("OTHER_SESSION_ACTIVE")
            self._user_id = user_id
            self._strategy_id = strategy_id
            self._failure_streak = 0
            self._last_error = None
            self._status = "running"
            self._user_loop = None
            self._user_loop_identity = None
            self._run_flag = True
            self._thread = threading.Thread(target=self._loop, name="paper-user-session", daemon=True)
            self._thread.start()
        self._append_log("info", f"Paper 세션 시작 strategy={strategy_id} (KIS 모의)")
        return {"ok": True, "status": self._status}

    def stop(self, requester_id: str) -> dict[str, Any]:
        if self._user_id and self._user_id != requester_id:
            raise RuntimeError("NOT_OWNER")
        self._run_flag = False
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=12.0)
        with self._lock:
            self._status = "stopped"
            self._user_id = None
            self._strategy_id = None
            self._thread = None
            self._user_loop = None
            self._user_loop_identity = None
        self._append_log("info", "Paper 세션 중지")
        return {"ok": True, "status": "stopped"}

    def risk_reset(self, requester_id: str) -> dict[str, Any]:
        if self._user_id and self._user_id != requester_id:
            raise RuntimeError("NOT_OWNER")
        with self._lock:
            if self._status != "risk_off":
                return {"ok": False, "message": "risk_off 상태가 아닙니다.", "status": self._status}
            self._failure_streak = 0
            self._last_error = None
            self._status = "running"
            if not self._run_flag:
                self._run_flag = True
            if self._thread is None or not self._thread.is_alive():
                if self._user_id and self._strategy_id:
                    self._thread = threading.Thread(target=self._loop, name="paper-user-session", daemon=True)
                    self._thread.start()
        self._append_log("info", "Paper risk_off 해제")
        return {"ok": True, "status": self._status}

    def status_payload(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mode": "paper",
                "status": self._status,
                "strategy_id": self._strategy_id,
                "user_session_active": bool(self._run_flag and self._thread and self._thread.is_alive()),
                "failure_streak": self._failure_streak,
                "max_failures": self._max_failures(),
                "last_error": self._last_error,
                "last_tick_at": self._last_tick_at,
                "last_tick_summary": {
                    "accepted_orders": self._last_report.get("accepted_orders"),
                    "rejected_orders": self._last_report.get("rejected_orders"),
                    "equity": self._last_report.get("equity"),
                    "daily_return_pct": self._last_report.get("daily_return_pct"),
                },
                "diagnostics": dict(self._paper_diagnostics),
            }

    def diagnostics_payload(self) -> dict[str, Any]:
        with self._lock:
            base = dict(self._paper_diagnostics)
            base["session_last_error"] = self._last_error
            base["session_status"] = self._status
            return base

    def get_positions(self) -> list[dict[str, Any]]:
        return list(self._last_positions)

    def get_logs(self) -> list[dict[str, str]]:
        return list(self._logs)

    def pnl_from_last_report(self) -> dict[str, Any]:
        r = self._last_report
        return {
            "today_return_pct": float(r.get("daily_return_pct") or 0.0),
            "cumulative_return_pct": float(r.get("cumulative_return_pct") or 0.0),
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "equity": r.get("equity"),
            "position_count": len(self._last_positions),
            "chart": [],
            "source": "last_tick_report",
        }


_controller_lock = threading.Lock()
_controller: PaperSessionController | None = None


def get_paper_session_controller() -> PaperSessionController:
    global _controller
    with _controller_lock:
        if _controller is None:
            _controller = PaperSessionController()
        return _controller
