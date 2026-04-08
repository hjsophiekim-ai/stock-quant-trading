"""
KIS mock 자동매매 파이프라인 핵심 API 점검 스크립트.

- 로그인/JWT 확인
- broker status 확인
- paper start/status/logs 확인
- dashboard/performance/portfolio/risk 상태 확인

주의:
- 실제 주문이 발생할 수 있으므로 테스트 계정(paper)에서만 실행하세요.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any


def _fail(msg: str) -> int:
    print(f"[FAIL] {msg}", file=sys.stderr)
    return 1


def _ok(msg: str, payload: Any | None = None) -> None:
    if payload is None:
        print(f"[ok] {msg}")
        return
    print(f"[ok] {msg}: {payload}")


def main() -> int:
    try:
        import httpx
    except ImportError:
        return _fail("httpx가 필요합니다. pip install httpx")

    p = argparse.ArgumentParser(description="Check KIS mock autotrade pipeline")
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--email", default="")
    p.add_argument("--password", default="")
    p.add_argument("--access-token", default="")
    p.add_argument("--strategy-id", default="swing_v1")
    p.add_argument("--start-paper", action="store_true", help="paper session start까지 수행")
    args = p.parse_args()

    base = args.base_url.rstrip("/")
    headers: dict[str, str] = {}

    with httpx.Client(base_url=base, timeout=httpx.Timeout(25.0, connect=8.0)) as c:
        h = c.get("/api/health")
        if h.status_code != 200:
            return _fail(f"/api/health {h.status_code} {h.text[:200]}")
        _ok("health", h.json())

        rdy = c.get("/api/ready")
        if rdy.status_code != 200:
            return _fail(f"/api/ready {rdy.status_code} {rdy.text[:200]}")
        _ok("ready", rdy.json().get("status"))

        if args.access_token.strip():
            headers["Authorization"] = f"Bearer {args.access_token.strip()}"
        elif args.email.strip() and args.password:
            lr = c.post("/api/auth/login", json={"email": args.email.strip(), "password": args.password})
            if lr.status_code != 200:
                return _fail(f"login 실패 {lr.status_code}: {lr.text[:300]}")
            tok = (lr.json() or {}).get("access_token")
            if not tok:
                return _fail("login 응답에 access_token 없음")
            headers["Authorization"] = f"Bearer {tok}"
            _ok("login")
        else:
            return _fail("--access-token 또는 --email/--password 가 필요합니다")

        me = c.get("/api/auth/me", headers=headers)
        if me.status_code != 200:
            return _fail(f"/api/auth/me 실패 {me.status_code}: {me.text[:200]}")
        _ok("auth/me", (me.json() or {}).get("email"))

        b = c.get("/api/broker-accounts/me/status", headers=headers)
        if b.status_code != 200:
            return _fail(f"/api/broker-accounts/me/status 실패 {b.status_code}: {b.text[:300]}")
        bjs = b.json() or {}
        _ok("broker status", {"ok": bjs.get("ok"), "mode": bjs.get("trading_mode"), "msg": bjs.get("connection_message")})

        if args.start_paper:
            s = c.post("/api/paper-trading/start", headers=headers, json={"strategy_id": args.strategy_id})
            if s.status_code not in (200, 400):
                return _fail(f"paper start 실패 {s.status_code}: {s.text[:300]}")
            _ok("paper start", (s.json() or {}).get("status"))

        st = c.get("/api/paper-trading/status")
        _ok("paper status", st.json() if st.status_code == 200 else st.text[:200])

        logs = c.get("/api/paper-trading/logs")
        if logs.status_code == 200:
            _ok("paper logs count", len((logs.json() or {}).get("items") or []))

        dash = c.get("/api/dashboard/summary", headers=headers)
        if dash.status_code != 200:
            return _fail(f"/api/dashboard/summary 실패 {dash.status_code}: {dash.text[:300]}")
        djs = dash.json() or {}
        _ok("dashboard summary", {"system_status": djs.get("system_status"), "mode": djs.get("mode")})

        perf = c.get("/api/performance/metrics")
        if perf.status_code != 200:
            return _fail(f"/api/performance/metrics 실패 {perf.status_code}: {perf.text[:300]}")
        _ok("performance metrics source", (perf.json() or {}).get("data_source"))

        risk = c.get("/api/risk/status")
        if risk.status_code != 200:
            return _fail(f"/api/risk/status 실패 {risk.status_code}: {risk.text[:200]}")
        _ok("risk status")

        port = c.get("/api/portfolio/summary")
        if port.status_code == 200:
            pjs = port.json() or {}
            _ok("portfolio summary", {"equity": pjs.get("equity"), "positions": pjs.get("position_count")})
        else:
            print(f"[info] portfolio summary 미생성: {port.status_code} (필요 시 /api/portfolio/sync 실행)")

    print("\n점검 완료: KIS mock autotrade pipeline API 경로 응답 정상")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

