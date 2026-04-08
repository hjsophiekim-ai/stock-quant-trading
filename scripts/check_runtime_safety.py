"""
런타임 안전 설정 점검. 실거래(live) 주문은 기본·설계상 금지이며, 다중 플래그 없이는 실행되지 않습니다.

  python scripts/check_runtime_safety.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure repo root on path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)


def main() -> None:
    from backend.app.core.config import get_backend_settings, is_live_order_execution_configured

    cfg = get_backend_settings()
    mode = (cfg.trading_mode or "paper").strip().lower()
    live_armed = is_live_order_execution_configured(cfg)

    issues: list[str] = []
    warnings: list[str] = []

    print("=== Runtime Safety Check ===")
    print()
    print("*** 실거래(live) 주문 경로는 기본 잠금입니다. ***")
    print("    TRADING_MODE=live + LIVE_TRADING* + LIVE_TRADING_CONFIRM + LIVE_TRADING_EXTRA_CONFIRM")
    print("    가 모두 맞아야만 실행 가능으로 표시됩니다. 초보자는 paper 만 사용하세요.")
    print()

    print(f"TRADING_MODE={cfg.trading_mode!r}")
    print(f"LIVE_TRADING={cfg.live_trading} LIVE_TRADING_ENABLED={cfg.live_trading_enabled}")
    print(f"LIVE_TRADING_CONFIRM={cfg.live_trading_confirm} LIVE_TRADING_EXTRA_CONFIRM={cfg.live_trading_extra_confirm}")
    print(f"live_order_execution_configured={live_armed}")
    print(f"KIS keys present={bool(cfg.kis_app_key and cfg.kis_app_secret)}")
    print(f"APP_SECRET_KEY set={bool(cfg.app_secret_key and len(cfg.app_secret_key) >= 8)}")

    if not cfg.app_secret_key or len(cfg.app_secret_key) < 8:
        warnings.append("APP_SECRET_KEY is short or empty - set a strong secret in .env for JWT/broker crypto")

    if mode not in {"paper", "live"}:
        issues.append("TRADING_MODE must be 'paper' or 'live'")

    if mode == "live":
        if not live_armed:
            issues.append(
                "TRADING_MODE=live but live execution is NOT fully armed - 실주문은 차단됩니다 "
                "(의도된 안전 동작)."
            )
        if not (cfg.kis_app_key and cfg.kis_app_secret):
            issues.append("Live mode requires KIS_APP_KEY / KIS_APP_SECRET in .env")

    if mode == "paper" and live_armed:
        warnings.append("paper mode but live_execution_configured=True - 설정을 다시 확인하세요")

    if warnings:
        print("\n[WARNINGS]")
        for w in warnings:
            print(f"- {w}")

    if issues:
        print("\n[BLOCKERS]")
        for item in issues:
            print(f"- {item}")
        raise SystemExit(1)

    print("\n[PASS] Runtime safety OK for current configuration.")
    if mode == "paper":
        print("        모의(paper) 기준으로 백엔드 기동 가능.")


if __name__ == "__main__":
    main()
