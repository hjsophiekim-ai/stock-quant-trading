from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_check_kis_order_mock_help_mentions_steps() -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "check_kis_order_mock.py"
    out = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0
    assert "--step" in out.stdout
    assert "psbl" in out.stdout
