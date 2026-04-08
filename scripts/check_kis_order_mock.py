"""
모의투자(TRADING_MODE=paper + openapivts) 기준:
  매수가능조회 → 미체결 → 일별체결 → (옵션) 시장가 1주 매수

기본은 드라이런만 출력합니다.
실제 모의 주문을 내려면: python scripts/check_kis_order_mock.py --execute

환경변수:
  KIS_ORDER_SYMBOL (기본 005930)
"""
from __future__ import annotations

import argparse
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
from app.clients.kis_contract import is_paper_host
from app.clients.kis_parsers import order_output_brief, psbl_order_summary
from backend.app.auth.kis_auth import validate_kis_inputs


def main() -> None:
    setup_logging()
    logger = logging.getLogger("scripts.check_kis_order_mock")
    parser = argparse.ArgumentParser(description="KIS mock order pipeline check")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="모의 시장가 매수 1주 실제 전송 (그 외 단계는 항상 조회)",
    )
    args = parser.parse_args()

    cfg = load_app_settings()
    base_url = resolved_kis_base_url(cfg)

    if not is_paper_host(base_url):
        logger.error("이 스크립트는 모의 API base(openapivts) 전용입니다. 현재 base=%s", base_url)
        raise SystemExit(2)

    acct = cfg.resolved_account_no or ""
    prod = cfg.resolved_account_product_code or ""
    symbol = os.environ.get("KIS_ORDER_SYMBOL", "005930").strip() or "005930"

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

    report: dict = {"symbol": symbol, "steps": []}

    try:
        psbl = client.inquire_psbl_order(
            account_no=acct,
            account_product_code=prod,
            symbol=symbol,
            order_price=None,
            order_div="01",
        )
        report["steps"].append({"name": "inquire_psbl_order", "summary": psbl_order_summary(psbl)})
    except KISClientError as exc:
        report["steps"].append({"name": "inquire_psbl_order", "error": str(exc)})

    try:
        nccs = client.inquire_nccs(account_no=acct, account_product_code=prod, symbol="")
        report["steps"].append({"name": "inquire_nccs", "output1_count": len(nccs.get("output1") or [])})
    except KISClientError as exc:
        report["steps"].append({"name": "inquire_nccs", "error": str(exc)})

    try:
        ccld = client.inquire_daily_ccld(
            account_no=acct,
            account_product_code=prod,
            symbol="",
            ccld_div="00",
        )
        o1 = ccld.get("output1")
        report["steps"].append(
            {
                "name": "inquire_daily_ccld",
                "output1_count": len(o1) if isinstance(o1, list) else (1 if o1 else 0),
            }
        )
    except KISClientError as exc:
        report["steps"].append({"name": "inquire_daily_ccld", "error": str(exc)})

    if args.execute:
        try:
            order = client.place_order(
                account_no=acct,
                account_product_code=prod,
                symbol=symbol,
                side="buy",
                quantity=1,
                price=0,
            )
            report["steps"].append({"name": "place_order_market_buy_1", "summary": order_output_brief(order)})
        except KISClientError as exc:
            report["steps"].append({"name": "place_order_market_buy_1", "error": str(exc)})
    else:
        report["steps"].append(
            {
                "name": "place_order_market_buy_1",
                "skipped": True,
                "hint": "실제 모의 매수를 내려면 --execute",
            }
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
