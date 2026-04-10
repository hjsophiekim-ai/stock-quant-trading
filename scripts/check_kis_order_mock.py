"""
모의투자(openapivts) 주문·체결 관련 KIS API 단계별 진단.

환경변수: KIS_ORDER_SYMBOL (기본 005930)

예:
  python scripts/check_kis_order_mock.py --step all
  python scripts/check_kis_order_mock.py --step psbl
  python scripts/check_kis_order_mock.py --step nccs --execute
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable

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

from app.clients.kis_client import KISClient, KISClientError
from app.clients.kis_contract import is_paper_host
from app.clients.kis_parsers import order_output_brief, psbl_order_summary
from backend.app.auth.kis_auth import validate_kis_inputs


def _step_context(exc: KISClientError) -> dict[str, Any]:
    ctx = getattr(exc, "kis_context", None) or {}
    return {
        "path": ctx.get("path"),
        "tr_id": ctx.get("tr_id"),
        "sanitized_params": ctx.get("params"),
        "http_status": ctx.get("http_status"),
    }


def _print_step_header(name: str) -> None:
    print()
    print("=" * 60)
    print(f" STEP: {name}")
    print("=" * 60)


def _print_ok(name: str, summary: Any) -> None:
    print(f"[OK] {name}")
    if isinstance(summary, dict):
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(summary)


def _print_fail(name: str, exc: KISClientError) -> None:
    print(f"[FAIL] {name}")
    print(f"  메시지: {exc}")
    ctx = _step_context(exc)
    print(f"  path:   {ctx.get('path')!r}")
    print(f"  tr_id:  {ctx.get('tr_id')!r}")
    print("  sanitized_params (로그용 마스킹):")
    print(json.dumps(ctx.get("sanitized_params"), ensure_ascii=False, indent=4))


def run_psbl(client: KISClient, acct: str, prod: str, symbol: str) -> None:
    _print_step_header("inquire_psbl_order (매수가능조회, 시장가)")
    try:
        psbl = client.inquire_psbl_order(
            account_no=acct,
            account_product_code=prod,
            symbol=symbol,
            order_price=None,
            order_div="01",
        )
        _print_ok("inquire_psbl_order", {"summary": psbl_order_summary(psbl)})
    except KISClientError as exc:
        _print_fail("inquire_psbl_order", exc)
        raise


def run_nccs(client: KISClient, acct: str, prod: str) -> None:
    _print_step_header("inquire_nccs (미체결, 전종목)")
    try:
        nccs = client.inquire_nccs(account_no=acct, account_product_code=prod, symbol="")
        _print_ok("inquire_nccs", {"output1_count": len(nccs.get("output1") or [])})
    except KISClientError as exc:
        _print_fail("inquire_nccs", exc)
        raise


def run_ccld(client: KISClient, acct: str, prod: str) -> None:
    _print_step_header("inquire_daily_ccld (일별체결, 전종목)")
    try:
        ccld = client.inquire_daily_ccld(
            account_no=acct,
            account_product_code=prod,
            symbol="",
            ccld_div="00",
        )
        o1 = ccld.get("output1")
        cnt = len(o1) if isinstance(o1, list) else (1 if o1 else 0)
        _print_ok("inquire_daily_ccld", {"output1_count": cnt})
    except KISClientError as exc:
        _print_fail("inquire_daily_ccld", exc)
        raise


def run_place_order(client: KISClient, acct: str, prod: str, symbol: str) -> None:
    _print_step_header("place_order (모의 시장가 매수 1주)")
    try:
        order = client.place_order(
            account_no=acct,
            account_product_code=prod,
            symbol=symbol,
            side="buy",
            quantity=1,
            price=0,
        )
        _print_ok("place_order", order_output_brief(order))
    except KISClientError as exc:
        _print_fail("place_order", exc)
        raise


def main() -> None:
    setup_logging()
    logger = logging.getLogger("scripts.check_kis_order_mock")
    parser = argparse.ArgumentParser(description="KIS mock order pipeline - step-by-step diagnostics")
    parser.add_argument(
        "--step",
        choices=("psbl", "nccs", "ccld", "order", "all"),
        default="all",
        help="실행할 단계 (기본 all)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="--step order 또는 all 일 때만 실제 모의 매수 1주 전송",
    )
    args = parser.parse_args()

    cfg = load_app_settings()
    base_url = resolved_kis_base_url(cfg)

    if not is_paper_host(base_url):
        logger.error("모의 API base(openapivts) 전용입니다. 현재 base=%s", base_url)
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

    print("KIS 모의 주문·체결 진단 (초보자용)")
    print(f"  base_url: {base_url}")
    print(f"  symbol:   {symbol}")
    print(f"  step:     {args.step}")
    print("실패 시 path / tr_id / sanitized_params 를 확인하세요.")

    token = issue_token_or_exit(cfg, base_url=base_url, logger=logger)
    client = build_kis_client(cfg, base_url=base_url, access_token=token)

    steps: list[tuple[str, Callable[[], None]]] = []
    if args.step in ("psbl", "all"):
        steps.append(("psbl", lambda: run_psbl(client, acct, prod, symbol)))
    if args.step in ("nccs", "all"):
        steps.append(("nccs", lambda: run_nccs(client, acct, prod)))
    if args.step in ("ccld", "all"):
        steps.append(("ccld", lambda: run_ccld(client, acct, prod)))
    if args.step == "order":
        if not args.execute:
            print("\n[SKIP] place_order 는 --execute 가 필요합니다.")
            raise SystemExit(0)
        steps.append(("order", lambda: run_place_order(client, acct, prod, symbol)))
    elif args.step == "all" and args.execute:
        steps.append(("order", lambda: run_place_order(client, acct, prod, symbol)))
    elif args.step == "all" and not args.execute:
        print("\n[INFO] place_order 는 건너뜀. 실제 매수까지 보려면: --execute 추가")

    failed = False
    for _key, fn in steps:
        try:
            fn()
        except KISClientError:
            failed = True
            if args.step != "all":
                raise SystemExit(3)

    print()
    if failed:
        print("일부 단계 실패 - 위 FAIL 블록의 path/tr_id/params 를 확인하세요.")
        raise SystemExit(3)
    print("모든 실행 단계 완료.")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
