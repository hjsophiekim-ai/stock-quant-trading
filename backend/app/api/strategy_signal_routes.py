"""전략 신호 엔진 스냅샷 조회·평가(KIS 시세)."""

from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException

from backend.app.auth.kis_auth import issue_access_token
from backend.app.clients.kis_client import build_kis_client_for_backend
from backend.app.core.config import get_backend_settings, resolved_kis_api_base_url
from backend.app.strategy.signal_engine import (
    get_swing_signal_engine,
    parse_live_quote_from_kis,
    snapshot_to_jsonable,
)
from app.config import get_settings as get_app_settings
from app.scheduler.kis_universe import (
    build_kis_stock_universe,
    build_kospi_index_series,
    build_mock_sp500_proxy_from_kospi,
    build_mock_volatility_series,
)
from app.strategy.market_regime import MarketRegimeConfig, MarketRegimeInputs, classify_market_regime

router = APIRouter(prefix="/strategy-signals", tags=["strategy-signals"])


def _parse_symbols(raw: str) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


def _portfolio_rows_from_settings() -> pd.DataFrame:
    """브로커 미연동 시 빈 포지션(신호는 진입 위주로 평가)."""
    return pd.DataFrame(columns=["symbol", "quantity", "average_price", "hold_days"])


@router.get("/latest")
def get_latest_strategy_signals() -> dict[str, Any]:
    eng = get_swing_signal_engine()
    snap = eng.get_snapshot()
    if snap is None:
        return {"status": "empty", "message": "아직 evaluate 미실행. POST /api/strategy-signals/evaluate"}
    out = snapshot_to_jsonable(snap)
    out["status"] = "ok"
    return out


@router.post("/evaluate")
def evaluate_strategy_signals() -> dict[str, Any]:
    bcfg = get_backend_settings()
    acfg = get_app_settings()
    raw_uni = (bcfg.screener_universe_symbols or "").strip()
    symbols = _parse_symbols(raw_uni) if raw_uni else _parse_symbols(acfg.paper_trading_symbols)
    if not symbols:
        raise HTTPException(status_code=400, detail="종목 유니버스가 비어 있습니다.")

    base = resolved_kis_api_base_url(bcfg)
    tr = issue_access_token(
        app_key=bcfg.kis_app_key,
        app_secret=bcfg.kis_app_secret,
        base_url=base,
        timeout_sec=12,
    )
    if not tr.ok or not tr.access_token:
        raise HTTPException(status_code=503, detail=tr.message or "KIS token failed")

    client = build_kis_client_for_backend(bcfg, access_token=tr.access_token)
    lookback = max(bcfg.screener_lookback_days, 120)

    prices_df = build_kis_stock_universe(
        client,
        symbols,
        lookback_calendar_days=lookback,
    )
    if prices_df.empty:
        raise HTTPException(status_code=503, detail="일봉 유니버스 조회 실패")

    kospi = build_kospi_index_series(client, lookback_calendar_days=lookback)
    sp500 = build_mock_sp500_proxy_from_kospi(kospi)
    vol = build_mock_volatility_series(kospi)
    regime_state = classify_market_regime(
        MarketRegimeInputs(kospi=kospi, sp500=sp500, volatility=vol),
        MarketRegimeConfig(),
    )

    quotes: dict[str, Any] = {}
    for sym in symbols:
        try:
            raw = client.get_quote(sym)
            q = parse_live_quote_from_kis(sym, raw)
            if q:
                quotes[sym] = q
        except Exception:
            continue

    eng = get_swing_signal_engine()
    snap = eng.evaluate(
        prices_df,
        quotes,
        _portfolio_rows_from_settings(),
        market_regime=regime_state.regime,
    )
    out = snapshot_to_jsonable(snap)
    out["status"] = "ok"
    out["regime_reasons"] = list(regime_state.reasons)
    return out
