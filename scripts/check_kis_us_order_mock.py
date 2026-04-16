#!/usr/bin/env python3
"""
미국 모의 주문 경로 점검 — 기본은 주문을 보내지 않고 브로커·TR 메타만 출력.
실제 주문을내려면 `CONFIRM_US_MOCK_ORDER=1` 및 추가 인자가 필요(실수 방지).
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    uid = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not uid:
        print("FAIL usage: python scripts/check_kis_us_order_mock.py <user_id>")
        return 2

    from backend.app.api.broker_routes import get_broker_service
    from backend.app.auth.kis_auth import issue_access_token
    from app.clients.kis_client import KISClient
    from app.config import get_settings as app_get_settings
    from app.brokers.kis_us_paper_broker import KisUsPaperBroker
    from app.orders.models import OrderRequest, OrderStatus

    svc = get_broker_service()
    ak, sk, acct, prod, mode = svc.get_plain_credentials(uid)
    api = svc._resolve_kis_api_base(mode)
    tr = issue_access_token(app_key=ak, app_secret=sk, base_url=api, timeout_sec=15)
    print("market", "us", "path_meta", "overseas-stock order", "effective_env", "openapivts" in (api or "").lower())
    if not tr.ok or not tr.access_token:
        print("FAIL token", tr.message)
        return 1
    if "openapivts" not in (api or "").lower():
        print("FAIL not mock host")
        return 1
    acfg = app_get_settings()
    client = KISClient(
        base_url=api.rstrip("/"),
        timeout_sec=10,
        token_provider=lambda: tr.access_token or "",
        app_key=ak,
        app_secret=sk,
        live_execution_unlocked=False,
        kis_min_request_interval_ms=int(acfg.kis_min_request_interval_ms),
        kis_rate_limit_max_retries=int(acfg.kis_rate_limit_max_retries),
        kis_rate_limit_backoff_base_sec=float(acfg.kis_rate_limit_backoff_base_sec),
        kis_rate_limit_backoff_cap_sec=float(acfg.kis_rate_limit_backoff_cap_sec),
    )
    br = KisUsPaperBroker(
        kis_client=client,
        account_no=acct,
        account_product_code=prod,
    )
    if os.environ.get("CONFIRM_US_MOCK_ORDER") != "1":
        print("SKIP live order — set CONFIRM_US_MOCK_ORDER=1 to send one NVDA limit buy qty=1 price=1.00 (paper only)")
        print("PASS dry_run")
        return 0
    res = br.place_order(
        OrderRequest(symbol="NVDA", side="buy", quantity=1, price=1.0, stop_loss_pct=None, strategy_id="diag"),
    )
    print("accepted", res.accepted, "status", res.status, "msg", res.message)
    print("PASS" if res.status != OrderStatus.FAILED or res.accepted else "FAIL")
    return 0 if res.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
