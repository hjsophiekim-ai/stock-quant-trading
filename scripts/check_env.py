"""
저장소 루트에서 실행: Python 버전, 필수 패키지, .env, KIS 모의 필수 변수 점검.

  python scripts/check_env.py
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def main() -> None:
    root = _root()
    os.chdir(root)
    rs = str(root)
    if rs not in sys.path:
        sys.path.insert(0, rs)
    issues: list[str] = []
    warnings: list[str] = []

    print("=== Environment Check (beginner / paper mock) ===")
    print(f"repo_root={os.getcwd()}")
    print(f"python={sys.version.split()[0]}")

    if sys.version_info < (3, 11):
        issues.append("Python 3.11+ is required (see pyproject.toml)")

    if shutil.which("npm") is None:
        warnings.append("'npm' not in PATH (only needed for mobile/desktop apps; backend-only OK)")

    required_modules = [
        "fastapi",
        "uvicorn",
        "httpx",
        "pydantic",
        "pydantic_settings",
        "email_validator",
        "dotenv",
        "jose",
        "passlib",
        "bcrypt",
        "sqlalchemy",
        "cryptography",
        "pandas",
        "requests",
    ]
    for mod in required_modules:
        if not _has_module(mod):
            issues.append(f"Python module missing: {mod}  →  pip install -e .")

    env_path = Path(".env")
    env_paper = Path(".env.paper")
    if not env_path.is_file():
        warnings.append(".env missing → copy env.paper.example to .env.paper, edit, then copy to .env")
    if env_paper.is_file() and not env_path.is_file():
        warnings.append(".env.paper exists but .env does not → cp .env.paper .env  (Unix) / copy .env.paper .env  (Windows)")

    venv_py = Path(".venv/bin/python")
    venv_win = Path(".venv/Scripts/python.exe")
    if not venv_py.is_file() and not venv_win.is_file():
        warnings.append("no .venv detected → python -m venv .venv && activate && pip install -e .")

    # When .env exists, verify KIS mock essentials (order engine / portfolio sync)
    if env_path.is_file():
        try:
            from dotenv import dotenv_values

            vals = dotenv_values(env_path)
        except Exception:
            vals = {}
        need = ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT_NO", "KIS_ACCOUNT_PRODUCT_CODE")
        for k in need:
            v = (vals.get(k) or "").strip()
            if not v:
                warnings.append(f"{k} empty in .env (needed for KIS mock token / account APIs)")

    print("\n[Checks]")
    print(f"- python_3_11_plus: {sys.version_info >= (3, 11)}")
    print(f"- dotenv_file: {env_path.is_file()}")
    print(f"- venv_present: {venv_py.is_file() or venv_win.is_file()}")
    print(f"- npm_in_path: {shutil.which('npm') is not None} (optional)")

    try:
        from backend.app.core.config import get_backend_settings

        _ = get_backend_settings()
        print("- backend_settings_import: True")
    except Exception as exc:
        issues.append(f"backend import failed: {exc}")

    if warnings:
        print("\n[WARNINGS]")
        for w in warnings:
            print(f"- {w}")

    if issues:
        print("\n[BLOCKERS]")
        for item in issues:
            print(f"- {item}")
        raise SystemExit(1)

    print("\n[PASS] Environment looks ready for backend (paper mock).")
    print("Next: python scripts/check_runtime_safety.py")
    print("Then: scripts/run_backend.bat  or  bash scripts/run_backend.sh")


if __name__ == "__main__":
    main()
