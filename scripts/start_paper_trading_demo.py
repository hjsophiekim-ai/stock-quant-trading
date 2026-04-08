"""
백엔드가 떠 있는 상태에서 **사용자 Paper 세션**(KIS 모의 틱·주문 루프)을 API로 시작하고 상태를 출력합니다.

`POST /api/paper-trading/start` 는 **JWT + 브로커 paper + 연결 테스트 성공 + openapivts** 가 필요합니다.
로그인 정보 또는 액세스 토큰을 넘기세요.

  python scripts/start_paper_trading_demo.py --email you@example.com --password '***'
  python scripts/start_paper_trading_demo.py --access-token 'eyJ...'

KIS 모의 잔고·손익을 서버 스냅샷으로 보려면 Swagger에서 POST /api/portfolio/sync 를 호출하거나
--sync-portfolio 옵션을 사용하세요. sync 는 **서버 .env 의 KIS** 기준이므로 앱 브로커와 계정을 맞추는 것이 좋습니다.
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    try:
        import httpx
    except ImportError:
        print("httpx required: pip install httpx", file=sys.stderr)
        return 1

    p = argparse.ArgumentParser(description="Start user KIS paper session via POST /api/paper-trading/start")
    p.add_argument("--base-url", default="http://127.0.0.1:8000", help="Backend root URL")
    p.add_argument(
        "--strategy-id",
        default="swing_v1",
        help="Paper strategy id: swing_v1 | bull_focus_v1 | defensive_v1 (not 'live')",
    )
    p.add_argument("--sync-portfolio", action="store_true", help="POST /api/portfolio/sync after start")
    p.add_argument("--email", default="", help="Login email (with --password) for Bearer token")
    p.add_argument("--password", default="", help="Login password")
    p.add_argument("--access-token", default="", help="JWT access token (alternative to --email/--password)")
    args = p.parse_args()

    base = args.base_url.rstrip("/")
    timeout = httpx.Timeout(60.0, connect=10.0)

    headers: dict[str, str] = {}
    if args.access_token.strip():
        headers["Authorization"] = f"Bearer {args.access_token.strip()}"
    elif args.email.strip() and args.password:
        pass  # login inside client block
    else:
        print(
            "[FAIL] JWT가 필요합니다. --access-token 또는 --email / --password 를 지정하세요.",
            file=sys.stderr,
        )
        return 1

    with httpx.Client(base_url=base, timeout=timeout) as client:
        h = client.get("/api/health")
        if h.status_code != 200:
            print(f"[FAIL] health {h.status_code}: {h.text[:200]}", file=sys.stderr)
            return 1
        print("[ok] GET /api/health", h.json())

        if not headers and args.email.strip() and args.password:
            lr = client.post("/api/auth/login", json={"email": args.email.strip(), "password": args.password})
            if lr.status_code != 200:
                print(f"[FAIL] login {lr.status_code}: {lr.text[:300]}", file=sys.stderr)
                return 1
            body = lr.json()
            tok = body.get("access_token")
            if not tok:
                print("[FAIL] login response missing access_token", file=sys.stderr)
                return 1
            headers["Authorization"] = f"Bearer {tok}"
            print("[ok] POST /api/auth/login")

        r = client.post("/api/paper-trading/start", json={"strategy_id": args.strategy_id}, headers=headers)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code == 400:
            detail = str(body.get("detail") or "")
            if "already running" in detail.lower():
                print("[info] paper trading already running — continuing")
            else:
                print(f"[FAIL] paper start {r.status_code}: {detail}", file=sys.stderr)
                return 1
        elif r.status_code != 200:
            print(f"[FAIL] paper start {r.status_code}: {r.text[:500]}", file=sys.stderr)
            return 1
        else:
            print("[ok] POST /api/paper-trading/start", json.dumps(body, ensure_ascii=False)[:500])

        st = client.get("/api/paper-trading/status")
        print("[ok] GET /api/paper-trading/status", st.json() if st.status_code == 200 else st.text[:300])

        pnl = client.get("/api/paper-trading/pnl")
        print("[ok] GET /api/paper-trading/pnl", pnl.json() if pnl.status_code == 200 else pnl.text[:300])

        logs = client.get("/api/paper-trading/logs")
        print("[ok] GET /api/paper-trading/logs items=", len((logs.json() or {}).get("items") or []))

        if args.sync_portfolio:
            s = client.post("/api/portfolio/sync")
            print(
                "[ok] POST /api/portfolio/sync",
                s.status_code,
                (s.json() if s.headers.get("content-type", "").startswith("application/json") else s.text)[:800],
            )

    print()
    print("다음 확인:")
    print(f"  - Swagger  {base}/docs")
    print(f"  - 대시보드  {base}/api/dashboard/summary")
    print("  - Paper 세션: GET /api/paper-trading/status | positions | pnl | logs")
    print("  - (선택) 스냅샷: POST /api/portfolio/sync 후 GET /api/portfolio/summary — .env 계정과 앱 브로커 일치 권장")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
