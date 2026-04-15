"""
KIS 모의 + app 전략/리스크/주문 파이프라인 연동.

- 장전: 유니버스 구축 및 후보 필터 요약
- 장중: 시세(일봉) 갱신 → 전략 → 리스크 → 주문
- 장후: 잔고·미체결·일별체결 스냅샷 및 일일 리포트 파일
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.app.auth.kis_auth import KIS_OAUTH_TOKEN_HTTP_PATH, issue_access_token
from backend.app.clients.kis_client import build_kis_client_for_backend
from backend.app.core.config import BackendSettings, get_backend_settings, resolved_kis_api_base_url
from backend.app.engine.scheduler import MarketPhase, now_kst
from backend.app.portfolio.sync_engine import run_portfolio_sync

logger = logging.getLogger("backend.app.engine.market_loop")

_last_kis_token_failure_diag: dict[str, Any] | None = None


def get_last_kis_token_failure_diag() -> dict[str, Any] | None:
    """Volatile: 마지막 KIS OAuth 토큰 실패 맥락(runtime_engine / market_loop)."""
    return _last_kis_token_failure_diag


@dataclass
class MarketLoopResult:
    ok: bool
    phase: str
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class BackendMarketLoop:
    """TRADING_MODE=paper + openapivts 전제 (실전 호스트면 주문은 클라이언트 잠금)."""

    def __init__(self, settings: BackendSettings | None = None) -> None:
        self._backend = settings or get_backend_settings()
        self._access_token: str | None = None
        self._token_monotonic: float = 0.0

    def _issue_token(self) -> str:
        global _last_kis_token_failure_diag
        base = resolved_kis_api_base_url(self._backend)
        trading_mode = (self._backend.trading_mode or "").strip().lower()
        tr = issue_access_token(
            app_key=self._backend.kis_app_key,
            app_secret=self._backend.kis_app_secret,
            base_url=base,
            timeout_sec=12,
        )
        if not tr.ok or not tr.access_token:
            diag: dict[str, Any] = {
                "kis_base_url": tr.kis_base_url or base,
                "kis_http_path": tr.kis_http_path or KIS_OAUTH_TOKEN_HTTP_PATH,
                "kis_http_status": tr.status_code,
                "kis_tr_id": tr.kis_tr_id,
                "trading_mode": trading_mode,
                "error_code": tr.error_code,
                "message": tr.message,
            }
            _last_kis_token_failure_diag = diag
            logger.error("KIS token failure (runtime_engine): %s", json.dumps(diag, ensure_ascii=False))
            raise RuntimeError(f"{tr.message} | {json.dumps(diag, ensure_ascii=False)}")
        _last_kis_token_failure_diag = None
        self._access_token = tr.access_token
        self._token_monotonic = time.monotonic()
        return tr.access_token

    def _kis_client(self):
        if not self._access_token or (time.monotonic() - self._token_monotonic) > 1500:
            self._issue_token()
        return build_kis_client_for_backend(self._backend, access_token=self._access_token or "")

    def _app_config(self):
        from app.config import get_settings

        return get_settings()

    def _require_paper_mock(self) -> None:
        base = resolved_kis_api_base_url(self._backend)
        if "openapivts" not in base:
            raise RuntimeError(
                "런타임 엔진은 KIS 모의 호스트(openapivts)에서만 동작합니다. TRADING_MODE=paper 를 확인하세요."
            )
        if (self._backend.trading_mode or "").lower() != "paper":
            raise RuntimeError("런타임 엔진 기본 정책: TRADING_MODE=paper 만 허용합니다.")

    def _build_jobs(self, client):
        self._require_paper_mock()
        cfg = self._app_config()
        from app.brokers.kis_paper_broker import KisPaperBroker
        from app.risk.kill_switch import KillSwitch
        from app.risk.rules import RiskLimits, RiskRules
        from app.scheduler.equity_tracker import EquityTracker
        from app.scheduler.jobs import SchedulerJobs

        acct = cfg.resolved_account_no
        prod = cfg.resolved_account_product_code
        if not acct or not prod:
            raise RuntimeError("KIS_ACCOUNT_NO / KIS_ACCOUNT_PRODUCT_CODE (.env) 가 필요합니다.")

        broker = KisPaperBroker(kis_client=client, account_no=acct, account_product_code=prod, logger=logger)
        tracker = EquityTracker(Path(cfg.paper_session_state_path), logger=logger)
        rules = RiskRules(
            RiskLimits(
                daily_loss_limit_pct=cfg.daily_loss_limit_pct,
                total_loss_limit_pct=cfg.total_loss_limit_pct,
                default_stop_loss_pct=cfg.default_stop_loss_pct,
            )
        )
        kill = KillSwitch(rules=rules)
        return SchedulerJobs(broker=broker, risk_rules=rules, kill_switch=kill, equity_tracker=tracker)

    def run_premarket(self) -> MarketLoopResult:
        """장 시작 전: KIS 일봉 유니버스 + 품질 필터 요약."""
        try:
            self._require_paper_mock()
            client = self._kis_client()
            cfg = self._app_config()
            symbols = [s.strip() for s in cfg.paper_trading_symbols.split(",") if s.strip()]
            from app.scheduler.kis_universe import build_kis_stock_universe
            from app.strategy.filters import filter_quality_swing_candidates

            universe = build_kis_stock_universe(
                client,
                symbols,
                lookback_calendar_days=max(cfg.paper_kis_chart_lookback_days, 60),
                logger=logger,
            )
            candidates = filter_quality_swing_candidates(universe) if not universe.empty else []
            summary: dict[str, Any] = {
                "symbol_count": len(symbols),
                "universe_rows": len(universe),
                "filtered_candidates": candidates,
                "candidate_count": len(candidates),
            }
            if self._backend.screener_auto_refresh_with_runtime:
                try:
                    from backend.app.strategy.screener import get_screener_engine

                    snap = get_screener_engine().refresh()
                    summary["screener"] = {
                        "regime": snap.regime,
                        "blocked": snap.blocked,
                        "candidate_count": len(snap.candidates),
                        "updated_at_utc": snap.updated_at_utc,
                    }
                except Exception as exc:
                    logger.warning("screener premarket refresh failed: %s", exc)
                    summary["screener_error"] = str(exc)
            return MarketLoopResult(ok=True, phase=MarketPhase.PREMARKET, summary=summary)
        except Exception as exc:
            logger.exception("premarket pass failed")
            return MarketLoopResult(ok=False, phase=MarketPhase.PREMARKET, error=str(exc))

    def run_intraday_tick(self) -> MarketLoopResult:
        """장중: 전략·리스크·주문 1틱."""
        try:
            client = self._kis_client()
            jobs = self._build_jobs(client)
            cfg = self._app_config()
            symbols = [s.strip() for s in cfg.paper_trading_symbols.split(",") if s.strip()]
            from app.scheduler.kis_universe import (
                build_kis_stock_universe,
                build_kospi_index_series,
                build_mock_sp500_proxy_from_kospi,
            )

            universe = build_kis_stock_universe(
                client,
                symbols,
                lookback_calendar_days=max(cfg.paper_kis_chart_lookback_days, 60),
                logger=logger,
            )
            kospi = build_kospi_index_series(
                client,
                lookback_calendar_days=max(cfg.paper_kis_chart_lookback_days, 60),
                logger=logger,
            )
            sp500 = build_mock_sp500_proxy_from_kospi(kospi)
            report = jobs.run_daily_cycle(universe=universe, kospi_index=kospi, sp500_index=sp500)
            track = self._order_tracking_snapshot(client, cfg)
            sync_summary = run_portfolio_sync(backfill_days=self._backend.portfolio_sync_backfill_days, settings=self._backend)
            summary: dict[str, Any] = {
                "cycle_report": report,
                "order_tracking": track,
                "portfolio_sync": {
                    "ok": True,
                    "updated_at_utc": sync_summary.get("updated_at_utc"),
                    "warnings": sync_summary.get("warnings") or [],
                },
            }
            if self._backend.screener_auto_refresh_with_runtime:
                try:
                    from backend.app.strategy.screener import get_screener_engine

                    snap = get_screener_engine().refresh()
                    summary["screener"] = {
                        "regime": snap.regime,
                        "blocked": snap.blocked,
                        "candidate_count": len(snap.candidates),
                        "updated_at_utc": snap.updated_at_utc,
                    }
                except Exception as exc:
                    logger.warning("screener intraday refresh failed: %s", exc)
                    summary["screener_error"] = str(exc)
            return MarketLoopResult(ok=True, phase=MarketPhase.SESSION, summary=summary)
        except Exception as exc:
            logger.exception("intraday tick failed")
            return MarketLoopResult(ok=False, phase=MarketPhase.SESSION, error=str(exc))

    def _order_tracking_snapshot(self, client, cfg) -> dict[str, Any]:
        acct = cfg.resolved_account_no
        prod = cfg.resolved_account_product_code
        out: dict[str, Any] = {}
        try:
            n = client.inquire_nccs(account_no=acct, account_product_code=prod, symbol="")
            o1 = n.get("output1")
            out["open_orders_count"] = len(o1) if isinstance(o1, list) else 0
        except Exception as exc:
            out["nccs_error"] = str(exc)
        try:
            c = client.inquire_daily_ccld(account_no=acct, account_product_code=prod, symbol="", ccld_div="00")
            o1 = c.get("output1")
            out["daily_ccld_rows"] = len(o1) if isinstance(o1, list) else 0
        except Exception as exc:
            out["ccld_error"] = str(exc)
        return out

    def run_afterhours(self, reports_dir: Path) -> MarketLoopResult:
        """장 마감 후: 잔고·추적 스냅샷 JSON 저장."""
        try:
            client = self._kis_client()
            cfg = self._app_config()
            acct = cfg.resolved_account_no
            prod = cfg.resolved_account_product_code
            balance = client.get_balance(account_no=acct, account_product_code=prod)
            track = self._order_tracking_snapshot(client, cfg)
            sync_summary = run_portfolio_sync(backfill_days=self._backend.portfolio_sync_backfill_days, settings=self._backend)
            reports_dir.mkdir(parents=True, exist_ok=True)
            day = now_kst().strftime("%Y-%m-%d")
            path = reports_dir / f"eod_{day}.json"
            payload = {
                "date_kst": day,
                "written_at": now_kst().isoformat(),
                "balance_keys": list(balance.keys()),
                "order_tracking": track,
                "portfolio_sync": sync_summary,
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return MarketLoopResult(
                ok=True,
                phase=MarketPhase.AFTERHOURS,
                summary={"report_path": str(path)},
            )
        except Exception as exc:
            logger.exception("afterhours failed")
            return MarketLoopResult(ok=False, phase=MarketPhase.AFTERHOURS, error=str(exc))
