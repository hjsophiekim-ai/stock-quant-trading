#!/usr/bin/env python3
"""
Paper API 정렬 점검: capabilities / status(domestic|us) / diagnostics 를 한 번에 출력합니다.
스크린샷·stale 백엔드 의심 시 backend_git_sha 와 market_mismatch 를 확인하세요.

  BACKEND_URL=http://127.0.0.1:8000 \\
  PAPER_CHECK_TOKEN='<JWT>' \\
  python scripts/check_paper_frontend_backend_alignment.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def http_json(method: str, url: str, headers: dict[str, str]) -> tuple[int, object]:
    req = urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.URLError as e:
        return 0, {"_error": str(e.reason if hasattr(e, "reason") else e)}
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(body) if body.strip() else {"_http_error": body}
        except json.JSONDecodeError:
            return e.code, {"_raw": body}


def pick_str(d: dict, *keys: str, default: str = "-") -> str:
    for k in keys:
        if k in d and d[k] is not None and str(d[k]).strip() != "":
            return str(d[k])
    return default


def summarize_block(title: str, cap: dict, status_code: int, st: dict) -> None:
    print(f"\n=== {title} (HTTP {status_code}) ===")
    mm = st.get("market_mismatch")
    sid = pick_str(st, "strategy_id")
    pm = pick_str(st, "paper_market")
    reqm = pick_str(st, "requested_market")
    sha = pick_str(st, "backend_git_sha")
    bt = pick_str(st, "backend_build_time")
    fb = st.get("final_betting_enabled_effective")
    print(f"  us_paper_supported (capabilities): {cap.get('us_paper_supported')}")
    print(f"  final_betting_enabled_effective (capabilities): {cap.get('final_betting_enabled_effective')}")
    print(f"  backend_git_sha (status): {sha}")
    print(f"  backend_build_time (status): {bt}")
    print(f"  status.strategy_id: {sid}")
    print(f"  paper_market (status): {pm}")
    print(f"  requested_market (status): {reqm}")
    print(f"  final_betting_enabled_effective (status): {fb}")
    print(f"  market_mismatch: {mm}")
    if mm is True:
        print("  ** market_mismatch: requested market query != session paper_market **")


def main() -> int:
    p = argparse.ArgumentParser(description="Paper trading API alignment check")
    p.add_argument(
        "--base-url",
        default=os.environ.get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/"),
        help="API base (default: env BACKEND_URL or http://127.0.0.1:8000)",
    )
    p.add_argument(
        "--token",
        default=os.environ.get("PAPER_CHECK_TOKEN") or os.environ.get("ACCESS_TOKEN") or "",
        help="Bearer JWT (env PAPER_CHECK_TOKEN or ACCESS_TOKEN)",
    )
    args = p.parse_args()
    base = args.base_url.rstrip("/")
    h: dict[str, str] = {}
    if args.token.strip():
        h["Authorization"] = f"Bearer {args.token.strip()}"

    c_code, cap_raw = http_json("GET", f"{base}/api/paper-trading/capabilities", h)
    cap = cap_raw if isinstance(cap_raw, dict) else {}
    print(f"GET /api/paper-trading/capabilities -> HTTP {c_code}")
    print(json.dumps(cap, ensure_ascii=False, indent=2))

    for market, label in (("domestic", "domestic"), ("us", "us")):
        st_code, st_raw = http_json("GET", f"{base}/api/paper-trading/status?market={market}", h)
        st = st_raw if isinstance(st_raw, dict) else {}
        summarize_block(f"status ?market={label}", cap, st_code, st)

        dg_code, dg_raw = http_json("GET", f"{base}/api/paper-trading/diagnostics?market={market}", h)
        dg = dg_raw if isinstance(dg_raw, dict) else {}
        print(f"\n--- diagnostics ?market={label} (HTTP {dg_code}) ---")
        print(f"  backend_git_sha: {pick_str(dg, 'backend_git_sha')}")
        print(f"  backend_build_time: {pick_str(dg, 'backend_build_time')}")
        print(f"  session_status: {dg.get('session_status')}")
        print(f"  paper_start_diagnostics: {json.dumps(dg.get('paper_start_diagnostics') or {}, ensure_ascii=False)[:500]}")

    # 단일 mismatch 요약
    st_dom_code, st_dom = http_json("GET", f"{base}/api/paper-trading/status?market=domestic", h)
    st_us_code, st_us = http_json("GET", f"{base}/api/paper-trading/status?market=us", h)
    st_d = st_dom if isinstance(st_dom, dict) else {}
    st_u = st_us if isinstance(st_us, dict) else {}
    print("\n=== summary (market_mismatch) ===")
    print(f"  domestic status HTTP: {st_dom_code}, market_mismatch: {st_d.get('market_mismatch')}")
    print(f"  us status HTTP: {st_us_code}, market_mismatch: {st_u.get('market_mismatch')}")
    if c_code != 200:
        print("\n[warn] capabilities HTTP != 200 — check BACKEND_URL / network / token.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
