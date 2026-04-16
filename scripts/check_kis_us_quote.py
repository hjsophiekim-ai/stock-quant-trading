#!/usr/bin/env python3
"""미국 현재가 HHDFS00000300 — user_id 인자 필요."""

from __future__ import annotations

import os
import sys


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    uid = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    sym = (sys.argv[2] if len(sys.argv) > 2 else "NVDA").strip().upper()
    if not uid:
        print("FAIL usage: python scripts/check_kis_us_quote.py <user_id> [SYMBOL]")
        return 2

    from backend.app.api.broker_routes import get_broker_service
    from backend.app.auth.kis_auth import issue_access_token
    from app.clients.kis_client import KISClient
    from app.config import get_settings as app_get_settings
    from backend.app.services.us_symbol_search_service import search_us_symbols_via_kis

    svc = get_broker_service()
    ak, sk, acct, prod, mode = svc.get_plain_credentials(uid)
    api = svc._resolve_kis_api_base(mode)
    tr = issue_access_token(app_key=ak, app_secret=sk, base_url=api, timeout_sec=15)
    print("market", "us", "path", "quote", "effective_env", "openapivts" in (api or "").lower())
    if not tr.ok or not tr.access_token:
        print("http_status", None, "rt_cd", None, "msg_cd", None, "msg1", tr.message, "FAIL token")
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
    hits = search_us_symbols_via_kis(client, sym, limit=1)
    if not hits:
        print("tr_id", "CTPF1702R", "params", {"pdno": sym}, "http_status", None, "FAIL search miss")
        return 1
    excd = str(hits[0].get("excd") or "NAS")
    path = client.overseas_price_paths.price
    tr_id = client.overseas_tr_ids.price
    try:
        raw = client.get_overseas_price_quotation(excd=excd, symb=sym, auth="")
    except Exception as exc:
        ctx = getattr(exc, "kis_context", {}) or {}
        print(
            "path",
            ctx.get("path") or path,
            "tr_id",
            ctx.get("tr_id") or tr_id,
            "http_status",
            ctx.get("http_status"),
            "rt_cd",
            ctx.get("rt_cd"),
            "msg_cd",
            ctx.get("msg_cd"),
            "msg1",
            ctx.get("msg1"),
            "FAIL",
            str(exc),
        )
        return 1
    print("path", path, "tr_id", tr_id, "params", {"EXCD": excd, "SYMB": sym}, "http_status", 200)
    print("rt_cd", raw.get("rt_cd"), "msg_cd", raw.get("msg_cd"), "msg1", raw.get("msg1"))
    print("PASS" if raw.get("rt_cd") in ("0", 0, "00", None) else "FAIL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
