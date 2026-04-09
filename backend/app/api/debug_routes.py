"""운영 진단용(경로·쓰기 가능 여부). 민감값은 노출하지 않습니다."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from backend.app.core.config import get_backend_settings
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
