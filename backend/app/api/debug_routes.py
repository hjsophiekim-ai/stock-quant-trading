"""운영 진단용(경로·쓰기 가능 여부). 민감값은 노출하지 않습니다."""

from __future__ import annotations

import logging
import sys

from fastapi import APIRouter, Header, HTTPException, status

from app.clients.kis_client import KISClientError, sanitize_kis_params_for_log
from backend.app.api.auth_routes import get_current_user_from_auth_header
from backend.app.api.broker_routes import get_broker_service
from backend.app.clients.kis_client import build_kis_client_for_paper_user
from backend.app.core.config import get_backend_settings
from backend.app.core.version_info import get_backend_version_payload
from backend.app.core.storage_paths import (
    directory_is_writable,
    get_resolved_storage_paths,
    path_is_writable_file_location,
    sqlite_trading_db_file_path,
)

router = APIRouter(prefix="/debug", tags=["debug"])
_logger = logging.getLogger("backend.app.api.debug_routes")


@router.get("/storage-paths")
def storage_paths() -> dict[str, object]:
    """users / broker DB / trading DB(SQLite) 경로와 쓰기 가능 여부."""
    cfg = get_backend_settings()
    paths = get_resolved_storage_paths()
    trading_sqlite = sqlite_trading_db_file_path(cfg.database_url)

    def _info(p, label: str) -> dict[str, object]:
        pp = p
        return {
            "label": label,
            "path": str(pp),
            "writable": path_is_writable_file_location(pp),
            "exists": pp.is_file(),
        }

    out: dict[str, object] = {
        "backend_data_dir": str(paths.backend_data_dir),
        "backend_data_dir_writable": directory_is_writable(paths.backend_data_dir),
        "auth_users": _info(paths.auth_users_path, "users.json"),
        "auth_revoked_tokens": _info(paths.auth_revoked_tokens_path, "revoked_refresh_tokens.json"),
        "broker_accounts_db": _info(paths.broker_accounts_db_path, "broker_accounts.db"),
        "database_url_mode": "sqlite" if trading_sqlite is not None else "non_sqlite",
        "trading_db": (
            _info(trading_sqlite, "trading.db")
            if trading_sqlite is not None
            else {
                "label": "DATABASE_URL",
                "path": "(non_sqlite_or_memory)",
                "writable": False,
                "exists": False,
                "note": "SQLite 파일이 아니면 경로 점검은 생략됩니다.",
            }
        ),
        "environment": (cfg.app_env or "local"),
    }
    _logger.debug("storage-paths diagnostic requested")
    return out


def _debug_user(authorization: str | None):
    try:
        return get_current_user_from_auth_header(authorization)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


def _balance_params(account_no: str, product_code: str) -> dict[str, str]:
    return {
        "CANO": account_no,
        "ACNT_PRDT_CD": product_code,
        "AFHR_FLPR_YN": "N",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01",
    }


@router.get("/runtime-info")
def runtime_info() -> dict[str, object]:
    import app.brokers.kis_paper_broker as kis_paper_broker_mod
    import app.clients.kis_client as kis_client_mod
    import backend.app.engine.user_paper_loop as user_paper_loop_mod

    ver = get_backend_version_payload()
    return {
        "backend_git_sha": ver.get("git_sha", ""),
        "backend_build_time": ver.get("build_time", ""),
        "backend_app_version": ver.get("app_version", ""),
        "python_executable": sys.executable,
        "module_files": {
            "app.clients.kis_client": getattr(kis_client_mod, "__file__", ""),
            "backend.app.engine.user_paper_loop": getattr(user_paper_loop_mod, "__file__", ""),
            "app.brokers.kis_paper_broker": getattr(kis_paper_broker_mod, "__file__", ""),
        },
    }


@router.get("/kis-balance-check")
def kis_balance_check(authorization: str | None = Header(default=None)) -> dict[str, object]:
    user = _debug_user(authorization)
    svc = get_broker_service()
    app_key, app_secret, account_no, product_code, trading_mode = svc.get_plain_credentials(user.id)
    api_base = svc._resolve_kis_api_base(trading_mode)
    if "openapivts" not in (api_base or ""):
        return {
            "ok": False,
            "failure_kind": "invalid_mode",
            "error": "paper 모드(openapivts)만 진단 가능합니다.",
            "trading_mode": trading_mode,
            "api_base": api_base,
        }

    tok = svc.ensure_cached_token_for_paper_start(user.id)
    if not tok.ok or not tok.access_token:
        return {
            "ok": False,
            "failure_kind": "token_not_ready",
            "error": tok.message,
            "token_error_code": tok.token_error_code,
            "token_cache_source": tok.token_cache_source,
        }

    client = build_kis_client_for_paper_user(
        base_url=api_base,
        access_token=tok.access_token,
        app_key=app_key,
        app_secret=app_secret,
    )
    req_params = _balance_params(account_no, product_code)
    tr_id = client._resolve_tr_id(paper_tr_id=client.tr_ids.balance_paper, live_tr_id=client.tr_ids.balance_live)
    path = client.endpoints.get_balance
    sanitized = sanitize_kis_params_for_log(req_params)
    try:
        payload = client.get_balance(account_no=account_no, account_product_code=product_code)
        out = payload.get("output2")
        sample = out[0] if isinstance(out, list) and out else out if isinstance(out, dict) else {}
        return {
            "ok": True,
            "path": path,
            "tr_id": tr_id,
            "sanitized_params": sanitized,
            "summary": {
                "ord_psbl_cash": sample.get("ord_psbl_cash") if isinstance(sample, dict) else None,
                "dnca_tot_amt": sample.get("dnca_tot_amt") if isinstance(sample, dict) else None,
                "tot_evlu_amt": sample.get("tot_evlu_amt") if isinstance(sample, dict) else None,
            },
        }
    except KISClientError as exc:
        ctx = getattr(exc, "kis_context", {}) or {}
        return {
            "ok": False,
            "failure_kind": "kis_error",
            "error": str(exc),
            "path": ctx.get("path") or path,
            "tr_id": ctx.get("tr_id") or tr_id,
            "sanitized_params": ctx.get("params") or sanitized,
            "http_status": ctx.get("http_status"),
        }
