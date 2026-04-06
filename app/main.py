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

    logger.info("Starting paper trading app")
    logger.info("Trading mode: %s", cfg.trading_mode)
    logger.info("Live trading enabled: %s", cfg.live_trading_enabled)

    health_server = start_health_server(port=8000)
    logger.info("Health endpoint ready: GET http://localhost:8000/health")

    jobs = SchedulerJobs()
    report = jobs.run_daily_cycle()
    logger.info("End-of-day report generated: %s", report)

    health_server.shutdown()
    logger.info("Paper trading app finished")
    return report


if __name__ == "__main__":
    run()
