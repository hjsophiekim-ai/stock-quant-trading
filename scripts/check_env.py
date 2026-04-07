from __future__ import annotations

import importlib.util
import os
import shutil
import sys


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def main() -> None:
    issues: list[str] = []
    warnings: list[str] = []

    print("=== Environment Check ===")
    print(f"python={sys.version.split()[0]}")

    if sys.version_info < (3, 11):
        issues.append("Python 3.11+ is required")

    for cmd in ("npm",):
        if shutil.which(cmd) is None:
            issues.append(f"'{cmd}' is not installed or not in PATH")

    required_modules = [
        "fastapi",
        "uvicorn",
        "pytest",
        "httpx",
        "pydantic",
        "pydantic_settings",
        "sqlalchemy",
        "redis",
    ]
    for mod in required_modules:
        if not _has_module(mod):
            issues.append(f"Python module missing: {mod}")

    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(env_path):
        warnings.append(".env not found at repository root (paper mode defaults may still run)")

    print("\n[Checks]")
    print(f"- python_3_11_plus: {sys.version_info >= (3, 11)}")
    print(f"- npm_available: {shutil.which('npm') is not None}")
    print(f"- root_env_file: {os.path.exists(env_path)}")

    if warnings:
        print("\n[WARNINGS]")
        for w in warnings:
            print(f"- {w}")

    if issues:
        print("\n[BLOCKERS]")
        for item in issues:
            print(f"- {item}")
        raise SystemExit(1)

    print("\n[PASS] Environment looks ready.")


if __name__ == "__main__":
    main()
