"""
잔고(output2 요약) + 보유종목(output1 요약) 조회.
"""
from __future__ import annotations

import json
import logging
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
from app.clients.kis_parsers import balance_cash_summary, positions_brief
from backend.app.auth.kis_auth import validate_kis_inputs


def main() -> None:
    setup_logging()
    logger = logging.getLogger("scripts.check_kis_balance")
    cfg = load_app_settings()
    base_url = resolved_kis_base_url(cfg)
    acct = cfg.resolved_account_no or ""
    prod = cfg.resolved_account_product_code or ""

    issues = validate_kis_inputs(
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        account_no=acct,
        account_product_code=prod,
        base_url=base_url,
        require_account=True,
    )
    if issues:
        for msg in issues:
            logger.error(msg)
        raise SystemExit(1)

    token = issue_token_or_exit(cfg, base_url=base_url, logger=logger)
    client = build_kis_client(cfg, base_url=base_url, access_token=token)

    try:
        raw = client.get_balance(account_no=acct, account_product_code=prod)
    except KISClientError as exc:
        logger.error("잔고 조회 실패: %s", exc)
        raise SystemExit(1) from exc

    out = {
        "trading_mode": cfg.trading_mode,
        "api_base": base_url,
        "cash_summary": balance_cash_summary(raw),
        "positions": positions_brief(raw),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
