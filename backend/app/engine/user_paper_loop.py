"""
앱에 저장된 KIS **모의** 자격증명으로 장중 1틱: 유니버스 → 전략 신호 → 리스크 → KisPaperBroker 주문.
서버 .env 계정과 무관하게 동작 (단, portfolio 백그라운드 sync 는 .env 기준이면 대시보드 정합은 .env 일치 권장).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from app.brokers.kis_paper_broker import KisPaperBroker
from app.clients.kis_client import KISClientError
from app.config import get_settings
from app.risk.kill_switch import KillSwitch
from app.risk.rules import RiskLimits, RiskRules
from app.scheduler.equity_tracker import EquityTracker
from app.scheduler.jobs import SchedulerJobs
from app.scheduler.kis_universe import (
    build_kis_stock_universe,
    build_kospi_index_series,
    build_mock_sp500_proxy_from_kospi,
)

from backend.app.auth.kis_auth import issue_access_token
from backend.app.clients.kis_client import build_kis_client_for_paper_user
from backend.app.core.config import BackendSettings, get_backend_settings
from backend.app.engine.paper_strategy import strategy_for_paper_id

logger = logging.getLogger("backend.app.engine.user_paper_loop")


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

    def _issue_token(self) -> str:
        tr = issue_access_token(
            app_key=self._app_key,
            app_secret=self._app_secret,
            base_url=self._api_base,
            timeout_sec=12,
        )
        if not tr.ok or not tr.access_token:
            raise RuntimeError(tr.message or "token_failed")
        self._access_token = tr.access_token
        self._token_monotonic = time.monotonic()
        self._token_issued_locally = True
        return tr.access_token

    def token_source_for_diagnostics(self) -> str:
        """루프가 브로커 test-connection 캐시 토큰을 쓰는지, 루프 내 재발급인지 구분."""
        return "fresh_issue" if self._token_issued_locally else "test_connection_reuse"

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

    def run_intraday_tick(self) -> dict[str, Any]:
        failed_step = "kis_client"
        try:
            try:
                client = self._kis_client()
            except RuntimeError as exc:
                return {
                    "ok": False,
                    "error": str(exc),
                    "failed_step": "kis_token",
                    "kis_context": {},
                    "token_source": self.token_source_for_diagnostics(),
                    "failure_kind": "token_failure",
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

            failed_step = "kis_universe"
            universe = build_kis_stock_universe(
                client,
                symbols,
                lookback_calendar_days=max(cfg.paper_kis_chart_lookback_days, 60),
                logger=logger,
            )
            failed_step = "kospi_series"
            kospi = build_kospi_index_series(
                client,
                lookback_calendar_days=max(cfg.paper_kis_chart_lookback_days, 60),
                logger=logger,
            )
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
            }
        except KISClientError as exc:
            fk = "kis_business_error" if "business error" in str(exc).lower() else "kis_client_error"
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": getattr(exc, "kis_context", {}),
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
