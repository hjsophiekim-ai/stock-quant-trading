"""종목 찾기: (1) 종목명 (2) 심볼 (3) 전략 후보 — 역할을 분리."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from backend.app.services.local_symbol_catalog import (
    catalog_size,
    name_by_symbol,
    search_by_name_kr,
    search_by_symbol_code,
    search_local_liquid_symbols,
)
from backend.app.strategy.screener import get_screener_engine
from backend.app.strategy.signal_engine import get_swing_signal_engine, snapshot_to_jsonable

router = APIRouter(prefix="/stocks", tags=["stocks"])

_BASE_KO = (
    "앱에 포함된 `data/domestic_liquid_symbols.json` 목록만 대상입니다. "
    "한국투자증권 공식 실시간 종목검색 API가 아닙니다."
)


@router.get("/search-by-name")
def search_stocks_by_name(
    q: str = Query("", description="종목명 일부 (예: 삼성, 하이닉스)"),
    limit: int = Query(40, ge=1, le=200),
) -> dict[str, object]:
    """**1) 종목명 검색** — 한글 종목명 부분 일치."""
    matches = search_by_name_kr(query=q, limit=limit)
    return {
        "api_role": "name_search",
        "title_ko": "종목명 검색 (앱 내 목록)",
        "kis_official_search": False,
        "description_ko": _BASE_KO + " 종목코드보다 이름으로 찾을 때 사용하세요.",
        "catalog_entry_count": catalog_size(),
        "query": q.strip(),
        "match_count": len(matches),
        "matches": matches,
    }


@router.get("/search-by-symbol")
def search_stocks_by_symbol(
    q: str = Query("", description="6자리 숫자 종목코드 또는 일부 (예: 005930)"),
    limit: int = Query(40, ge=1, le=200),
) -> dict[str, object]:
    """**2) 심볼(종목코드) 검색** — 숫자 코드 접두·부분 일치."""
    matches = search_by_symbol_code(query=q, limit=limit)
    return {
        "api_role": "symbol_search",
        "title_ko": "심볼(종목코드) 검색 (앱 내 목록)",
        "kis_official_search": False,
        "description_ko": _BASE_KO + " 코드를 알 때·접두로 찾을 때 사용하세요.",
        "catalog_entry_count": catalog_size(),
        "query": q.strip(),
        "match_count": len(matches),
        "matches": matches,
    }


@router.get("/strategy-candidates")
def get_strategy_candidates(
    strategy_id: str = Query(
        "swing_v1",
        description="지원: swing_v1",
    ),
) -> dict[str, Any]:
    """**3) 전략 후보 조회** — 스크리너·신호 엔진 스냅샷 (검색과 무관)."""
    sid = (strategy_id or "").strip().lower()
    if sid != "swing_v1":
        raise HTTPException(
            status_code=400,
            detail="지원 strategy_id: swing_v1 만 제공합니다.",
        )

    scr = get_screener_engine().get_snapshot()
    sig = get_swing_signal_engine().get_snapshot()

    screener_block: dict[str, Any]
    if scr is None:
        screener_block = {
            "status": "empty",
            "message": "스크리너 스냅샷 없음. POST /api/screening/refresh 후 다시 시도하세요.",
            "candidates": [],
        }
    else:
        enriched: list[dict[str, Any]] = []
        for c in scr.candidates:
            if not isinstance(c, dict):
                continue
            sym = str(c.get("symbol") or "").strip()
            row = dict(c)
            if sym:
                nm = name_by_symbol(sym)
                if nm:
                    row["name_kr_catalog"] = nm
            enriched.append(row)
        screener_block = {
            "status": "blocked" if scr.blocked else "ok",
            "updated_at_utc": scr.updated_at_utc,
            "regime": scr.regime,
            "blocked": scr.blocked,
            "block_reason": scr.block_reason,
            "universe_symbols": scr.universe_symbols,
            "candidates": enriched,
            "top_n_effective": scr.top_n_effective,
        }

    signal_block: dict[str, Any]
    if sig is None:
        signal_block = {
            "status": "empty",
            "message": "신호 엔진 스냅샷 없음. POST /api/strategy-signals/evaluate 후 다시 시도하세요.",
        }
    else:
        full = snapshot_to_jsonable(sig)
        per = full.get("per_symbol") if isinstance(full, dict) else []
        ps_enriched: list[dict[str, Any]] = []
        if isinstance(per, list):
            for d in per:
                if not isinstance(d, dict):
                    continue
                sym = str(d.get("symbol") or "").strip()
                row = dict(d)
                if sym:
                    nm = name_by_symbol(sym)
                    if nm:
                        row["name_kr_catalog"] = nm
                ps_enriched.append(row)
        signal_block = {
            "status": "ok",
            "evaluated_at_utc": full.get("evaluated_at_utc") if isinstance(full, dict) else None,
            "market_regime": full.get("market_regime") if isinstance(full, dict) else None,
            "per_symbol": ps_enriched,
        }

    return {
        "api_role": "strategy_candidates",
        "kind": "strategy_candidate_list",
        "strategy_id": "swing_v1",
        "title_ko": "전략 후보 (swing_v1)",
        "description_ko": (
            "스크리너가 유니버스에서 고른 후보(candidates)와 스윙 신호 엔진의 종목별 상태(per_symbol)입니다. "
            "종목명/코드 검색 API와 데이터 소스가 다릅니다."
        ),
        "screener": screener_block,
        "signal_engine": signal_block,
    }


@router.get("/local-symbol-search")
def local_symbol_search(
    q: str = Query("", description="종목코드 또는 종목명 일부 (혼합, 하위 호환)"),
    limit: int = Query(40, ge=1, le=200),
) -> dict[str, object]:
    """하위 호환: 이름·코드 혼합 검색. 신규는 `/search-by-name` · `/search-by-symbol` 권장."""
    matches = search_local_liquid_symbols(query=q, limit=limit)
    return {
        "api_role": "legacy_combined_search",
        "search_name": "국내 유동주 빠른 찾기 (레거시)",
        "kis_official_search": False,
        "description_ko": (
            "이전 버전 호환용 혼합 검색입니다. "
            "목적에 맞게 `/api/stocks/search-by-name` 또는 `/api/stocks/search-by-symbol` 사용을 권장합니다."
        ),
        "catalog_entry_count": catalog_size(),
        "query": q.strip(),
        "match_count": len(matches),
        "matches": matches,
    }
