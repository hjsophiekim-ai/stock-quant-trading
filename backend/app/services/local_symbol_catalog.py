"""
앱에 포함된 국내 유동성 종목 목록(심볼+한글명)으로만 검색합니다.
한국투자증권 공식 '종목검색' Open API와는 무관합니다.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    # backend/app/services/local_symbol_catalog.py -> parents[3] == repo root
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def _load_rows() -> tuple[dict[str, Any], ...]:
    path = _repo_root() / "data" / "domestic_liquid_symbols.json"
    if not path.is_file():
        return ()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return ()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol", "")).strip()
        name = str(item.get("name_kr", "")).strip()
        if len(sym) == 6 and sym.isdigit() and name and sym not in seen:
            out.append({"symbol": sym, "name_kr": name})
            seen.add(sym)
    return tuple(out)


def search_by_name_kr(*, query: str, limit: int = 40) -> list[dict[str, Any]]:
    """
    종목명(한글) 부분 일치만 사용. (앱 내장 목록, KIS 공식 검색 아님)
    """
    q = (query or "").strip()
    if len(q) < 1:
        return []
    rows = list(_load_rows())
    if not rows:
        return []
    q_lower = q.lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    for r in rows:
        name = str(r.get("name_kr") or "")
        if not name:
            continue
        nl = name.lower()
        if q in name or (q_lower and q_lower in nl):
            score = 50
            if name.startswith(q):
                score = 100
            elif q_lower and nl.startswith(q_lower[: min(len(q_lower), 4)]):
                score = 75
            scored.append((score, r))
    scored.sort(key=lambda x: (-x[0], x[1]["symbol"]))
    return [r for _, r in scored[: max(1, min(limit, 200))]]


def search_by_symbol_code(*, query: str, limit: int = 40) -> list[dict[str, Any]]:
    """
    6자리 종목코드만 대상: 숫자만 추출해 접두·부분 일치. (앱 내장 목록)
    """
    q_raw = (query or "").strip()
    q_digits = re.sub(r"\D", "", q_raw)
    if not q_digits:
        return []
    rows = list(_load_rows())
    if not rows:
        return []
    scored: list[tuple[int, dict[str, Any]]] = []
    for r in rows:
        sym = r["symbol"]
        score = 0
        if sym == q_digits[:6] and len(q_digits) >= 6:
            score = 100
        elif len(q_digits) <= 6 and sym.startswith(q_digits):
            score = 80
        elif q_digits in sym:
            score = 60
        if score <= 0:
            continue
        scored.append((score, r))
    scored.sort(key=lambda x: (-x[0], x[1]["symbol"]))
    return [r for _, r in scored[: max(1, min(limit, 200))]]


def search_local_liquid_symbols(*, query: str, limit: int = 40) -> list[dict[str, Any]]:
    """
    하위 호환: 종목코드·종목명 혼합 검색 (신규 코드에서는 search_by_name_kr / search_by_symbol_code 사용 권장).
    """
    q = (query or "").strip()
    if not q:
        return []
    rows = list(_load_rows())
    if not rows:
        return []
    q_lower = q.lower()
    q_digits = re.sub(r"\D", "", q)
    scored: list[tuple[int, dict[str, Any]]] = []
    for r in rows:
        sym = r["symbol"]
        name = r.get("name_kr") or ""
        score = 0
        if q_digits and q_digits in sym:
            score += 80
        elif sym.startswith(q_digits) if q_digits else False:
            score += 70
        if q_lower in name.lower():
            score += 60
        if q in sym:
            score += 50
        if score <= 0:
            continue
        if sym.startswith(q):
            score += 10
        scored.append((score, r))
    scored.sort(key=lambda x: (-x[0], x[1]["symbol"]))
    return [r for _, r in scored[: max(1, min(limit, 200))]]


def name_by_symbol(symbol: str) -> str | None:
    sym = str(symbol or "").strip()
    if len(sym) != 6 or not sym.isdigit():
        return None
    for r in _load_rows():
        if r["symbol"] == sym:
            n = str(r.get("name_kr") or "").strip()
            return n or None
    return None


def catalog_size() -> int:
    return len(_load_rows())
