"""
국내주식 현재가(inquire-price) 조회. 계좌 없이 동작.
종목: 환경변수 KIS_QUOTE_SYMBOL (기본 005930)
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.logging import setup_logging
from scripts.kis_script_utils import (
    build_kis_client,
    issue_token_or_exit,
    load_app_settings,
    resolved_kis_base_url,
)

from app.clients.kis_client import KISClientError
from app.clients.kis_parsers import quote_from_price_payload


def main() -> None:
    setup_logging()
    logger = logging.getLogger("scripts.check_kis_quote")
    cfg = load_app_settings()
    base_url = resolved_kis_base_url(cfg)
    symbol = os.environ.get("KIS_QUOTE_SYMBOL", "005930").strip() or "005930"

    token = issue_token_or_exit(cfg, base_url=base_url, logger=logger)
    client = build_kis_client(cfg, base_url=base_url, access_token=token)

    try:
        raw = client.get_quote(symbol)
    except KISClientError as exc:
        logger.error("시세 조회 실패 symbol=%s err=%s", symbol, exc)
        raise SystemExit(1) from exc

    print(
        json.dumps(
            {
                "symbol": symbol,
                "trading_mode": cfg.trading_mode,
                "api_base": base_url,
                "quote": quote_from_price_payload(raw),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    raise SystemExit(0)


if __name__ == "__main__":
    main()
