from __future__ import annotations

import logging

from app.clients.kis_client import KISClient, KISClientError
from app.config import get_settings
from app.logging import setup_logging


def main() -> None:
    setup_logging()
    logger = logging.getLogger("scripts.check_kis_quotes")
    cfg = get_settings()
    base_url = cfg.kis_mock_base_url if cfg.trading_mode == "paper" else cfg.kis_base_url
    symbol = "005930"

    logger.info("Checking latest quote from KIS")
    logger.info("Mode=%s, Symbol=%s", cfg.trading_mode, symbol)

    client = KISClient(base_url=base_url, timeout_sec=5)
    try:
        quote = client.get_quote(symbol)
    except KISClientError as exc:
        logger.error("Quote check failed. Please verify token, endpoint, and market session. err=%s", exc)
        return

    logger.info("Quote response received: %s", quote)


if __name__ == "__main__":
    main()
