#!/usr/bin/env python3
"""
US KIS 검증 스크립트 (로컬).

사전 조건:
  - SQLite 브로커에 모의투자 자격 저장됨 (앱과 동일)
  - 환경: PYTHONPATH=. 및 프로젝트 루트에서 실행

예:
  set PYTHONPATH=.
  python scripts/verify_us_kis_endpoints.py YOUR_USER_ID

또는 .env 의 백엔드 JWT 없이 브로커만 직접 호출하려면 BrokerSecretService 경로를 코드에 맞게 조정하세요.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    os.environ.setdefault("PYTHONPATH", root)

    from backend.app.api.broker_routes import get_broker_service
    from backend.app.auth.kis_auth import issue_access_token
    from app.clients.kis_client import KISClient
    from app.config import get_settings as app_get_settings
    from backend.app.market.us_session import analyze_us_equity_session
    from backend.app.services.us_symbol_search_service import search_us_symbols_via_kis

    uid = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not uid:
        print("Usage: python scripts/verify_us_kis_endpoints.py <user_id>")
        return 2

    svc = get_broker_service()
    ak, sk, acct, prod, mode = svc.get_plain_credentials(uid)
    api = svc._resolve_kis_api_base(mode)
    tr = issue_access_token(app_key=ak, app_secret=sk, base_url=api, timeout_sec=15)
    if not tr.ok or not tr.access_token:
        print("token_fail:", tr.message)
        return 1
    acfg = app_get_settings()
    client = KISClient(
        base_url=api.rstrip("/"),
        token_provider=lambda: tr.access_token or "",
        app_key=ak,
        app_secret=sk,
        live_execution_unlocked=False,
        kis_min_request_interval_ms=int(acfg.kis_min_request_interval_ms),
        kis_rate_limit_max_retries=int(acfg.kis_rate_limit_max_retries),
        kis_rate_limit_backoff_base_sec=float(acfg.kis_rate_limit_backoff_base_sec),
        kis_rate_limit_backoff_cap_sec=float(acfg.kis_rate_limit_backoff_cap_sec),
    )

    print("--- market=us balance (inquire-balance NASD/USD) ---")
    bal = client.get_overseas_inquire_balance(
        account_no=acct,
        account_product_code=prod,
        ovrs_excg_cd="NASD",
        tr_crcy_cd="USD",
    )
    print("rt_cd", bal.get("rt_cd"), "output1 keys", list((bal.get("output1") or bal.get("output2") or {}))[:3])

    print("--- search NVDA ---")
    print(search_us_symbols_via_kis(client, "NVDA", limit=5))

    print("--- quote NVDA ---")
    q = client.get_overseas_price_quotation(excd="NAS", symb="NVDA", auth="")
    print("output", q.get("output"))

    print("--- minute bars (1m, nrec=5) ---")
    m = client.get_overseas_time_itemchartprice(
        auth="",
        excd="NAS",
        symb="NVDA",
        nmin="1",
        pinc="1",
        next_flag="",
        nrec="5",
        fill="",
        keyb="",
    )
    o1 = m.get("output1")
    print("output1 rows", len(o1) if isinstance(o1, list) else type(o1))

    print("--- US session ---")
    print(analyze_us_equity_session())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
