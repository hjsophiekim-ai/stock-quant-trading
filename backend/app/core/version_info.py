"""배포·진단용: git SHA / 빌드 시각 (환경변수 우선, 로컬은 git rev-parse)."""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path


def _repo_root() -> Path:
    # backend/app/core/version_info.py -> parents[3] = 저장소 루트
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def get_backend_git_sha() -> str:
    for key in ("GIT_COMMIT_SHA", "RENDER_GIT_COMMIT", "COMMIT_SHA", "SOURCE_VERSION"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_repo_root()),
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
        )
        return str(out or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


@lru_cache(maxsize=1)
def get_backend_build_time() -> str:
    return (
        (os.environ.get("BUILD_TIME") or "").strip()
        or (os.environ.get("RENDER_GIT_COMMIT_TIMESTAMP") or "").strip()
    )


def get_backend_version_payload(*, app_version: str = "0.1.0") -> dict[str, str]:
    return {
        "app_version": app_version,
        "git_sha": get_backend_git_sha(),
        "build_time": get_backend_build_time(),
    }
