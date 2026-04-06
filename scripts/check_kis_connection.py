from __future__ import annotations

import logging

from app.clients.kis_client import KISClient, KISClientError
from app.config import get_settings
from app.logging import setup_logging


def main() -> None:
    setup_logging()
    logger = logging.getLogger("scripts.check_kis_connection")
    cfg = get_settings()
    base_url = cfg.kis_mock_base_url if cfg.trading_mode == "paper" else cfg.kis_base_url

    logger.info("Checking KIS API connectivity")
    logger.info("Mode=%s, Base URL=%s", cfg.trading_mode, base_url)

    client = KISClient(base_url=base_url, timeout_sec=5)
    try:
        # Quote endpoint is used as lightweight connectivity probe.
        probe = client.get_quote("005930")
    except KISClientError as exc:
        logger.error("Connection check failed. Please verify app key/secret, network, and endpoint. err=%s", exc)
        return

    logger.info("Connection check passed. Response keys=%s", sorted(probe.keys()))


if __name__ == "__main__":
    main()
