"""
앱에 저장된 KIS **모의** 자격증명으로 장중 1틱: 유니버스 → 전략 신호 → 리스크 → KisPaperBroker 주문.
서버 .env 계정과 무관하게 동작 (단, portfolio 백그라운드 sync 는 .env 기준이면 대시보드 정합은 .env 일치 권장).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.brokers.kis_paper_broker import KisPaperBroker
from app.clients.kis_client import KISClientError
from app.config import get_settings
from app.risk.kill_switch import KillSwitch
from app.risk.rules import RiskLimits, RiskRules
from app.scheduler.equity_tracker import EquityTracker
from app.scheduler.intraday_jobs import IntradaySchedulerJobs, fetch_quotes_throttled, infer_forced_flatten
from app.scheduler.jobs import SchedulerJobs
from app.scheduler.kis_intraday import (
    IntradayChartCache,
    build_intraday_universe_1m,
    universe_as_timeframe,
)
from app.scheduler.kis_universe import (
    build_kis_stock_universe,
    build_kospi_index_series,
    build_mock_sp500_proxy_from_kospi,
)
from app.strategy.intraday_paper_state import IntradayPaperStateStore

from backend.app.auth.kis_auth import issue_access_token
from backend.app.clients.kis_client import build_kis_client_for_paper_user
from backend.app.core.config import BackendSettings, get_backend_settings
from backend.app.engine.paper_strategy import strategy_for_paper_id

logger = logging.getLogger("backend.app.engine.user_paper_loop")


def _is_intraday_scalp_strategy(strategy_id: str) -> bool:
    s = (strategy_id or "").lower().strip()
    return s in ("scalp_momentum_v1", "scalp_momentum_v2")


class UserPaperTradingLoop:
    def __init__(
        self,
        *,
        app_key: str,
        app_secret: str,
        account_no: str,
        product_code: str,
        api_base: str,
        strategy_id: str,
        user_tag: str,
        backend_settings: BackendSettings | None = None,
        initial_access_token: str | None = None,
        initial_token_source_label: str | None = None,
    ) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._account_no = account_no
        self._product_code = product_code
        self._api_base = api_base.rstrip("/")
        self._strategy_id = strategy_id
        self._user_tag = user_tag
        self._backend = backend_settings or get_backend_settings()
        self._access_token: str | None = initial_access_token
        self._token_monotonic: float = time.monotonic() if initial_access_token else 0.0
        self._token_issued_locally: bool = False
        self._initial_token_source_label: str | None = initial_token_source_label
        self._univ_sig: str | None = None
        self._univ_ts: float = 0.0
        self._univ_df: Any = None
        self._kospi_sig: str | None = None
        self._kospi_ts: float = 0.0
        self._kospi_df: Any = None
        self._last_token_failure_at_iso: str | None = None
        self._last_token_error_code: str | None = None
        self._last_token_http_status: int | None = None

    def _issue_token(self) -> str:
        tr = issue_access_token(
            app_key=self._app_key,
            app_secret=self._app_secret,
            base_url=self._api_base,
            timeout_sec=12,
        )
        self._last_token_http_status = tr.status_code
        if not tr.ok or not tr.access_token:
            code = tr.error_code or ""
            self._last_token_failure_at_iso = datetime.now(timezone.utc).isoformat()
            self._last_token_error_code = code or "TOKEN_FAILURE"
            msg = tr.message or "token_failed"
            if code == "TOKEN_RATE_LIMIT":
                raise RuntimeError("TOKEN_RATE_LIMIT: " + msg)
            raise RuntimeError(msg)
        self._last_token_failure_at_iso = None
        self._last_token_error_code = None
        self._access_token = tr.access_token
        self._token_monotonic = time.monotonic()
        self._token_issued_locally = True
        return tr.access_token

    def token_source_for_diagnostics(self) -> str:
        """브로커 메모리/DB 캐시·루프 내 재발급 구분 (diagnostics token_cache_source)."""
        if self._token_issued_locally:
            return "fresh_issue"
        if self._initial_token_source_label:
            return self._initial_token_source_label
        return "broker_reuse"

    def _kis_client(self):
        if not self._access_token or (time.monotonic() - self._token_monotonic) > 1500:
            self._issue_token()
        return build_kis_client_for_paper_user(
            base_url=self._api_base,
            access_token=self._access_token or "",
            app_key=self._app_key,
            app_secret=self._app_secret,
        )

    def _build_jobs(self, client):
        cfg = get_settings()
        broker = KisPaperBroker(
            kis_client=client,
            account_no=self._account_no,
            account_product_code=self._product_code,
            logger=logger,
        )
        eq_path = Path(cfg.paper_session_state_path).parent / f"equity_tracker_{self._user_tag}.json"
        tracker = EquityTracker(eq_path, logger=logger)
        rules = RiskRules(
            RiskLimits(
                daily_loss_limit_pct=cfg.daily_loss_limit_pct,
                total_loss_limit_pct=cfg.total_loss_limit_pct,
                default_stop_loss_pct=cfg.default_stop_loss_pct,
            )
        )
        kill = KillSwitch(rules=rules)
        strat = strategy_for_paper_id(self._strategy_id)
        return SchedulerJobs(
            strategy=strat,
            broker=broker,
            risk_rules=rules,
            kill_switch=kill,
            equity_tracker=tracker,
            logger=logger,
        )

    def _build_intraday_jobs(self, client, *, state_store: IntradayPaperStateStore):
        cfg = get_settings()
        broker = KisPaperBroker(
            kis_client=client,
            account_no=self._account_no,
            account_product_code=self._product_code,
            logger=logger,
        )
        eq_path = Path(cfg.paper_session_state_path).parent / f"equity_tracker_{self._user_tag}.json"
        tracker = EquityTracker(eq_path, logger=logger)
        rules = RiskRules(
            RiskLimits(
                daily_loss_limit_pct=cfg.daily_loss_limit_pct,
                total_loss_limit_pct=cfg.total_loss_limit_pct,
                default_stop_loss_pct=cfg.default_stop_loss_pct,
            )
        )
        kill = KillSwitch(rules=rules)
        strat = strategy_for_paper_id(self._strategy_id)
        return IntradaySchedulerJobs(
            strategy=strat,
            broker=broker,
            risk_rules=rules,
            kill_switch=kill,
            equity_tracker=tracker,
            state_store=state_store,
            logger=logger,
        )

    def _run_intraday_scalp_tick(self) -> dict[str, Any]:
        """분봉 단타 전용 — 일봉 유니버스와 분리."""
        failed_step = "kis_client"
        try:
            try:
                client = self._kis_client()
            except RuntimeError as exc:
                err_s = str(exc)
                is_rl = err_s.startswith("TOKEN_RATE_LIMIT:") or "TOKEN_RATE_LIMIT" in err_s
                fk = "token_rate_limit" if is_rl else "token_failure"
                return {
                    "ok": False,
                    "error": err_s,
                    "failed_step": "kis_token",
                    "kis_context": {},
                    "token_source": self.token_source_for_diagnostics(),
                    "failure_kind": fk,
                    "token_error_code": "TOKEN_RATE_LIMIT" if is_rl else (self._last_token_error_code or "TOKEN_FAILURE"),
                    "paper_loop_fresh_issue": False,
                    "paper_loop_last_token_failure_at": self._last_token_failure_at_iso,
                    "paper_loop_last_token_http_status": self._last_token_http_status,
                }

            cfg = get_settings()
            symbols = [s.strip() for s in cfg.paper_trading_symbols.split(",") if s.strip()]
            if not symbols:
                return {
                    "ok": False,
                    "error": "paper_trading_symbols 비어 있음 (app 설정)",
                    "failed_step": "config",
                    "kis_context": {},
                    "token_source": self.token_source_for_diagnostics(),
                    "failure_kind": "config",
                }
            if cfg.paper_smoke_mode:
                symbols = symbols[:1]

            state_path = Path(cfg.paper_session_state_path).parent / f"paper_intraday_state_{self._user_tag}.json"
            state_store = IntradayPaperStateStore(state_path, logger=logger)
            chart_cache = IntradayChartCache(
                ttl_sec=float(cfg.paper_intraday_chart_cache_ttl_sec),
                min_interval_sec=float(cfg.paper_intraday_chart_min_interval_sec),
            )

            failed_step = "intraday_universe"
            universe_1m = build_intraday_universe_1m(
                client,
                symbols,
                target_bars_per_symbol=140,
                logger=logger,
                cache=chart_cache,
            )

            sid = (self._strategy_id or "").lower().strip()
            if sid == "scalp_momentum_v1":
                universe_tf = universe_as_timeframe(universe_1m, 3)
                timeframe = "3m"
            else:
                universe_tf = universe_1m
                timeframe = "1m"

            failed_step = "kospi_series"
            now_m = time.monotonic()
            ttl_u = int(cfg.paper_kis_kospi_cache_ttl_sec)
            lookback = max(int(cfg.paper_kis_chart_lookback_days), 60)
            univ_key = f"kospi|{lookback}"
            kospi_cache_hit = False
            if (
                ttl_u > 0
                and self._kospi_df is not None
                and self._kospi_sig == univ_key
                and (now_m - self._kospi_ts) < float(ttl_u)
            ):
                kospi = self._kospi_df
                kospi_cache_hit = True
            else:
                kospi = build_kospi_index_series(
                    client,
                    lookback_calendar_days=lookback,
                    logger=logger,
                )
                self._kospi_sig = univ_key
                self._kospi_ts = time.monotonic()
                self._kospi_df = kospi

            sp500 = build_mock_sp500_proxy_from_kospi(kospi)

            failed_step = "intraday_quotes"
            quote_by_symbol = fetch_quotes_throttled(
                client,
                symbols,
                min_interval_sec=max(0.15, float(cfg.paper_intraday_chart_min_interval_sec)),
                logger=logger,
            )
            forced_flatten = infer_forced_flatten(cfg)

            failed_step = "intraday_jobs"
            jobs = self._build_intraday_jobs(client, state_store=state_store)
            report = jobs.run_intraday_cycle(
                universe_tf=universe_tf,
                kospi_index=kospi,
                sp500_index=sp500,
                timeframe=timeframe,
                quote_by_symbol=quote_by_symbol,
                forced_flatten=forced_flatten,
            )

            return {
                "ok": True,
                "report": report,
                "token_source": self.token_source_for_diagnostics(),
                "token_cache_source": self.token_source_for_diagnostics(),
                "token_error_code": None,
                "paper_loop_fresh_issue": self._token_issued_locally,
                "paper_loop_last_token_failure_at": self._last_token_failure_at_iso,
                "paper_loop_last_token_error_code": self._last_token_error_code,
                "paper_loop_last_token_http_status": self._last_token_http_status,
                "universe_cache_hit": False,
                "kospi_cache_hit": kospi_cache_hit,
                "request_budget_mode": "paper_intraday",
                "throttled_mode": int(cfg.kis_min_request_interval_ms) > 0,
                "paper_tick_interval_sec": int(cfg.paper_intraday_loop_interval_sec),
                "paper_intraday_mode": True,
            }
        except KISClientError as exc:
            ctx = getattr(exc, "kis_context", {}) or {}
            if ctx.get("rate_limit"):
                fk = "rate_limit"
            elif "business error" in str(exc).lower():
                fk = "kis_business_error"
            else:
                fk = "kis_client_error"
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": ctx,
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": fk,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": {},
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": type(exc).__name__,
            }

    def run_intraday_tick(self) -> dict[str, Any]:
        cfg = get_settings()
        if _is_intraday_scalp_strategy(self._strategy_id):
            if not bool(cfg.paper_intraday_enabled):
                return {
                    "ok": False,
                    "error": "scalp 전략은 PAPER_INTRADAY_ENABLED=true 일 때만 실행됩니다.",
                    "failed_step": "config",
                    "kis_context": {},
                    "token_source": self.token_source_for_diagnostics(),
                    "failure_kind": "config",
                }
            return self._run_intraday_scalp_tick()

        failed_step = "kis_client"
        try:
            try:
                client = self._kis_client()
            except RuntimeError as exc:
                err_s = str(exc)
                is_rl = err_s.startswith("TOKEN_RATE_LIMIT:") or "TOKEN_RATE_LIMIT" in err_s
                fk = "token_rate_limit" if is_rl else "token_failure"
                return {
                    "ok": False,
                    "error": err_s,
                    "failed_step": "kis_token",
                    "kis_context": {},
                    "token_source": self.token_source_for_diagnostics(),
                    "failure_kind": fk,
                    "token_error_code": "TOKEN_RATE_LIMIT" if is_rl else (self._last_token_error_code or "TOKEN_FAILURE"),
                    "paper_loop_fresh_issue": False,
                    "paper_loop_last_token_failure_at": self._last_token_failure_at_iso,
                    "paper_loop_last_token_http_status": self._last_token_http_status,
                }

            failed_step = "build_jobs"
            jobs = self._build_jobs(client)
            cfg = get_settings()
            symbols = [s.strip() for s in cfg.paper_trading_symbols.split(",") if s.strip()]
            if not symbols:
                return {
                    "ok": False,
                    "error": "paper_trading_symbols 비어 있음 (app 설정)",
                    "failed_step": "config",
                    "kis_context": {},
                    "token_source": self.token_source_for_diagnostics(),
                    "failure_kind": "config",
                }
            if cfg.paper_smoke_mode:
                symbols = symbols[:1]
                lookback = min(60, int(cfg.paper_kis_chart_lookback_days))
            else:
                lookback = max(int(cfg.paper_kis_chart_lookback_days), 60)

            now_m = time.monotonic()
            ttl_u = int(cfg.paper_kis_universe_cache_ttl_sec)
            univ_key = f"{','.join(symbols)}|{lookback}"
            failed_step = "kis_universe"
            universe_cache_hit = False
            if (
                ttl_u > 0
                and self._univ_df is not None
                and self._univ_sig == univ_key
                and (now_m - self._univ_ts) < float(ttl_u)
            ):
                universe = self._univ_df
                universe_cache_hit = True
            else:
                universe = build_kis_stock_universe(
                    client,
                    symbols,
                    lookback_calendar_days=lookback,
                    logger=logger,
                )
                self._univ_sig = univ_key
                self._univ_ts = time.monotonic()
                self._univ_df = universe

            failed_step = "kospi_series"
            ttl_k = int(cfg.paper_kis_kospi_cache_ttl_sec)
            kospi_key = str(lookback)
            kospi_cache_hit = False
            if (
                ttl_k > 0
                and self._kospi_df is not None
                and self._kospi_sig == kospi_key
                and (now_m - self._kospi_ts) < float(ttl_k)
            ):
                kospi = self._kospi_df
                kospi_cache_hit = True
            else:
                kospi = build_kospi_index_series(
                    client,
                    lookback_calendar_days=lookback,
                    logger=logger,
                )
                self._kospi_sig = kospi_key
                self._kospi_ts = time.monotonic()
                self._kospi_df = kospi
            failed_step = "daily_cycle"
            sp500 = build_mock_sp500_proxy_from_kospi(kospi)
            report = jobs.run_daily_cycle(universe=universe, kospi_index=kospi, sp500_index=sp500)

            if self._backend.screener_auto_refresh_with_runtime:
                try:
                    from backend.app.strategy.screener import get_screener_engine

                    snap = get_screener_engine().refresh()
                    report = dict(report)
                    report["screener"] = {
                        "regime": snap.regime,
                        "blocked": snap.blocked,
                        "candidate_count": len(snap.candidates),
                        "updated_at_utc": snap.updated_at_utc,
                    }
                except Exception as exc:
                    logger.warning("screener refresh failed: %s", exc)

            return {
                "ok": True,
                "report": report,
                "token_source": self.token_source_for_diagnostics(),
                "token_cache_source": self.token_source_for_diagnostics(),
                "token_error_code": None,
                "paper_loop_fresh_issue": self._token_issued_locally,
                "paper_loop_last_token_failure_at": self._last_token_failure_at_iso,
                "paper_loop_last_token_error_code": self._last_token_error_code,
                "paper_loop_last_token_http_status": self._last_token_http_status,
                "universe_cache_hit": universe_cache_hit,
                "kospi_cache_hit": kospi_cache_hit,
                "request_budget_mode": "paper_conserve",
                "throttled_mode": int(cfg.kis_min_request_interval_ms) > 0,
                "paper_tick_interval_sec": int(cfg.paper_trading_interval_sec),
                "paper_intraday_mode": False,
            }
        except KISClientError as exc:
            ctx = getattr(exc, "kis_context", {}) or {}
            if ctx.get("rate_limit"):
                fk = "rate_limit"
            elif "business error" in str(exc).lower():
                fk = "kis_business_error"
            else:
                fk = "kis_client_error"
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": ctx,
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": fk,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": {},
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": type(exc).__name__,
            }

    def snapshot_positions(self) -> list[dict[str, Any]]:
        client = self._kis_client()
        broker = KisPaperBroker(
            kis_client=client,
            account_no=self._account_no,
            account_product_code=self._product_code,
            logger=logger,
        )
        return [
            {"symbol": p.symbol, "quantity": p.quantity, "average_price": p.average_price}
            for p in broker.get_positions()
        ]

    def _paper_broker(self) -> KisPaperBroker:
        client = self._kis_client()
        return KisPaperBroker(
            kis_client=client,
            account_no=self._account_no,
            account_product_code=self._product_code,
            logger=logger,
        )

    def fetch_open_orders_payload(self) -> dict[str, Any]:
        """KIS 모의 미체결(nccs). 실패 시 error 문자열, items 는 항상 리스트."""
        items: list[dict[str, Any]] = []
        err: str | None = None
        try:
            for o in self._paper_broker().get_open_orders():
                items.append(
                    {
                        "order_id": o.order_id,
                        "symbol": o.symbol,
                        "side": o.side,
                        "quantity": o.quantity,
                        "remaining_quantity": o.remaining_quantity,
                        "price": o.price,
                        "created_at": o.created_at.isoformat(),
                    }
                )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            logger.warning("fetch_open_orders_payload failed: %s", err)
        return {"items": items, "error": err}

    def fetch_recent_fills_payload(self, *, limit: int = 20) -> dict[str, Any]:
        """당일 체결(CCLD). 최신 순 최대 limit 건."""
        items: list[dict[str, Any]] = []
        err: str | None = None
        try:
            fills = self._paper_broker().get_fills()
            sorted_fills = sorted(
                fills,
                key=lambda f: f.filled_at.timestamp() if f.filled_at else 0.0,
                reverse=True,
            )
            for fl in sorted_fills[: max(0, limit)]:
                items.append(
                    {
                        "fill_id": fl.fill_id,
                        "order_id": fl.order_id,
                        "symbol": fl.symbol,
                        "side": fl.side,
                        "quantity": fl.quantity,
                        "price": fl.fill_price,
                        "filled_at": fl.filled_at.isoformat() if fl.filled_at else None,
                    }
                )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            logger.warning("fetch_recent_fills_payload failed: %s", err)
        return {"items": items, "error": err}
