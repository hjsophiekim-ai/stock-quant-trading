from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

from app.config import Settings, get_settings
from app.logging import setup_logging
from app.scheduler.jobs import SchedulerJobs


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

    jobs = SchedulerJobs()
    report = jobs.run_daily_cycle()
    logger.info("End-of-day report generated: %s", report)
    _check_shutdown_on_loss_limit(report, cfg, logger)

    health_server.shutdown()
    logger.info("Paper trading app finished")
    return report


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
