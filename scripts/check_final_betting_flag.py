#!/usr/bin/env python3
"""종가베팅 플래그 — fresh Settings vs 캐시된 get_settings 비교 (네트워크 없음)."""

from __future__ import annotations

import os
import sys


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    from app.config import get_settings, paper_final_betting_diagnostics, paper_final_betting_enabled_fresh

    d = paper_final_betting_diagnostics()
    print("effective", d.get("final_betting_enabled_effective"))
    print("fresh_field", d.get("paper_final_betting_enabled_fresh_settings"))
    print("cached_field", d.get("paper_final_betting_enabled_cached_settings"))
    print("cache_mismatch", d.get("settings_cache_mismatch"))
    print("env_sources", d.get("final_betting_env_sources"))
    ok = bool(d.get("final_betting_enabled_effective"))
    _ = get_settings  # touch cached singleton for visibility
    print("PASS" if ok else "FAIL", "- paper_final_betting_enabled_effective")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
