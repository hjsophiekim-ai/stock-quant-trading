"""Remote Paper API verification (stdout JSON-ish lines). Run: python scripts/verify_paper_api_remote.py"""
from __future__ import annotations

import json
import os
import sys
import time

import httpx

BASE = os.environ.get("BACKEND_URL", "https://stock-quant-backend.onrender.com").rstrip("/")
TOKEN = (os.environ.get("PAPER_VERIFY_JWT") or os.environ.get("BACKEND_JWT") or "").strip()
HDR = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
TIMEOUT = float(os.environ.get("VERIFY_HTTP_TIMEOUT", "60"))


def call(method: str, path: str, **kw) -> tuple[int, object | None, str]:
    url = BASE + path
    try:
        r = httpx.request(method, url, timeout=TIMEOUT, **kw)
        body = r.text
        try:
            return r.status_code, r.json(), body
        except Exception:
            return r.status_code, None, body
    except Exception as e:
        return -1, None, str(e)


def main() -> None:
    print("BASE=", BASE, flush=True)
    print("JWT set=", bool(TOKEN), flush=True)
    print(flush=True)

    # [1]
    for label, method, path in [
        ("health", "GET", "/api/health"),
        ("paper-trading/status", "GET", "/api/paper-trading/status"),
        ("paper-trading/engine/status", "GET", "/api/paper-trading/engine/status"),
        ("runtime-engine/status", "GET", "/api/runtime-engine/status"),
        ("dashboard/runtime-status", "GET", "/api/dashboard/runtime-status"),
    ]:
        sc, j, raw = call(method, path)
        print("===", label, sc, "===", flush=True)
        print(json.dumps(j, ensure_ascii=False, indent=2) if isinstance(j, dict) else raw[:4000], flush=True)
        print(flush=True)

    # [2]
    sc2, j2, _ = call("GET", "/api/broker-accounts/me/status", headers=HDR)
    print("=== broker me/status", sc2, "===", flush=True)
    print(json.dumps(j2, ensure_ascii=False, indent=2) if isinstance(j2, dict) else _[:4000], flush=True)

    sc2b, j2b, _ = call("POST", "/api/broker-accounts/me/test-connection", headers=HDR)
    print("=== broker test-connection", sc2b, "===", flush=True)
    print(json.dumps(j2b, ensure_ascii=False, indent=2) if isinstance(j2b, dict) else _[:4000], flush=True)
    print(flush=True)

    # [3]
    sc3, j3, raw3 = call(
        "POST",
        "/api/paper-trading/start",
        headers=HDR,
        json={"strategy_id": "swing_v1", "link_runtime_engine": True},
    )
    print("=== paper start", sc3, "===", flush=True)
    print(json.dumps(j3, ensure_ascii=False, indent=2) if isinstance(j3, dict) else raw3[:4000], flush=True)
    print(flush=True)

    last_ticks: list[str | None] = []
    for round_i in range(1, 4):
        if round_i > 1:
            time.sleep(22)
        print("--- poll round", round_i, "---", flush=True)
        for p in [
            "/api/paper-trading/status",
            "/api/paper-trading/logs",
            "/api/paper-trading/diagnostics",
            "/api/paper-trading/positions",
            "/api/paper-trading/pnl",
        ]:
            sc, j, _ = call("GET", p, headers=HDR)
            snippet = json.dumps(j, ensure_ascii=False)[:2000] if isinstance(j, dict) else _[:800]
            print(p, sc, snippet, flush=True)

        scdd, jdd, _ = call("GET", "/api/paper-trading/dashboard-data", headers=HDR)
        snippet = json.dumps(jdd, ensure_ascii=False)[:2500] if isinstance(jdd, dict) else _[:800]
        print("/api/paper-trading/dashboard-data", scdd, snippet, flush=True)

        if isinstance(j := call("GET", "/api/paper-trading/status")[1], dict):
            last_ticks.append(str(j.get("last_tick_at")))

    sc6, j6, _ = call("GET", "/api/dashboard/summary", headers=HDR)
    print(flush=True)
    print("=== dashboard/summary", sc6, "===", flush=True)
    print(json.dumps(j6, ensure_ascii=False, indent=2)[:12000] if isinstance(j6, dict) else _[:4000], flush=True)
    print("last_tick_at series:", last_ticks, flush=True)


if __name__ == "__main__":
    main()
    sys.exit(0)
