from __future__ import annotations

import json
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

from app.auth.kis_auth import KISTokenService
from app.brokers.kis_paper_broker import KisPaperBroker
from app.clients.kis_client import KISClient
from app.config import Settings, get_settings
from app.logging import setup_logging
from app.risk.kill_switch import KillSwitch
from app.risk.rules import RiskLimits, RiskRules
from app.scheduler.equity_tracker import EquityTracker
from app.scheduler.jobs import SchedulerJobs
from app.scheduler.kis_universe import (
    build_kis_stock_universe,
    build_kospi_index_series,
    build_mock_sp500_proxy_from_kospi,
)


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")
            return
        payload = {"status": "ok", "service": "stock-quant-trading"}
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        # Keep console clean; app logger handles user-facing messages.
        _ = (format, args)


def start_health_server(port: int = 8000) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def run(settings: Settings | None = None) -> dict[str, object]:
    cfg = settings or get_settings()
    setup_logging()
    logger = logging.getLogger("app.main")

    _validate_startup_runtime_safety(cfg, logger)
    logger.info("Starting trading app")
    logger.info("Trading mode: %s", cfg.trading_mode)
    logger.info("Live trading enabled: %s", cfg.resolved_live_trading_enabled)
    logger.info("Live trading confirm: %s", cfg.live_trading_confirm)

    health_server = start_health_server(port=8000)
    logger.info("Health endpoint ready: GET http://localhost:8000/health")

    report: dict[str, object] = {}
    try:
        if cfg.paper_use_kis_execution:
            if cfg.paper_trading_loop:
                report = _run_kis_paper_trading_loop(cfg, logger)
            else:
                report = _run_single_kis_paper_cycle(cfg, logger)
        else:
            jobs = SchedulerJobs(risk_rules=_risk_rules_from_config(cfg))
            report = jobs.run_daily_cycle()
            logger.info("End-of-day report generated: %s", report)
            _check_shutdown_on_loss_limit(report, cfg, logger)
    finally:
        health_server.shutdown()
    logger.info("Paper trading app finished")
    return report


def _risk_rules_from_config(cfg: Settings) -> RiskRules:
    return RiskRules(
        RiskLimits(
            daily_loss_limit_pct=cfg.daily_loss_limit_pct,
            total_loss_limit_pct=cfg.total_loss_limit_pct,
            default_stop_loss_pct=cfg.default_stop_loss_pct,
        )
    )


def _validate_kis_paper_prereqs(cfg: Settings) -> None:
    if cfg.trading_mode != "paper":
        raise RuntimeError("KIS 모의 연동 자동매매는 TRADING_MODE=paper 에서만 사용할 수 있습니다.")
    if not cfg.kis_app_key or not cfg.kis_app_secret:
        raise RuntimeError("KIS_APP_KEY 및 KIS_APP_SECRET 이 필요합니다.")
    if not cfg.resolved_account_no or not cfg.resolved_account_product_code:
        raise RuntimeError("KIS_ACCOUNT_NO 및 KIS_ACCOUNT_PRODUCT_CODE 가 필요합니다.")
    base = (cfg.kis_mock_base_url or "").rstrip("/")
    if not base.startswith("https://openapivts"):
        raise RuntimeError("모의 주문은 KIS_MOCK_BASE_URL 이 https://openapivts... 인 경우만 허용됩니다.")


def _make_kis_paper_jobs(cfg: Settings, logger: logging.Logger) -> tuple[SchedulerJobs, KISClient]:
    _validate_kis_paper_prereqs(cfg)
    token_service = KISTokenService.from_env(cfg)
    client = KISClient(
        base_url=cfg.kis_mock_base_url.rstrip("/"),
        token_provider=lambda: token_service.get_valid_access_token(),
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
    )
    broker = KisPaperBroker(
        kis_client=client,
        account_no=cfg.resolved_account_no,
        account_product_code=cfg.resolved_account_product_code,
        logger=logging.getLogger("app.brokers.kis_paper"),
    )
    equity_path = Path(cfg.paper_session_state_path)
    tracker = EquityTracker(equity_path, logger=logging.getLogger("app.scheduler.equity_tracker"))
    kill = KillSwitch(rules=_risk_rules_from_config(cfg))
    jobs = SchedulerJobs(
        broker=broker,
        risk_rules=kill.rules,
        kill_switch=kill,
        equity_tracker=tracker,
    )
    logger.info(
        "KIS paper execution enabled (mock host only). symbols=%s interval=%ss",
        cfg.paper_trading_symbols,
        cfg.paper_trading_interval_sec if cfg.paper_trading_loop else "n/a",
    )
    return jobs, client


def _run_single_kis_paper_cycle(cfg: Settings, logger: logging.Logger) -> dict[str, object]:
    jobs, client = _make_kis_paper_jobs(cfg, logger)
    symbols = [s.strip() for s in cfg.paper_trading_symbols.split(",") if s.strip()]
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
    logger.info("KIS paper cycle report: %s", report)
    if report.get("halted"):
        logger.warning("Cycle halted: %s", report.get("reason"))
    else:
        _check_shutdown_on_loss_limit(report, cfg, logger)
    return report


def _run_kis_paper_trading_loop(cfg: Settings, logger: logging.Logger) -> dict[str, object]:
    jobs, client = _make_kis_paper_jobs(cfg, logger)
    symbols = [s.strip() for s in cfg.paper_trading_symbols.split(",") if s.strip()]
    last_report: dict[str, object] = {}
    while True:
        try:
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
            last_report = jobs.run_daily_cycle(universe=universe, kospi_index=kospi, sp500_index=sp500)
            logger.info("[LOOP] KIS paper cycle report: %s", last_report)
        except Exception:
            logger.exception("[LOOP] Cycle failed; backing off and retrying")
            time.sleep(min(60, cfg.paper_trading_interval_sec))
            continue

        if last_report.get("halted") and last_report.get("kill_state") == "SYSTEM_OFF":
            logger.critical("SYSTEM_OFF: total loss guard — stopping loop")
            raise SystemExit(3)

        if not last_report.get("halted"):
            try:
                _check_shutdown_on_loss_limit(last_report, cfg, logger)
            except SystemExit:
                raise
            except Exception:
                logger.exception("Post-cycle check failed")

        time.sleep(cfg.paper_trading_interval_sec)


def _validate_startup_runtime_safety(cfg: Settings, logger: logging.Logger) -> None:
    """
    Startup safety validation:
    - default mode should remain paper
    - live orders require dual-confirm flags + account readiness
    """
    if cfg.trading_mode not in {"paper", "live"}:
        raise RuntimeError("Invalid TRADING_MODE; must be 'paper' or 'live'")

    if cfg.trading_mode == "paper":
        logger.info("Startup safety check: paper mode active (safe default)")
        return

    if not cfg.resolved_live_trading_enabled:
        logger.warning("Startup safety check: live mode selected but LIVE_TRADING is false; live orders will be blocked")
        return

    if not cfg.live_trading_confirm:
        logger.warning("Startup safety check: LIVE_TRADING_CONFIRM is false; live orders will be blocked")
        return

    if not cfg.resolved_account_no or not cfg.resolved_account_product_code:
        raise RuntimeError("Live mode requires KIS_ACCOUNT_NO and KIS_ACCOUNT_PRODUCT_CODE")

    logger.warning("Startup safety check: live mode fully enabled with dual confirmation")


def _check_shutdown_on_loss_limit(report: dict[str, object], cfg: Settings, logger: logging.Logger) -> None:
    cumulative = float(report.get("cumulative_return_pct", 0.0))
    if cumulative <= -abs(cfg.total_loss_limit_pct):
        logger.critical(
            "Auto shutdown triggered: cumulative return %.2f%% breached total loss limit -%.2f%%",
            cumulative,
            abs(cfg.total_loss_limit_pct),
        )
        raise SystemExit(2)


if __name__ == "__main__":
    run()
