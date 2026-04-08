"""
1) 토큰 발급  2) 잔고 API 1회 호출 로 KIS 연결을 검증합니다.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.logging import setup_logging
from scripts.kis_script_utils import (
    build_kis_client,
    issue_token_or_exit,
    load_app_settings,
    resolved_kis_base_url,
)

from app.clients.kis_client import KISClientError
from backend.app.auth.kis_auth import validate_kis_inputs


def main() -> None:
    setup_logging()
    logger = logging.getLogger("scripts.check_kis_connection")
    cfg = load_app_settings()
    base_url = resolved_kis_base_url(cfg)

    logger.info("KIS connection check trading_mode=%s api_base=%s", cfg.trading_mode, base_url)

    acct = cfg.resolved_account_no or ""
    prod = cfg.resolved_account_product_code or ""
    issues = validate_kis_inputs(
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        account_no=acct,
        account_product_code=prod,
        base_url=base_url,
        require_account=True,
    )
    if issues:
        for msg in issues:
            logger.error(msg)
        raise SystemExit(1)

    token = issue_token_or_exit(cfg, base_url=base_url, logger=logger)
    client = build_kis_client(cfg, base_url=base_url, access_token=token)

    try:
        probe = client.get_balance(account_no=acct, account_product_code=prod)
    except KISClientError as exc:
        err = str(exc)
        if "status=404" in err or "HTTP 404" in err:
            logger.error("URL 또는 API 경로 오류 가능성. api_base=%s", base_url)
        elif "401" in err or "403" in err:
            logger.error("인증 오류: 앱키/시크릿·토큰·모의/실전 도메인 일치 여부 확인.")
        else:
            logger.error("잔고 조회 실패: %s", err)
        raise SystemExit(1) from exc

    logger.info("OK — rt_cd=0, 응답 키=%s", sorted(probe.keys()))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
