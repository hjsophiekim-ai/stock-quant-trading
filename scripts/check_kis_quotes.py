"""호환용: check_kis_quote.py 로 이전되었습니다."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.check_kis_quote import main

if __name__ == "__main__":
    main()
