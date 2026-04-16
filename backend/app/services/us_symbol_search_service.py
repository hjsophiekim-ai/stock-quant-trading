"""미국 티커 조회: 공식 `search-info`(CTPF1702R) + prdt_type_cd 512/513/529 (search_info 도움말)."""

from __future__ import annotations

import time
from typing import Any

from app.clients.kis_client import KISClient, KISClientError

from backend.app.market.us_exchange_map import excd_for_price_chart

_US_TYPES = ("512", "513", "529")
_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_TTL_SEC = 45.0


def _norm_symbol(q: str) -> str:
    return "".join(c for c in (q or "").strip().upper() if c.isalnum())


def _row_from_output(payload: dict[str, Any]) -> dict[str, Any] | None:
    raw = payload.get("output")
    if isinstance(raw, list) and raw:
        first = raw[0]
        return first if isinstance(first, dict) else None
    if isinstance(raw, dict):
        return raw
    return None


def search_us_symbols_via_kis(client: KISClient, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """티커 정확 일치 위주: 각 미국 상품유형에 대해 search_info(pdno=티커) 호출."""
    sym = _norm_symbol(query)
    if not sym:
        return []
    lim = max(1, min(int(limit), 40))
    now = time.monotonic()
    ck = sym
    hit = _CACHE.get(ck)
    if hit and (now - hit[0]) < _TTL_SEC:
        return list(hit[1])[:lim]

    matches: list[dict[str, Any]] = []
    for prdt in _US_TYPES:
        try:
            payload = client.get_overseas_search_info(prdt_type_cd=prdt, pdno=sym)
        except KISClientError:
            continue
        row = _row_from_output(payload)
        if not row:
            continue
        pdno = str(row.get("pdno") or row.get("PDNO") or row.get("std_pdno") or row.get("STD_PDNO") or "").strip().upper()
        if pdno != sym:
            continue
        ovrs = str(row.get("ovrs_excg_cd") or row.get("OVRS_EXCG_CD") or "").strip().upper()
        name = str(row.get("prdt_eng_name") or row.get("PRDT_ENG_NAME") or row.get("prdt_name") or row.get("PRDT_NAME") or "")
        excd = excd_for_price_chart(ovrs) if ovrs else "NAS"
        matches.append(
            {
                "symbol": pdno,
                "name_en": name,
                "ovrs_excg_cd": ovrs or None,
                "prdt_type_cd": prdt,
                "excd": excd,
                "kis_tr_id": "CTPF1702R",
                "kis_path": "/uapi/overseas-price/v1/quotations/search-info",
            }
        )
        break

    _CACHE[ck] = (now, list(matches))
    return matches[:lim]
