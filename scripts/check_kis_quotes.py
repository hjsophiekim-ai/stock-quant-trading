from __future__ import annotations

import logging

from app.clients.kis_client import KISClient, KISClientError
from app.config import get_settings
from app.logging import setup_logging
from backend.app.auth.kis_auth import issue_access_token, validate_kis_inputs


def main() -> None:
    setup_logging()
    logger = logging.getLogger("scripts.check_kis_quotes")
    cfg = get_settings()
    base_url = cfg.kis_mock_base_url if cfg.trading_mode == "paper" else cfg.kis_base_url
    symbol = "005930"

    logger.info("Checking latest quote from KIS")
    logger.info("Mode=%s, Symbol=%s", cfg.trading_mode, symbol)

    issues = validate_kis_inputs(
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        account_no=cfg.resolved_account_no or "00000000",
        account_product_code=cfg.resolved_account_product_code or "01",
        base_url=base_url,
    )
    issues = [x for x in issues if "계좌" not in x]
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

    client = KISClient(
        base_url=base_url,
        timeout_sec=5,
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        token_provider=lambda: token_result.access_token or "",
    )
    try:
        quote = client.get_quote(symbol)
    except KISClientError as exc:
        err = str(exc)
        if "status=404" in err:
            logger.error("base url 오류 또는 시세 API 경로 오류입니다. err=%s", err)
        elif "status=401" in err or "status=403" in err:
            logger.error("토큰 발급 실패 또는 인증 오류입니다. err=%s", err)
        else:
            logger.error("시세 조회 실패: 네트워크/장운영시간/종목코드를 확인하세요. err=%s", err)
        raise SystemExit(1) from exc

    logger.info("Quote response received: %s", quote)


if __name__ == "__main__":
    main()
