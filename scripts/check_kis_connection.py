from __future__ import annotations

import logging

from app.clients.kis_client import KISClient, KISClientError
from app.config import get_settings
from app.logging import setup_logging
from backend.app.auth.kis_auth import issue_access_token, validate_kis_inputs


def main() -> None:
    setup_logging()
    logger = logging.getLogger("scripts.check_kis_connection")
    cfg = get_settings()
    base_url = cfg.kis_mock_base_url if cfg.trading_mode == "paper" else cfg.kis_base_url
    account_no = cfg.resolved_account_no
    account_product_code = cfg.resolved_account_product_code

    logger.info("Checking KIS API connectivity")
    logger.info("Mode=%s, Base URL=%s", cfg.trading_mode, base_url)

    issues = validate_kis_inputs(
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        account_no=account_no or "",
        account_product_code=account_product_code or "",
        base_url=base_url,
    )
    if issues:
        for msg in issues:
            logger.error(msg)
        raise SystemExit(1)

    token_result = issue_access_token(
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        base_url=base_url,
        timeout_sec=8,
    )
    if not token_result.ok:
        logger.error("%s (code=%s)", token_result.message, token_result.error_code)
        raise SystemExit(1)

    logger.info("Token issuance passed.")
    client = KISClient(
        base_url=base_url,
        timeout_sec=5,
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        token_provider=lambda: token_result.access_token or "",
    )
    try:
        probe = client.get_balance(account_no=account_no, account_product_code=account_product_code)
    except KISClientError as exc:
        err = str(exc)
        if "status=404" in err:
            logger.error("base url 오류 또는 API 경로 오류입니다. err=%s", err)
        elif "status=401" in err or "status=403" in err:
            logger.error("토큰 발급 실패 또는 권한 오류입니다. 앱키/시크릿을 확인하세요. err=%s", err)
        else:
            logger.error("조회 API 연결 실패: 네트워크/계좌 설정을 확인하세요. err=%s", err)
        raise SystemExit(1) from exc

    logger.info("Connection check passed. Balance response keys=%s", sorted(probe.keys()))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
