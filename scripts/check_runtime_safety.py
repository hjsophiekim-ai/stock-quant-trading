from __future__ import annotations

from app.config import get_settings


def main() -> None:
    cfg = get_settings()
    issues: list[str] = []

    if cfg.trading_mode not in {"paper", "live"}:
        issues.append("TRADING_MODE must be 'paper' or 'live'")

    if cfg.trading_mode == "live":
        if not cfg.resolved_live_trading_enabled:
            issues.append("LIVE_TRADING is not true (live orders will be blocked)")
        if not cfg.live_trading_confirm:
            issues.append("LIVE_TRADING_CONFIRM is not true (dual confirmation missing)")
        if not cfg.live_trading_extra_confirm:
            issues.append("LIVE_TRADING_EXTRA_CONFIRM is not true (extra confirmation missing)")
        if not cfg.resolved_account_no:
            issues.append("KIS_ACCOUNT_NO is missing")
        if not cfg.resolved_account_product_code:
            issues.append("KIS_ACCOUNT_PRODUCT_CODE is missing")

    print("=== Runtime Safety Check ===")
    print(f"mode={cfg.trading_mode}")
    print(f"live_enabled={cfg.resolved_live_trading_enabled}")
    print(f"live_confirm={cfg.live_trading_confirm}")
    print(f"live_extra_confirm={cfg.live_trading_extra_confirm}")
    print(f"account_configured={bool(cfg.resolved_account_no and cfg.resolved_account_product_code)}")
    print(f"dry_run_log={cfg.live_order_dry_run_log}")

    if issues:
        print("\n[BLOCKERS]")
        for issue in issues:
            print(f"- {issue}")
        raise SystemExit(1)

    print("\n[PASS] Runtime safety checks passed.")


if __name__ == "__main__":
    main()
