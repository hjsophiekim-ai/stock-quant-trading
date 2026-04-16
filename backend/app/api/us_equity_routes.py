"""미국 주식 시세(공식 overseas-price API) — 사용자 저장 KIS 자격 + 온디맨드 토큰."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from app.clients.kis_client import KISClient

from app.config import get_settings as get_app_settings

from backend.app.api.auth_routes import get_current_user_from_auth_header
from backend.app.api.broker_routes import get_broker_service
from backend.app.auth.kis_auth import issue_access_token
from backend.app.market.us_exchange_map import excd_for_price_chart
from backend.app.services.us_symbol_search_service import search_us_symbols_via_kis

router = APIRouter(prefix="/us-equity", tags=["us-equity"])


def _kis_client_for_user(authorization: str | None) -> tuple[KISClient, dict[str, Any]]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization 헤더가 필요합니다.")
    try:
        user = get_current_user_from_auth_header(authorization)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    svc = get_broker_service()
    try:
        app_key, app_secret, _acct, _prod, mode = svc.get_plain_credentials(user.id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="브로커 계정이 없습니다.") from exc
    api_base = svc._resolve_kis_api_base(mode)
    tr = issue_access_token(
        app_key=app_key,
        app_secret=app_secret,
        base_url=api_base,
        timeout_sec=12,
    )
    if not tr.ok or not tr.access_token:
        raise HTTPException(status_code=503, detail=tr.message or "KIS token failed")
    acfg = get_app_settings()
    client = KISClient(
        base_url=api_base.rstrip("/"),
        timeout_sec=10,
        token_provider=lambda: tr.access_token or "",
        app_key=app_key,
        app_secret=app_secret,
        live_execution_unlocked=False,
        kis_min_request_interval_ms=int(acfg.kis_min_request_interval_ms),
        kis_rate_limit_max_retries=int(acfg.kis_rate_limit_max_retries),
        kis_rate_limit_backoff_base_sec=float(acfg.kis_rate_limit_backoff_base_sec),
        kis_rate_limit_backoff_cap_sec=float(acfg.kis_rate_limit_backoff_cap_sec),
    )
    meta = {"api_base": api_base, "user_id": user.id}
    return client, meta


@router.get("/quote")
def us_quote(
    symbol: str = Query(..., min_length=1, max_length=16),
    excd: str | None = Query(None, description="미입력 시 search-info 로 거래소 추정"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """해외주식 현재체결가 — TR HHDFS00000300."""
    client, meta = _kis_client_for_user(authorization)
    sym = symbol.strip().upper()
    ex = (excd or "").strip().upper()
    if not ex:
        hits = search_us_symbols_via_kis(client, sym, limit=1)
        if not hits:
            raise HTTPException(status_code=404, detail="티커를 search-info로 확인하지 못했습니다.")
        ex = str(hits[0].get("excd") or "NAS")
    raw = client.get_overseas_price_quotation(excd=ex, symb=sym, auth="")
    return {
        "market": "us",
        "symbol": sym,
        "excd": ex,
        "kis_tr_id": client.overseas_tr_ids.price,
        "kis_path": client.overseas_price_paths.price,
        "raw": raw.get("output"),
        "_meta": meta,
    }


@router.get("/minute-bars")
def us_minute_bars(
    symbol: str = Query(..., min_length=1, max_length=16),
    excd: str | None = Query(None),
    nmin: str = Query("1", description="분 단위(공식 예제 nmin)"),
    nrec: str = Query("60", description="최대 120"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """해외주식분봉조회 — TR HHDFS76950200, 공식 예제 파라미터."""
    client, meta = _kis_client_for_user(authorization)
    sym = symbol.strip().upper()
    ex = (excd or "").strip().upper()
    if not ex:
        hits = search_us_symbols_via_kis(client, sym, limit=1)
        if not hits:
            raise HTTPException(status_code=404, detail="티커를 search-info로 확인하지 못했습니다.")
        ov = hits[0].get("ovrs_excg_cd")
        ex = excd_for_price_chart(str(ov or "NASD"))
    raw = client.get_overseas_time_itemchartprice(
        auth="",
        excd=ex,
        symb=sym,
        nmin=str(nmin),
        pinc="1",
        next_flag="",
        nrec=str(min(int(nrec or "60"), 120)),
        fill="",
        keyb="",
    )
    return {
        "market": "us",
        "symbol": sym,
        "excd": ex,
        "kis_tr_id": client.overseas_tr_ids.time_itemchart,
        "kis_path": client.overseas_price_paths.inquire_time_itemchartprice,
        "output1": raw.get("output1"),
        "output2": raw.get("output2"),
        "_meta": meta,
    }
