"""
앱 Paper Trading 세션: 사용자 KIS 모의 자격으로 백그라운드 루프(전략·리스크·모의 주문).
전역 RuntimeEngine 과 별도 스레드 — live 경로와 혼합하지 않음.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.api.broker_routes import get_broker_service
from backend.app.core.config import get_backend_settings
from backend.app.engine.user_paper_loop import UserPaperTradingLoop
from app.config import get_settings as app_get_settings, paper_final_betting_diagnostics, paper_final_betting_enabled_fresh
from backend.app.portfolio.sync_engine import run_portfolio_sync

logger = logging.getLogger("backend.app.engine.paper_session_controller")


def normalize_paper_market_param(market: str | None) -> str:
    mk = (market or "domestic").strip().lower()
    if mk in ("us", "usa", "nyse", "nasdaq", "us_equity", "us_equities"):
        return "us"
    return "domestic"


def paper_positions_refresh_due(now_mono: float, last_at: float, interval_sec: float) -> bool:
    """interval_sec<=0 이면 매 틱 스냅샷(호출 많음)."""
    if interval_sec <= 0.0:
        return True
    return last_at == 0.0 or (now_mono - last_at) >= interval_sec


def paper_portfolio_sync_due(now_mono: float, last_at: float, interval_sec: float) -> bool:
    """interval_sec<=0 이면 sync 비활성."""
    if interval_sec <= 0.0:
        return False
    return last_at == 0.0 or (now_mono - last_at) >= interval_sec


class PaperSessionController:
    def __init__(self) -> None:
        # get_dashboard_payload 가 _lock 보유 중 status_payload() 를 호출하므로 재진입 허용(RLock).
        self._lock = threading.RLock()
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
        self._last_start_diagnostics: dict[str, Any] = {}
        self._last_positions_refresh_at: float = 0.0
        self._last_paper_portfolio_sync_at: float = 0.0
        self._paper_token_ensure_meta: dict[str, Any] = {}
        self._last_paper_initial_token_source: str | None = None
        self._started_at_utc: str | None = None
        self._desired_running: bool = False
        self._paper_market: str = "domestic"
        self._manual_override_enabled: bool = False
        self._resume_info: dict[str, Any] = {
            "enabled": True,
            "restored_from_state": False,
            "last_resume_attempt_utc": None,
            "last_resume_error": None,
        }
        acfg = app_get_settings()
        self._resume_info["enabled"] = bool(getattr(acfg, "paper_session_auto_resume", True))
        self._state_path = Path(acfg.paper_session_state_path).expanduser().resolve()
        self._load_desired_state()
        self._try_auto_resume()

    def _max_failures(self) -> int:
        return max(1, int(get_backend_settings().runtime_max_consecutive_failures))

    def _interval_sec(self) -> int:
        # Paper 세션 틱 간격: 인트라데이(scalp)는 PAPER_INTRADAY_LOOP_INTERVAL_SEC, 그 외 PAPER_TRADING_INTERVAL_SEC.
        acfg = app_get_settings()
        sid = (self._strategy_id or "").lower().strip()
        pm = (self._paper_market or "domestic").strip().lower()
        if pm in ("us", "usa") and sid == "us_scalp_momentum_v1":
            return max(25, int(acfg.paper_intraday_loop_interval_sec))
        if pm in ("us", "usa") and sid == "us_swing_relaxed_v1":
            return max(45, int(acfg.paper_trading_interval_sec))
        if sid == "final_betting_v1" and bool(paper_final_betting_enabled_fresh()):
            return max(25, int(acfg.paper_final_betting_loop_interval_sec))
        if bool(acfg.paper_intraday_enabled) and sid in ("scalp_momentum_v1", "scalp_momentum_v2", "scalp_momentum_v3"):
            return max(20, int(acfg.paper_intraday_loop_interval_sec))
        return max(25, int(acfg.paper_trading_interval_sec))

    def _append_log(self, level: str, msg: str) -> None:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "level": level, "message": msg[:2000]}
        self._logs.insert(0, entry)
        self._logs = self._logs[:100]

    def _state_snapshot(self) -> dict[str, Any]:
        return {
            "desired_running": self._desired_running,
            "status": self._status,
            "user_id": self._user_id,
            "strategy_id": self._strategy_id,
            "paper_market": self._paper_market,
            "started_at_utc": self._started_at_utc,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    def _save_desired_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps(self._state_snapshot(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("paper desired state save skipped: %s", exc)

    def _clear_desired_state(self) -> None:
        try:
            self._state_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("paper desired state clear skipped: %s", exc)

    def _load_desired_state(self) -> None:
        if not self._state_path.is_file():
            return
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            self._desired_running = bool(raw.get("desired_running"))
            self._user_id = str(raw.get("user_id") or "").strip() or None
            self._strategy_id = str(raw.get("strategy_id") or "").strip() or None
            self._paper_market = str(raw.get("paper_market") or "domestic").strip().lower() or "domestic"
            self._started_at_utc = str(raw.get("started_at_utc") or "").strip() or None
            if self._desired_running and self._user_id and self._strategy_id:
                self._resume_info["restored_from_state"] = True
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("paper desired state load skipped: %s", exc)

    def _try_auto_resume(self) -> None:
        if not bool(self._resume_info.get("enabled")):
            return
        if not (self._desired_running and self._user_id and self._strategy_id):
            return
        self._resume_info["last_resume_attempt_utc"] = datetime.now(timezone.utc).isoformat()
        try:
            svc = get_broker_service()
            acc = svc.get_account(self._user_id)
            if acc.trading_mode != "paper":
                raise RuntimeError("PAPER_MODE_REQUIRED")
            if acc.connection_status != "success":
                raise RuntimeError("BROKER_NOT_READY")
            self._run_flag = True
            self._status = "running"
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="paper-user-session", daemon=True)
                self._thread.start()
            self._append_log("info", f"Paper desired state auto-resume strategy={self._strategy_id}")
            self._resume_info["last_resume_error"] = None
        except Exception as exc:
            self._status = "stopped"
            self._run_flag = False
            self._resume_info["last_resume_error"] = str(exc)
            self._append_log("warning", f"Paper auto-resume skipped: {exc}")

    def _apply_paper_tick_diagnostics(self, out: dict[str, Any]) -> None:
        """틱 결과에서 KIS 실패 맥락·토큰 출처·호출 예산(캐시 히트 등)을 누적(진단 API용)."""
        ok = bool(out.get("ok"))
        kis_ctx = out.get("kis_context") if isinstance(out.get("kis_context"), dict) else {}
        budget_base = {
            "universe_cache_hit": out.get("universe_cache_hit"),
            "kospi_cache_hit": out.get("kospi_cache_hit"),
            "request_budget_mode": out.get("request_budget_mode"),
            "throttled_mode": out.get("throttled_mode"),
            "paper_tick_interval_sec": out.get("paper_tick_interval_sec"),
            "positions_refresh_skipped": None,
            "portfolio_sync_skipped": None,
            "token_cache_source": out.get("token_cache_source"),
            "token_error_code": out.get("token_error_code"),
            "fresh_issue": out.get("paper_loop_fresh_issue"),
            "last_kis_token_failure_at_utc": out.get("paper_loop_last_token_failure_at"),
            "last_kis_token_error_code": out.get("paper_loop_last_token_error_code"),
            "last_kis_token_http_status": out.get("paper_loop_last_token_http_status"),
        }
        if ok:
            self._paper_diagnostics = {
                "last_error": None,
                "last_failed_step": None,
                "last_failed_endpoint": None,
                "last_failed_tr_id": None,
                "sanitized_params": None,
                "token_source": out.get("token_source"),
                "failure_kind": None,
                "rate_limit": None,
                "retry_after_sec": None,
                "http_status": None,
                **budget_base,
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
            "rate_limit": kis_ctx.get("rate_limit"),
            "retry_after_sec": kis_ctx.get("retry_after_sec"),
            "http_status": kis_ctx.get("http_status"),
            **budget_base,
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
                    self._desired_running = False
                    self._save_desired_state()
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
                        initial_token_source_label=self._last_paper_initial_token_source,
                        paper_market=self._paper_market,
                        manual_override_enabled=self._manual_override_enabled,
                    )
                    self._user_loop_identity = identity
                    self._append_log(
                        "info",
                        "Paper 루프 재초기화 (자격/전략 변경 또는 첫 시작)"
                        + (" · test-connection 토큰 재사용" if cached_token else ""),
                    )
                else:
                    self._user_loop.set_manual_override(self._manual_override_enabled)
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
                acfg = app_get_settings()
                now_mono = time.monotonic()
                pos_iv = float(acfg.paper_positions_refresh_interval_sec)
                pos_due = paper_positions_refresh_due(now_mono, self._last_positions_refresh_at, pos_iv)
                if pos_due:
                    self._paper_diagnostics["positions_refresh_skipped"] = False
                    try:
                        self._last_positions = loop.snapshot_positions()
                        self._last_positions_refresh_at = now_mono
                    except Exception as snap_e:
                        self._append_log("warning", f"positions snapshot: {snap_e}")
                else:
                    self._paper_diagnostics["positions_refresh_skipped"] = True
                acc_n = self._last_report.get("accepted_orders")
                rej_n = self._last_report.get("rejected_orders")
                self._append_log("info", f"tick ok accepted={acc_n} rejected={rej_n}")
                if self._last_report.get("halted"):
                    self._append_log(
                        "warning",
                        f"cycle halted kill={self._last_report.get('kill_state')} reason={self._last_report.get('reason')}",
                    )
                sync_iv = float(acfg.paper_portfolio_sync_interval_sec)
                sync_due = paper_portfolio_sync_due(now_mono, self._last_paper_portfolio_sync_at, sync_iv)
                if (self._paper_market or "").lower() in ("us", "usa"):
                    self._paper_diagnostics["portfolio_sync_skipped"] = True
                elif sync_due:
                    self._paper_diagnostics["portfolio_sync_skipped"] = False
                    try:
                        run_portfolio_sync(backfill_days=settings.portfolio_sync_backfill_days, settings=settings)
                        self._last_paper_portfolio_sync_at = time.monotonic()
                    except Exception as sync_e:
                        self._append_log("warning", f"portfolio sync: {sync_e}")
                else:
                    self._paper_diagnostics["portfolio_sync_skipped"] = True
            except Exception as exc:
                self._failure_streak += 1
                self._last_error = str(exc)
                logger.exception("paper session tick error (streak=%s)", self._failure_streak)
                self._append_log("error", f"{type(exc).__name__}: {exc}")
                if self._failure_streak >= self._max_failures():
                    if self._manual_override_enabled:
                        self._append_log("warning", "연속 실패 한도 도달했지만 manual override ON으로 risk_off 전환 생략")
                        self._failure_streak = 0
                    else:
                        self._status = "risk_off"
                        self._append_log("error", "연속 실패 한도 → risk_off (paper-trading/risk-reset 또는 stop 후 재시작)")
                        self._save_desired_state()
            end = time.monotonic() + float(self._interval_sec())
            while self._run_flag and time.monotonic() < end:
                time.sleep(min(1.0, end - time.monotonic()))

    def start(self, user_id: str, strategy_id: str, market: str | None = None) -> dict[str, Any]:
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

        ens = svc.ensure_cached_token_for_paper_start(user_id)
        self._paper_token_ensure_meta = {
            "token_cache_hit": ens.token_cache_hit,
            "token_cache_source": ens.token_cache_source,
            "token_cache_persisted": ens.token_cache_persisted,
            "cache_miss_reason": ens.cache_miss_reason,
            "start_blocked_reason": None if ens.ok else ens.message,
            "token_error_code": ens.token_error_code,
        }
        if not ens.ok:
            raise ValueError(ens.failure_code or "PAPER_TOKEN_NOT_READY")
        self._last_paper_initial_token_source = ens.token_cache_source or None

        mk = (market or "domestic").strip().lower()
        self._paper_market = "us" if mk in ("us", "usa", "nyse", "nasdaq", "us_equity", "us_equities") else "domestic"

        sid_l = (strategy_id or "").lower().strip()
        fb_diag = paper_final_betting_diagnostics()
        self._last_start_diagnostics = {
            "strategy_id": strategy_id,
            "effective_market": self._paper_market,
            "paper_final_betting_enabled_fresh": bool(paper_final_betting_enabled_fresh()),
            "paper_final_betting_enabled_cached_settings": fb_diag.get("paper_final_betting_enabled_cached_settings"),
            "settings_cache_mismatch": fb_diag.get("settings_cache_mismatch"),
            "final_betting_env_sources": fb_diag.get("final_betting_env_sources"),
        }
        logger.info("paper start diagnostics %s", self._last_start_diagnostics)
        if sid_l == "final_betting_v1" and not bool(paper_final_betting_enabled_fresh()):
            raise ValueError("FINAL_BETTING_DISABLED")

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
            self._started_at_utc = datetime.now(timezone.utc).isoformat()
            self._user_loop = None
            self._user_loop_identity = None
            self._last_positions_refresh_at = 0.0
            self._last_paper_portfolio_sync_at = 0.0
            self._run_flag = True
            self._desired_running = True
            self._thread = threading.Thread(target=self._loop, name="paper-user-session", daemon=True)
            self._thread.start()
            self._save_desired_state()
            self._append_log(
                "info",
                f"Paper 세션 시작 strategy={strategy_id} market={self._paper_market} (KIS 모의) diag={self._last_start_diagnostics}",
            )
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
            self._desired_running = False
            self._paper_market = "domestic"
            self._manual_override_enabled = False
        self._last_paper_initial_token_source = None
        self._save_desired_state()
        self._clear_desired_state()
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
            self._desired_running = True
            self._save_desired_state()
        self._append_log("info", "Paper risk_off 해제")
        return {"ok": True, "status": self._status}

    def status_payload(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mode": "paper",
                "status": self._status,
                "session_user_id": self._user_id,
                "strategy_id": self._strategy_id,
                "paper_market": self._paper_market,
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
                "started_at_utc": self._started_at_utc,
                "desired_running": self._desired_running,
                "desired_state_path": str(self._state_path),
                "resume_info": dict(self._resume_info),
                "diagnostics": dict(self._paper_diagnostics),
                "manual_override_enabled": self._manual_override_enabled,
                "session_state": self._last_report.get("us_session_state")
                or self._last_report.get("krx_session_state"),
                "final_betting_enabled_effective": paper_final_betting_diagnostics().get(
                    "final_betting_enabled_effective"
                ),
                "final_betting_env_sources": paper_final_betting_diagnostics().get("final_betting_env_sources"),
                "paper_start_diagnostics": dict(self._last_start_diagnostics),
            }

    def toggle_manual_override(self, requester_id: str) -> dict[str, Any]:
        if self._user_id and self._user_id != requester_id:
            raise RuntimeError("NOT_OWNER")
        with self._lock:
            self._manual_override_enabled = not self._manual_override_enabled
            if self._manual_override_enabled:
                self._failure_streak = 0
                self._last_error = None
                if self._status == "risk_off":
                    self._status = "running"
            enabled = self._manual_override_enabled
            loop = self._user_loop
            if loop is not None:
                loop.set_manual_override(enabled)
            self._save_desired_state()
        self._append_log("warning", f"Paper manual override toggled enabled={enabled}")
        return {"ok": True, "manual_override_enabled": enabled, "status": self._status}

    def diagnostics_payload(self) -> dict[str, Any]:
        from backend.app.core.version_info import get_backend_version_payload

        with self._lock:
            base = dict(self._paper_diagnostics)
            merged = {**self._paper_token_ensure_meta, **base}
            merged["session_last_error"] = self._last_error
            merged["session_status"] = self._status
            ver = get_backend_version_payload()
            merged["backend_git_sha"] = ver.get("git_sha", "")
            merged["backend_build_time"] = ver.get("build_time", "")
            merged["backend_app_version"] = ver.get("app_version", "")
            fb = paper_final_betting_diagnostics()
            merged["final_betting_enabled_effective"] = fb.get("final_betting_enabled_effective")
            merged["final_betting_env_sources"] = fb.get("final_betting_env_sources")
            merged["paper_final_betting_cache_mismatch"] = fb.get("settings_cache_mismatch")
            merged["paper_start_diagnostics"] = dict(self._last_start_diagnostics)
            return merged

    def paper_token_ensure_snapshot(self) -> dict[str, Any]:
        """마지막 Paper start 시도 시 토큰 확보 메타(HTTP 예외 detail 용)."""
        with self._lock:
            return dict(self._paper_token_ensure_meta)

    def get_positions(self) -> list[dict[str, Any]]:
        return list(self._last_positions)

    def _session_running(self) -> bool:
        return bool(self._run_flag and self._thread and self._thread.is_alive())

    def market_request_matches(self, market: str | None) -> tuple[bool, str, str]:
        """(ok, requested, session) — 세션이 돌아가는데 market 쿼리가 다르면 ok=False."""
        req = normalize_paper_market_param(market)
        with self._lock:
            sess = (self._paper_market or "domestic").strip().lower()
            running = self._session_running()
            has_user = bool(self._user_id)
        if sess in ("us", "usa"):
            sess = "us"
        else:
            sess = "domestic"
        if running and has_user and req != sess:
            return False, req, sess
        return True, req, sess

    def get_positions_payload(self, *, market: str | None) -> dict[str, Any]:
        ok, req, sess = self.market_request_matches(market)
        base = {
            "paper_market": sess,
            "requested_market": req,
            "market_mismatch": not ok,
        }
        if not ok:
            return {**base, "items": [], "message": "실행 중인 Paper 세션의 market 과 요청이 다릅니다."}
        return {**base, "items": self.get_positions()}

    def pnl_payload(self, *, market: str | None) -> dict[str, Any]:
        ok, req, sess = self.market_request_matches(market)
        p = self.pnl_from_last_report()
        p["paper_market"] = sess
        p["requested_market"] = req
        p["market_mismatch"] = not ok
        if not ok:
            p["note"] = "market 불일치 — 마지막 틱 손익은 숨기고 0으로 표시합니다."
            p["today_return_pct"] = 0.0
            p["cumulative_return_pct"] = 0.0
            p["position_count"] = 0
            p["equity"] = None
        return p

    def logs_payload(self, *, market: str | None) -> dict[str, Any]:
        ok, req, sess = self.market_request_matches(market)
        return {
            "items": self.get_logs(),
            "paper_market": sess,
            "requested_market": req,
            "market_mismatch": not ok,
        }

    def get_open_orders(self, user_id: str | None = None) -> dict[str, Any]:
        """사용자 Paper 계정 기준 미체결. 세션 없거나 소유자가 아니면 error."""
        with self._lock:
            if not self._user_loop or self._status not in ("running", "risk_off"):
                return {"items": [], "error": None}
            if user_id and self._user_id != user_id:
                return {"items": [], "error": "NOT_OWNER"}
            loop = self._user_loop
        return loop.fetch_open_orders_payload()

    def get_recent_fills(self, user_id: str | None = None, *, limit: int = 20) -> dict[str, Any]:
        with self._lock:
            if not self._user_loop or self._status not in ("running", "risk_off"):
                return {"items": [], "error": None}
            if user_id and self._user_id != user_id:
                return {"items": [], "error": "NOT_OWNER"}
            loop = self._user_loop
        return loop.fetch_recent_fills_payload(limit=limit)

    def get_dashboard_payload(self, user_id: str, *, market: str | None = None) -> dict[str, Any]:
        """Paper 세션 틱 리포트 + 포지션/미체결/체결 + 진단(온디맨드 KIS 조회 포함)."""
        ok_m, req_m, sess_m = self.market_request_matches(market)
        if not ok_m:
            return {
                "ok": False,
                "error": "MARKET_QUERY_MISMATCH",
                "requested_market": req_m,
                "paper_market": sess_m,
                "message": "실행 중인 세션과 다른 market 입니다.",
            }
        with self._lock:
            if self._user_id != user_id:
                return {"ok": False, "error": "NOT_OWNER_OR_NO_SESSION"}
            if self._status not in ("running", "risk_off"):
                return {"ok": False, "error": "PAPER_SESSION_NOT_ACTIVE"}
            st = self.status_payload()
            rep = dict(self._last_report)
            loop = self._user_loop
        if loop is None:
            return {"ok": False, "error": "PAPER_LOOP_NOT_READY"}

        oo = loop.fetch_open_orders_payload()
        rf = loop.fetch_recent_fills_payload(limit=20)
        pos = self.get_positions()

        cand = rep.get("candidate_count")
        if cand is None:
            cand = len(rep.get("candidates") or [])
        gen_ct = rep.get("generated_order_count")
        if gen_ct is None:
            gen_ct = len(rep.get("generated_orders") or [])

        cfb = rep.get("candidate_filter_breakdown") or []
        tick_report = {
            "candidate_count": cand,
            "candidates": list(rep.get("candidates") or []),
            "generated_order_count": gen_ct,
            "generated_orders": list(rep.get("generated_orders") or []),
            "no_order_reason": rep.get("no_order_reason") or "",
            "last_diagnostics": list(rep.get("last_diagnostics") or []),
            "candidate_filter_breakdown": list(cfb),
            "timeframe": rep.get("timeframe"),
            "trade_count_today": rep.get("trade_count_today"),
            "intraday_filter_breakdown": list(rep.get("intraday_filter_breakdown") or []),
            "intraday_signal_breakdown": dict(rep.get("intraday_signal_breakdown") or {}),
            "forced_flatten": bool(rep.get("forced_flatten")),
            "flatten_before_close_armed": bool(rep.get("flatten_before_close_armed")),
            "cooldown_symbols": list(rep.get("cooldown_symbols") or []),
            "paper_intraday_target_round_trip_trades": rep.get("paper_intraday_target_round_trip_trades"),
            "daily_pnl_pct_snapshot": rep.get("daily_pnl_pct_snapshot"),
            "risk_halt_new_entries": rep.get("risk_halt_new_entries"),
            # 인트라데이(scalp) 진단 — 분봉 수집 vs 후보 0 vs 신호 0 구분용
            "session_open_kst": rep.get("session_open_kst"),
            "regular_session_kst": rep.get("regular_session_kst"),
            "minute_bars_present": rep.get("minute_bars_present"),
            "symbols_request_count": rep.get("symbols_request_count"),
            "paper_trading_symbols_resolved": list(rep.get("paper_trading_symbols_resolved") or []),
            "intraday_symbols_source": rep.get("intraday_symbols_source"),
            "intraday_universe_symbol_count": rep.get("intraday_universe_symbol_count"),
            "intraday_universe_row_count": rep.get("intraday_universe_row_count"),
            "intraday_bar_fetch_summary": list(rep.get("intraday_bar_fetch_summary") or []),
            "fetch_error_summary": rep.get("fetch_error_summary"),
            "intraday_first_api_error": rep.get("intraday_first_api_error"),
            "multi_strategy_snapshot": rep.get("multi_strategy_snapshot"),
            "krx_session_state": rep.get("krx_session_state"),
            "fetch_allowed": rep.get("fetch_allowed"),
            "order_allowed": rep.get("order_allowed"),
            "fetch_block_reason": rep.get("fetch_block_reason"),
            "order_block_reason": rep.get("order_block_reason"),
            "orders_blocked_session": rep.get("orders_blocked_session"),
            "strategy_profile": rep.get("strategy_profile"),
            "close_betting_forced_flatten": rep.get("close_betting_forced_flatten"),
        }

        return {
            "ok": True,
            "paper_market": sess_m,
            "requested_market": req_m,
            "status": st.get("status"),
            "strategy_id": st.get("strategy_id"),
            "failure_streak": st.get("failure_streak"),
            "last_error": st.get("last_error"),
            "last_tick_at": st.get("last_tick_at"),
            "last_tick_summary": st.get("last_tick_summary") or {},
            "positions": pos,
            "open_orders": oo.get("items") or [],
            "open_orders_error": oo.get("error"),
            "recent_fills": rf.get("items") or [],
            "recent_fills_error": rf.get("error"),
            "diagnostics": st.get("diagnostics") or {},
            "candidate_count": cand,
            "ranking": rep.get("ranking") or [],
            "generated_order_count": gen_ct,
            "generated_orders": rep.get("generated_orders") or [],
            "accepted_orders": rep.get("accepted_orders"),
            "rejected_orders": rep.get("rejected_orders"),
            "no_order_reason": rep.get("no_order_reason") or "",
            "regime": rep.get("regime"),
            "last_diagnostics": rep.get("last_diagnostics") or [],
            "candidates": rep.get("candidates") or [],
            "candidate_filter_breakdown": cfb,
            "tick_report": tick_report,
        }

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
