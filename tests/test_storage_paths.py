from __future__ import annotations

from pathlib import Path

from backend.app.core.config import BackendSettings
from backend.app.core.storage_paths import (
    directory_is_writable,
    path_is_writable_file_location,
    resolve_storage_paths,
    sqlite_trading_db_file_path,
)


def test_resolve_storage_paths_unifies_under_backend_data_dir(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    s = BackendSettings.model_construct(
        backend_data_dir=str(root / "persist"),
        auth_users_path="",
        auth_revoked_tokens_path="",
        broker_accounts_db_path="",
        database_url="sqlite:///./trading.db",
    )
    p = resolve_storage_paths(s, cwd=tmp_path)
    assert p.backend_data_dir == (tmp_path / "root" / "persist").resolve()
    assert p.auth_users_path == p.backend_data_dir / "users.json"
    assert p.broker_accounts_db_path == p.backend_data_dir / "broker_accounts.db"


def test_sqlite_trading_db_relative_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    p = sqlite_trading_db_file_path("sqlite:///./trading.db")
    assert p == (tmp_path / "trading.db").resolve()


def test_directory_and_file_writable_tmp(tmp_path: Path) -> None:
    d = tmp_path / "d"
    assert directory_is_writable(d) is True
    f = tmp_path / "d" / "f.db"
    assert path_is_writable_file_location(f) is True
