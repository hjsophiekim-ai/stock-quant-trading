from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.brokers.live_broker import LiveBroker
from app.config import get_settings as get_app_settings
from app.scheduler.intraday_jobs import fetch_quotes_throttled
from app.scheduler.kis_intraday import IntradayChartCache, build_intraday_universe_1m
from app.scheduler.kis_universe import build_kospi_index_series, build_mock_sp500_proxy_from_kospi
from app.strategy.final_betting_v1_strategy import FinalBettingV1Strategy, set_final_betting_debug_now
from app.strategy.intraday_common import analyze_krx_intraday_session
from app.strategy.intraday_paper_state import IntradayPaperStateStore
from app.strategy.base_strategy import StrategyContext
from app.orders.models import OrderRequest

from backend.app.clients.kis_client import build_kis_client_for_live_user
from backend.app.core.config import BackendSettings
from backend.app.services.broker_secret_service import BrokerSecretService
from backend.app.services.live_prep_store import LiveCandidate

logger = logging.getLogger("backend.app.engine.live_prep_engine")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kst_now() -> datetime:
    from backend.app.engine.scheduler import now_kst

    return now_kst()


def _intraday_state_store_path(settings: BackendSettings, *, user_tag: str, suffix: str) -> Path:
    base = Path(settings.backend_data_dir or "backend_data")
    return (base / "live_prep" / f"state_{user_tag}_{suffix}.json").resolve()


def _build_positions_df(positions: list[Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for p in positions:
        rows.append(
            {
                "symbol": str(getattr(p, "symbol", "") or ""),
                "quantity": int(getattr(p, "quantity", 0) or 0),
                "average_price": float(getattr(p, "average_price", 0.0) or 0.0),
                "hold_days": 0,
            }
        )
    return pd.DataFrame(rows, columns=["symbol", "quantity", "average_price", "hold_days"])


def _latest_close(universe_tf: pd.DataFrame, symbol: str) -> float:
    if universe_tf.empty:
        return 0.0
    if "symbol" not in universe_tf.columns:
        return 0.0
    if "close" not in universe_tf.columns:
        return 0.0
    sub = universe_tf[universe_tf["symbol"] == symbol]
    if sub.empty:
        return 0.0
    try:
        return float(sub.iloc[-1]["close"])
    except Exception:
        return 0.0


def _compute_equity_from_universe(universe_tf: pd.DataFrame, *, cash: float, positions: list[Any]) -> float:
    mv = 0.0
    for p in positions:
        sym = str(getattr(p, "symbol", "") or "")
        q = int(getattr(p, "quantity", 0) or 0)
        if q <= 0 or not sym:
            continue
        px = _latest_close(universe_tf, sym)
        if px <= 0:
            px = float(getattr(p, "average_price", 0.0) or 0.0)
        mv += float(px) * float(q)
    return float(cash) + float(mv)


def _candidate_from_diag(diag: dict[str, Any]) -> tuple[str, float | None, list[str], str]:
    sym = str(diag.get("symbol") or "")
    score = None
    try:
        score = float(diag.get("flow_proxy_score")) if diag.get("flow_proxy_score") is not None else None
    except Exception:
        score = None
    flags: list[str] = []
    if bool(diag.get("atr_fallback_used")):
        flags.append("atr_fallback_used")
    if bool(diag.get("final_betting_rebound_candidate")):
        flags.append("bearish_rebound_candidate")
    if bool(diag.get("final_betting_entry_aggressive")):
        flags.append("aggressive_entry")
    hits = int(diag.get("signal_hits") or 0)
    rsi14 = diag.get("rsi14")
    atr_pct = diag.get("atr_pct")
    rank = diag.get("final_betting_rank")
    rationale = f"hits={hits}"
    if rank is not None:
        rationale += f" rank={rank}"
    if rsi14 is not None:
        rationale += f" rsi14={rsi14}"
    if atr_pct is not None:
        rationale += f" atr_pct={atr_pct}"
    return sym, score, flags, rationale


def _build_live_client_and_broker(
    *,
    broker_service: BrokerSecretService,
    backend_settings: BackendSettings,
    user_id: str,
    live_execution_unlocked: bool,
) -> tuple[Any, LiveBroker, str] | tuple[None, None, str]:  # type: ignore[valid-type]
    try:
        app_key, app_secret, account_no, product_code, mode = broker_service.get_plain_credentials(user_id)
    except Exception:
        return (None, None, "broker_credentials_missing")  # type: ignore[return-value]
    if (mode or "").strip().lower() != "live":
        return (None, None, "broker_account_not_live")  # type: ignore[return-value]

    tok = broker_service.ensure_cached_token_for_paper_start(user_id)
    if not tok.ok or not tok.access_token:
        return (None, None, tok.failure_code or "token_not_ready")  # type: ignore[return-value]

    api_base = broker_service._resolve_kis_api_base(mode)  # type: ignore[attr-defined]
    client = build_kis_client_for_live_user(
        base_url=api_base,
        access_token=tok.access_token,
        app_key=app_key,
        app_secret=app_secret,
        live_execution_unlocked=bool(live_execution_unlocked),
    )
    broker = LiveBroker(kis_client=client, account_no=account_no, account_product_code=product_code, logger=logger)
    return client, broker, ""


def compute_final_betting_exit_orders_live(
    *,
    broker_service: BrokerSecretService,
    backend_settings: BackendSettings,
    user_id: str,
    debug_now_kst: datetime | None = None,
) -> dict[str, Any]:
    client, broker, err = _build_live_client_and_broker(
        broker_service=broker_service,
        backend_settings=backend_settings,
        user_id=user_id,
        live_execution_unlocked=False,
    )
    if client is None or broker is None:
        return {"ok": False, "error": err, "message": err}

    cfg = get_app_settings()
    symbols = cfg.resolved_final_betting_symbol_list()
    symbols = [s.strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {"ok": False, "error": "empty_symbols", "message": "final_betting 심볼 리스트가 비어 있습니다."}

    set_final_betting_debug_now(debug_now_kst)
    try:
        scfg = None
        try:
            from app.scheduler.jobs import krx_session_config_from_settings

            scfg = krx_session_config_from_settings(cfg)
        except Exception:
            scfg = None
        snap = analyze_krx_intraday_session(session_config=scfg)
        chart_cache = IntradayChartCache(
            ttl_sec=float(cfg.paper_intraday_chart_cache_ttl_sec),
            min_interval_sec=float(cfg.paper_intraday_chart_min_interval_sec),
        )
        universe_1m, fetch_summary = build_intraday_universe_1m(
            client,
            symbols,
            target_bars_per_symbol=140,
            logger=logger,
            cache=chart_cache,
            intraday_fetch_allowed=bool(snap.fetch_allowed),
            intraday_fetch_block_reason=snap.fetch_block_reason,
            session_state=snap.state,
            order_allowed=False,
        )
        lookback = max(int(cfg.paper_kis_chart_lookback_days), 60)
        kospi = build_kospi_index_series(client, lookback_calendar_days=lookback, logger=logger)
        sp500 = build_mock_sp500_proxy_from_kospi(kospi)
        quote_by_symbol = fetch_quotes_throttled(
            client,
            symbols,
            min_interval_sec=max(0.15, float(cfg.paper_intraday_chart_min_interval_sec)),
            logger=logger,
        )

        positions = broker.get_positions()
        portfolio_df = _build_positions_df(positions)
        cash = float(broker.get_cash() or 0.0)
        equity = _compute_equity_from_universe(universe_1m, cash=cash, positions=positions)

        state_path = _intraday_state_store_path(backend_settings, user_tag=user_id[:12], suffix="final_betting")
        state_store = IntradayPaperStateStore(state_path, logger=logger)
        state = state_store.load()

        strategy = FinalBettingV1Strategy()
        strategy.intraday_state = state
        strategy.quote_by_symbol = quote_by_symbol
        strategy.intraday_session_context = {
            "krx_session_state": snap.state,
            "fetch_allowed": snap.fetch_allowed,
            "order_allowed": False,
            "fetch_block_reason": snap.fetch_block_reason,
            "order_block_reason": "live_sell_only",
            "regular_session_kst": snap.regular_session_kst,
        }
        setattr(strategy, "_final_betting_equity_krw", float(equity))

        context = StrategyContext(
            prices=universe_1m,
            kospi_index=kospi,
            sp500_index=sp500,
            portfolio=portfolio_df,
        )
        orders = strategy.generate_orders(context)
        state_store.save(strategy.intraday_state or state)

        sell_orders = [o for o in orders if o.side == "sell"]
        return {
            "ok": True,
            "asof_utc": _utc_now_iso(),
            "strategy_id": "final_betting_v1",
            "order_allowed": False,
            "sell_orders": [asdict(o) for o in sell_orders],
            "sell_symbol_count": len({o.symbol for o in sell_orders}),
            "shadow": {
                "last_diagnostics": list(getattr(strategy, "last_diagnostics", []) or [])[-50:],
                "fetch_summary": fetch_summary,
                "session_state": snap.state,
                "fetch_allowed": snap.fetch_allowed,
                "order_allowed": False,
            },
        }
    finally:
        set_final_betting_debug_now(None)


def generate_final_betting_shadow_candidates(
    *,
    broker_service: BrokerSecretService,
    backend_settings: BackendSettings,
    user_id: str,
    limit: int = 5,
    symbols_override: list[str] | None = None,
    debug_now_kst: datetime | None = None,
) -> dict[str, Any]:
    client, broker, err = _build_live_client_and_broker(
        broker_service=broker_service,
        backend_settings=backend_settings,
        user_id=user_id,
        live_execution_unlocked=False,
    )
    if client is None or broker is None:
        return {"ok": False, "error": err, "message": err}

    cfg = get_app_settings()
    symbols = list(symbols_override) if symbols_override is not None else cfg.resolved_final_betting_symbol_list()
    symbols = [s.strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {"ok": False, "error": "empty_symbols", "message": "final_betting 심볼 리스트가 비어 있습니다."}

    set_final_betting_debug_now(debug_now_kst)
    try:
        scfg = None
        try:
            from app.scheduler.jobs import krx_session_config_from_settings

            scfg = krx_session_config_from_settings(cfg)
        except Exception:
            scfg = None
        snap = analyze_krx_intraday_session(session_config=scfg)
        chart_cache = IntradayChartCache(
            ttl_sec=float(cfg.paper_intraday_chart_cache_ttl_sec),
            min_interval_sec=float(cfg.paper_intraday_chart_min_interval_sec),
        )
        universe_1m, fetch_summary = build_intraday_universe_1m(
            client,
            symbols,
            target_bars_per_symbol=140,
            logger=logger,
            cache=chart_cache,
            intraday_fetch_allowed=bool(snap.fetch_allowed),
            intraday_fetch_block_reason=snap.fetch_block_reason,
            session_state=snap.state,
            order_allowed=False,
        )
        lookback = max(int(cfg.paper_kis_chart_lookback_days), 60)
        kospi = build_kospi_index_series(client, lookback_calendar_days=lookback, logger=logger)
        sp500 = build_mock_sp500_proxy_from_kospi(kospi)
        quote_by_symbol = fetch_quotes_throttled(
            client,
            symbols,
            min_interval_sec=max(0.15, float(cfg.paper_intraday_chart_min_interval_sec)),
            logger=logger,
        )

        positions = broker.get_positions()
        portfolio_df = _build_positions_df(positions)
        cash = float(broker.get_cash() or 0.0)
        equity = _compute_equity_from_universe(universe_1m, cash=cash, positions=positions)

        state_path = _intraday_state_store_path(backend_settings, user_tag=user_id[:12], suffix="final_betting")
        state_store = IntradayPaperStateStore(state_path, logger=logger)
        state = state_store.load()

        strategy = FinalBettingV1Strategy()
        strategy.intraday_state = state
        strategy.quote_by_symbol = quote_by_symbol
        strategy.intraday_session_context = {
            "krx_session_state": snap.state,
            "fetch_allowed": snap.fetch_allowed,
            "order_allowed": False,
            "fetch_block_reason": snap.fetch_block_reason,
            "order_block_reason": "live_shadow",
            "regular_session_kst": snap.regular_session_kst,
        }
        setattr(strategy, "_final_betting_equity_krw", float(equity))

        context = StrategyContext(
            prices=universe_1m,
            kospi_index=kospi,
            sp500_index=sp500,
            portfolio=portfolio_df,
        )
        orders = strategy.generate_orders(context)
        state_store.save(strategy.intraday_state or state)

        diags = list(getattr(strategy, "last_diagnostics", []) or [])
        entered = [d for d in diags if bool(d.get("entered"))]
        buy_syms = [o.symbol for o in orders if o.side == "buy"]
        sell_syms = [o.symbol for o in orders if o.side == "sell"]

        by_symbol_diag: dict[str, dict[str, Any]] = {}
        for d in entered:
            sym = str(d.get("symbol") or "")
            if sym and sym not in by_symbol_diag:
                by_symbol_diag[sym] = d

        candidates: list[LiveCandidate] = []
        for o in [x for x in orders if x.side == "buy"][: max(1, min(int(limit), 5))]:
            diag = by_symbol_diag.get(o.symbol) or {}
            sym, score, flags, rationale = _candidate_from_diag(diag)
            candidates.append(
                LiveCandidate(
                    candidate_id=str(uuid.uuid4()),
                    status="approval_pending",
                    symbol=o.symbol,
                    side="buy",
                    strategy_id=str(o.strategy_id or "final_betting_v1"),
                    score=score,
                    quantity=int(o.quantity),
                    price=float(o.price) if o.price is not None else None,
                    stop_loss_pct=float(o.stop_loss_pct) if o.stop_loss_pct is not None else None,
                    rationale=rationale,
                    risk_flags=flags,
                    metadata={"diag": diag},
                )
            )

        for o in [x for x in orders if x.side == "sell"][:10]:
            candidates.append(
                LiveCandidate(
                    candidate_id=str(uuid.uuid4()),
                    status="approval_pending",
                    symbol=o.symbol,
                    side="sell",
                    strategy_id=str(o.strategy_id or "final_betting_v1"),
                    score=None,
                    quantity=int(o.quantity),
                    price=float(o.price) if o.price is not None else None,
                    stop_loss_pct=None,
                    rationale="exit_signal",
                    risk_flags=[],
                    metadata={},
                )
            )

        return {
            "ok": True,
            "asof_utc": _utc_now_iso(),
            "market": "domestic",
            "strategy_id": "final_betting_v1",
            "candidate_limit": int(limit),
            "candidate_count": len(candidates),
            "candidates": [asdict(c) for c in candidates],
            "shadow": {
                "generated_buy_symbols": buy_syms,
                "generated_sell_symbols": sell_syms,
                "last_diagnostics": diags[-50:],
                "fetch_summary": fetch_summary,
                "session_state": snap.state,
                "fetch_allowed": snap.fetch_allowed,
                "order_allowed": False,
            },
            "equity_estimate_krw": float(equity),
            "token_cache": {
                "hit": bool(tok.token_cache_hit),
                "source": tok.token_cache_source,
                "persisted": bool(tok.token_cache_persisted),
            },
        }
    finally:
        set_final_betting_debug_now(None)


def _strategy_for_shadow_id(strategy_id: str):
    sid = (strategy_id or "").strip().lower()
    if sid in ("scalp_rsi_flag_hf_v1", "intraday_rsi_flag_hf_v1"):
        from app.strategy.scalp_rsi_flag_hf_v1_strategy import ScalpRsiFlagHfV1Strategy

        inst = ScalpRsiFlagHfV1Strategy()
        setattr(inst, "_paper_strategy_id", sid)
        return inst
    if sid == "scalp_macd_rsi_3m_v1":
        from app.strategy.scalp_macd_rsi_3m_v1_strategy import ScalpMacdRsi3mV1Strategy

        return ScalpMacdRsi3mV1Strategy()
    if sid == "scalp_momentum_v1":
        from app.strategy.scalp_momentum_v1_strategy import ScalpMomentumV1Strategy

        return ScalpMomentumV1Strategy()
    raise ValueError("unsupported_strategy_id")


def _order_to_dict(o: OrderRequest) -> dict[str, Any]:
    return {
        "symbol": o.symbol,
        "side": o.side,
        "quantity": int(o.quantity),
        "price": float(o.price) if o.price is not None else None,
        "stop_loss_pct": float(o.stop_loss_pct) if o.stop_loss_pct is not None else None,
        "strategy_id": str(o.strategy_id or ""),
        "signal_reason": str(o.signal_reason or ""),
    }


def generate_intraday_shadow_report(
    *,
    broker_service: BrokerSecretService,
    backend_settings: BackendSettings,
    user_id: str,
    strategy_id: str,
    symbols_override: list[str] | None = None,
) -> dict[str, Any]:
    app_key, app_secret, account_no, product_code, mode = broker_service.get_plain_credentials(user_id)
    if (mode or "").strip().lower() != "live":
        return {"ok": False, "error": "broker_account_not_live", "message": "브로커 계정이 live 모드가 아닙니다."}

    tok = broker_service.ensure_cached_token_for_paper_start(user_id)
    if not tok.ok or not tok.access_token:
        return {"ok": False, "error": tok.failure_code or "token_not_ready", "message": tok.message}

    api_base = broker_service._resolve_kis_api_base(mode)  # type: ignore[attr-defined]
    client = build_kis_client_for_live_user(
        base_url=api_base,
        access_token=tok.access_token,
        app_key=app_key,
        app_secret=app_secret,
        live_execution_unlocked=False,
    )

    cfg = get_app_settings()
    symbols = list(symbols_override) if symbols_override is not None else cfg.resolved_intraday_symbol_list()
    symbols = [s.strip() for s in symbols if s and str(s).strip()]
    if not symbols:
        return {"ok": False, "error": "empty_symbols", "message": "intraday 심볼 리스트가 비어 있습니다."}

    scfg = None
    try:
        from app.scheduler.jobs import krx_session_config_from_settings

        scfg = krx_session_config_from_settings(cfg)
    except Exception:
        scfg = None
    snap = analyze_krx_intraday_session(session_config=scfg)
    chart_cache = IntradayChartCache(
        ttl_sec=float(cfg.paper_intraday_chart_cache_ttl_sec),
        min_interval_sec=float(cfg.paper_intraday_chart_min_interval_sec),
    )
    universe_1m, fetch_summary = build_intraday_universe_1m(
        client,
        symbols,
        target_bars_per_symbol=160,
        logger=logger,
        cache=chart_cache,
        intraday_fetch_allowed=bool(snap.fetch_allowed),
        intraday_fetch_block_reason=snap.fetch_block_reason,
        session_state=snap.state,
        order_allowed=False,
    )

    lookback = max(int(cfg.paper_kis_chart_lookback_days), 60)
    kospi = build_kospi_index_series(client, lookback_calendar_days=lookback, logger=logger)
    sp500 = build_mock_sp500_proxy_from_kospi(kospi)
    quote_by_symbol = fetch_quotes_throttled(
        client,
        symbols,
        min_interval_sec=max(0.15, float(cfg.paper_intraday_chart_min_interval_sec)),
        logger=logger,
    )

    broker = LiveBroker(kis_client=client, account_no=account_no, account_product_code=product_code, logger=logger)
    positions = broker.get_positions()
    portfolio_df = _build_positions_df(positions)

    state_path = _intraday_state_store_path(backend_settings, user_tag=user_id[:12], suffix=strategy_id)
    state_store = IntradayPaperStateStore(state_path, logger=logger)
    state = state_store.load()

    try:
        strategy = _strategy_for_shadow_id(strategy_id)
    except ValueError:
        return {"ok": False, "error": "unsupported_strategy_id", "message": f"지원되지 않는 strategy_id={strategy_id}"}

    if hasattr(strategy, "intraday_state"):
        setattr(strategy, "intraday_state", state)
    if hasattr(strategy, "quote_by_symbol"):
        setattr(strategy, "quote_by_symbol", quote_by_symbol)
    if hasattr(strategy, "intraday_session_context"):
        setattr(
            strategy,
            "intraday_session_context",
            {
                "krx_session_state": snap.state,
                "fetch_allowed": snap.fetch_allowed,
                "order_allowed": False,
                "fetch_block_reason": snap.fetch_block_reason,
                "order_block_reason": "live_shadow",
                "regular_session_kst": snap.regular_session_kst,
            },
        )

    context = StrategyContext(
        prices=universe_1m,
        kospi_index=kospi,
        sp500_index=sp500,
        portfolio=portfolio_df,
    )
    orders = strategy.generate_orders(context)
    if hasattr(strategy, "intraday_state"):
        state_store.save(getattr(strategy, "intraday_state") or state)

    return {
        "ok": True,
        "asof_utc": _utc_now_iso(),
        "market": "domestic",
        "strategy_id": str(strategy_id),
        "order_allowed": False,
        "generated_order_count": len(orders),
        "generated_orders": [_order_to_dict(o) for o in orders],
        "last_diagnostics": list(getattr(strategy, "last_diagnostics", []) or [])[-50:],
        "intraday_signal_breakdown": dict(getattr(strategy, "last_intraday_signal_breakdown", {}) or {}),
        "fetch_summary": fetch_summary,
    }

