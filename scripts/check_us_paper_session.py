#!/usr/bin/env python3
"""US Paper capabilities + (선택) 로컬 백엔드 status — HTTP만."""

from __future__ import annotations

import json
import os
import sys
import urllib.request


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("BACKEND_URL") or "http://127.0.0.1:8000").rstrip("/")
    cap_url = f"{base}/api/paper-trading/capabilities"
    print("path", cap_url)
    try:
        with urllib.request.urlopen(cap_url, timeout=10) as r:
            body = r.read().decode("utf-8", errors="replace")
            print("http_status", r.status)
            dj = json.loads(body)
            print("json", json.dumps(dj, ensure_ascii=False)[:2000])
            ok = dj.get("us_paper_supported") is not False
            print("PASS" if ok else "FAIL", "us_paper_supported")
            return 0 if ok else 1
    except Exception as exc:
        print("http_status", None, "FAIL", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
