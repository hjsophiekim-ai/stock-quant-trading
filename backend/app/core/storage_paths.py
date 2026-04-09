"""
Auth·브로커·SQLite 등 파일 경로를 설정값으로 일관 해석합니다.
상대 경로는 프로세스 cwd 기준으로 절대 경로로 고정합니다(배포 시 BACKEND_DATA_DIR 로 디스크 고정 권장).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy.engine.url import make_url

from backend.app.core.config import BackendSettings, get_backend_settings


def _resolve_under_cwd(p: Path, *, cwd: Path | None = None) -> Path:
    base = cwd or Path.cwd()
    if p.is_absolute():
        return p.expanduser().resolve()
    return (base / p).expanduser().resolve()


def sqlite_trading_db_file_path(database_url: str, *, cwd: Path | None = None) -> Path | None:
    """DATABASE_URL 이 SQLite 파일일 때 경로. :memory:·PostgreSQL 등은 None."""
    try:
        u = make_url(database_url)
    except Exception:
        return None
    if u.get_dialect().name != "sqlite":
        return None
    db = u.database
    if not db or db == ":memory:":
        return None
    p = Path(db)
    base = cwd or Path.cwd()
    if not p.is_absolute():
        return (base / p).resolve()
    return p.resolve()


@dataclass(frozen=True)
class ResolvedStoragePaths:
    backend_data_dir: Path
    auth_users_path: Path
    auth_revoked_tokens_path: Path
    broker_accounts_db_path: Path


def resolve_storage_paths(settings: BackendSettings, *, cwd: Path | None = None) -> ResolvedStoragePaths:
    base = cwd or Path.cwd()
    raw_data = (settings.backend_data_dir or "backend_data").strip()
    data_dir = _resolve_under_cwd(Path(raw_data), cwd=base)

    def pick(override: str, default_under_data: str) -> Path:
        o = (override or "").strip()
        if o:
            return _resolve_under_cwd(Path(o), cwd=base)
        return _resolve_under_cwd(data_dir / default_under_data, cwd=base)

    return ResolvedStoragePaths(
        backend_data_dir=data_dir,
        auth_users_path=pick(settings.auth_users_path, "users.json"),
        auth_revoked_tokens_path=pick(settings.auth_revoked_tokens_path, "revoked_refresh_tokens.json"),
        broker_accounts_db_path=pick(settings.broker_accounts_db_path, "broker_accounts.db"),
    )


def path_is_writable_file_location(path: Path) -> bool:
    """파일이 없어도 부모 디렉터리에 쓸 수 있으면 True."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        probe = path.parent / ".write_probe_storage_paths"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def directory_is_writable(path: Path) -> bool:
    """디렉터리에 임시 파일을 만들 수 있으면 True."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe_dir"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


@lru_cache(maxsize=1)
def get_resolved_storage_paths() -> ResolvedStoragePaths:
    return resolve_storage_paths(get_backend_settings())


def clear_resolved_storage_paths_cache() -> None:
    get_resolved_storage_paths.cache_clear()
