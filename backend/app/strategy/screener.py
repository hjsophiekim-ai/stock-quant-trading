"""
실시간·주기 갱신 가능한 종목 스크리너.

- KIS 일봉으로 유니버스 지표 계산
- 국면(regime)에 따라 후보 수·상위 수익률 비율 조정, 고변동 시 신규 차단
- 상위 N개만 유지, 점수·사유·감사 로그 저장
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.auth.kis_auth import issue_access_token
from backend.app.clients.kis_client import build_kis_client_for_backend
from backend.app.core.config import get_backend_settings, resolved_kis_api_base_url
from backend.app.strategy.ranking import (
    ScreenedCandidate,
    apply_hard_filters,
    apply_return_top_percentile,
    build_symbol_feature_row,
    rank_candidates,
    regime_adjusted_top_n_and_percentile,
)
from app.scheduler.kis_universe import (
    build_kis_stock_universe,
    build_kospi_index_series,
    build_mock_sp500_proxy_from_kospi,
    build_mock_volatility_series,
)
from app.strategy.market_regime import MarketRegimeConfig, MarketRegimeInputs, classify_market_regime

logger = logging.getLogger(__name__)

_engine_lock = threading.Lock()
_engine: "ScreenerEngine | None" = None


def _parse_symbols(raw: str) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


def _candidate_to_dict(c: ScreenedCandidate) -> dict[str, Any]:
    return {
        "symbol": c.symbol,
        "total_score": round(c.total_score, 6),
        "factor_scores": {k: round(v, 6) for k, v in c.factor_scores.items()},
        "reasons": list(c.reasons),
        "metrics": {k: round(v, 6) for k, v in c.metrics.items()},
    }


@dataclass
class ScreeningSnapshot:
    updated_at_utc: str
    regime: str
    regime_detail: dict[str, Any]
    regime_adjustment_reasons: list[str]
    blocked: bool
    block_reason: str | None
    universe_symbols: list[str]
    candidates: list[dict[str, Any]]
    filter_audit: list[str]
    top_n_effective: int
    return_percentile_threshold_pct: float | None = None


def _kis_client_for_screener() -> Any:
    bcfg = get_backend_settings()
    base = resolved_kis_api_base_url(bcfg)
    tr = issue_access_token(
        app_key=bcfg.kis_app_key,
        app_secret=bcfg.kis_app_secret,
        base_url=base,
        timeout_sec=12,
    )
    if not tr.ok or not tr.access_token:
        raise RuntimeError(tr.message or "KIS token issue failed")
    return build_kis_client_for_backend(bcfg, access_token=tr.access_token)


def _regime_detail_dict(regime_state: Any) -> dict[str, Any]:
    return {
        "regime": regime_state.regime,
        "reasons": list(regime_state.reasons),
        "features": asdict(regime_state.features),
    }


class ScreenerEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snap: ScreeningSnapshot | None = None

    def get_snapshot(self) -> ScreeningSnapshot | None:
        with self._lock:
            return self._snap

    def refresh(self) -> ScreeningSnapshot:
        bcfg = get_backend_settings()
        from app.config import get_settings as get_app_settings

        acfg = get_app_settings()
        raw_uni = (bcfg.screener_universe_symbols or "").strip()
        symbols = _parse_symbols(raw_uni) if raw_uni else _parse_symbols(acfg.paper_trading_symbols)
        if not symbols:
            snap = ScreeningSnapshot(
                updated_at_utc=datetime.now(timezone.utc).isoformat(),
                regime="unknown",
                regime_detail={},
                regime_adjustment_reasons=["유니버스 종목 없음"],
                blocked=True,
                block_reason="SCREENER_UNIVERSE_SYMBOLS / PAPER_TRADING_SYMBOLS 비어 있음",
                universe_symbols=[],
                candidates=[],
                filter_audit=[],
                top_n_effective=0,
            )
            self._store(snap, bcfg)
            return snap

        audit: list[str] = []
        try:
            client = _kis_client_for_screener()
        except Exception as exc:
            audit.append(f"KIS 클라이언트 실패: {exc}")
            snap = ScreeningSnapshot(
                updated_at_utc=datetime.now(timezone.utc).isoformat(),
                regime="unknown",
                regime_detail={},
                regime_adjustment_reasons=audit,
                blocked=True,
                block_reason=str(exc),
                universe_symbols=symbols,
                candidates=[],
                filter_audit=audit,
                top_n_effective=0,
            )
            logger.exception("screener KIS client failed")
            self._store(snap, bcfg)
            return snap

        prices_df = build_kis_stock_universe(
            client,
            symbols,
            lookback_calendar_days=bcfg.screener_lookback_days,
            logger=logger,
        )
        if prices_df.empty:
            audit.append("가격 데이터 없음")
            snap = ScreeningSnapshot(
                updated_at_utc=datetime.now(timezone.utc).isoformat(),
                regime="unknown",
                regime_detail={},
                regime_adjustment_reasons=audit,
                blocked=True,
                block_reason="KIS 일봉 조회 실패 또는 빈 응답",
                universe_symbols=symbols,
                candidates=[],
                filter_audit=audit,
                top_n_effective=0,
            )
            self._store(snap, bcfg)
            return snap

        kospi = build_kospi_index_series(
            client,
            lookback_calendar_days=bcfg.screener_lookback_days,
            logger=logger,
        )
        sp500 = build_mock_sp500_proxy_from_kospi(kospi)
        vol = build_mock_volatility_series(kospi)
        regime_state = classify_market_regime(
            MarketRegimeInputs(kospi=kospi, sp500=sp500, volatility=vol),
            MarketRegimeConfig(),
        )
        regime = regime_state.regime

        top_n_eff, ret_top_pct, reg_reasons = regime_adjusted_top_n_and_percentile(
            regime, bcfg.screener_top_n, bcfg.screener_top_return_pct
        )
        audit.extend(reg_reasons)

        if top_n_eff <= 0:
            snap = ScreeningSnapshot(
                updated_at_utc=datetime.now(timezone.utc).isoformat(),
                regime=regime,
                regime_detail=_regime_detail_dict(regime_state),
                regime_adjustment_reasons=reg_reasons,
                blocked=True,
                block_reason="고변동·리스크 국면: 신규 후보 차단",
                universe_symbols=symbols,
                candidates=[],
                filter_audit=audit,
                top_n_effective=0,
            )
            logger.warning("screener blocked regime=%s", regime)
            self._store(snap, bcfg)
            return snap

        rows: list[dict] = []
        for sym in symbols:
            row = build_symbol_feature_row(prices_df, sym)
            if row is None:
                audit.append(f"{sym}: 데이터부족(<65일) 제외")
            else:
                rows.append(row)

        hard_pass, hard_log = apply_hard_filters(rows)
        audit.extend(hard_log)
        pct_pass, pct_log, thr = apply_return_top_percentile(hard_pass, top_pct=ret_top_pct)
        audit.extend(pct_log)

        ranked = rank_candidates(pct_pass, regime=regime, top_n=top_n_eff)
        cand_dicts = [_candidate_to_dict(c) for c in ranked]

        snap = ScreeningSnapshot(
            updated_at_utc=datetime.now(timezone.utc).isoformat(),
            regime=regime,
            regime_detail=_regime_detail_dict(regime_state),
            regime_adjustment_reasons=reg_reasons,
            blocked=False,
            block_reason=None,
            universe_symbols=symbols,
            candidates=cand_dicts,
            filter_audit=audit,
            top_n_effective=top_n_eff,
            return_percentile_threshold_pct=thr,
        )
        logger.info(
            "screener refresh regime=%s candidates=%d/%d thr_ret=%s audit_lines=%d",
            regime,
            len(cand_dicts),
            len(symbols),
            f"{thr:.4f}" if thr is not None else "n/a",
            len(audit),
        )
        self._store(snap, bcfg)
        return snap

    def _store(self, snap: ScreeningSnapshot, bcfg: Any) -> None:
        with self._lock:
            self._snap = snap
        out_dir = Path(bcfg.screener_report_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        latest = out_dir / "screener_latest.json"
        payload = {
            "updated_at_utc": snap.updated_at_utc,
            "regime": snap.regime,
            "regime_detail": snap.regime_detail,
            "regime_adjustment_reasons": snap.regime_adjustment_reasons,
            "blocked": snap.blocked,
            "block_reason": snap.block_reason,
            "universe_symbols": snap.universe_symbols,
            "candidates": snap.candidates,
            "filter_audit": snap.filter_audit,
            "top_n_effective": snap.top_n_effective,
            "return_percentile_threshold_pct": snap.return_percentile_threshold_pct,
        }
        latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        hist_name = snap.updated_at_utc.replace(":", "-").replace("+", "_")
        hist = out_dir / f"screener_{hist_name}.json"
        try:
            hist.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass


def get_screener_engine() -> ScreenerEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = ScreenerEngine()
        return _engine


def screening_snapshot_to_dashboard_dict(snap: ScreeningSnapshot | None) -> dict[str, Any]:
    """대시보드용 축약 필드."""
    if snap is None:
        return {
            "status": "empty",
            "message": "후보 스크리닝 미실행 (/api/screening/refresh)",
            "candidates": [],
        }
    return {
        "status": "blocked" if snap.blocked else "ok",
        "updated_at_utc": snap.updated_at_utc,
        "regime": snap.regime,
        "regime_adjustment_reasons": snap.regime_adjustment_reasons,
        "blocked": snap.blocked,
        "block_reason": snap.block_reason,
        "top_n_effective": snap.top_n_effective,
        "candidates": snap.candidates,
        "filter_audit_tail": snap.filter_audit[-12:] if snap.filter_audit else [],
    }
