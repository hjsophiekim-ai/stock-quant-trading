"""운영 대시보드: KIS·런타임·포트폴리오·리스크·스크리너·신호 엔진 상태 집계."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException, Query

from backend.app.api.auth_routes import get_current_user_from_auth_header
from backend.app.api.broker_routes import get_broker_service
from backend.app.auth.kis_auth import issue_access_token, validate_kis_inputs
from backend.app.core.config import BackendSettings, get_backend_settings, is_live_order_execution_configured, resolved_kis_api_base_url
from backend.app.core.storage_paths import directory_is_writable, get_resolved_storage_paths, path_is_writable_file_location
from backend.app.engine.runtime_engine import get_runtime_engine
from backend.app.orders import build_kis_mock_execution_engine
from backend.app.orders.order_store import TrackedOrderStore, filter_active_submitted
from backend.app.portfolio.sync_engine import load_last_snapshot, read_jsonl_tail
from backend.app.risk.audit import read_jsonl_tail as read_jsonl_tail_risk
from backend.app.risk.service import build_public_risk_status
from backend.app.portfolio.performance_aggregate import build_dashboard_performance_block
from backend.app.strategy.screener import get_screener_engine, screening_snapshot_to_dashboard_dict
from backend.app.strategy.signal_engine import get_swing_signal_engine, snapshot_to_jsonable

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# 서버 .env 브로커 probe는 토큰 발급 API를 사용하므로 너무 자주 호출하지 않는다.
_BROKER_PROBE_TTL_SEC = 180.0
_OPEN_ORDERS_TTL_SEC = 20.0
_broker_probe_cache: tuple[float, dict[str, Any]] | None = None
_open_orders_cache: tuple[float, list[dict[str, Any]], str | None] | None = None


def _build_market_status_cards(
    paper_trading_status_domestic: dict[str, Any],
    paper_trading_status_us: dict[str, Any],
    psd: dict[str, Any] | None,
    rt: dict[str, Any],
) -> list[dict[str, Any]]:
    tick = (psd or {}).get("tick_report") or {}
    domestic_session = tick.get("krx_session_state") or rt.get("market_phase_now") or "closed"
    sid_dom = paper_trading_status_domestic.get("strategy_id")
    sid_us = paper_trading_status_us.get("strategy_id")
    dom_msg = f"strategy={sid_dom}" if sid_dom else "Paper 미실행"
    us_state = str(paper_trading_status_us.get("session_state") or tick.get("us_session_state") or "")
    us_msg = f"strategy={sid_us}" if sid_us else "Paper 미실행"
    return [
        {
            "market": "domestic",
            "title": "국내 (KRX · Paper)",
            "status": str(paper_trading_status_domestic.get("status") or "unknown"),
            "session_state": str(domestic_session),
            "message": dom_msg,
        },
        {
            "market": "us",
            "title": "미국 (Paper · KIS overseas)",
            "status": str(paper_trading_status_us.get("status") or "unknown"),
            "session_state": us_state or "—",
            "message": us_msg,
        },
    ]


def _try_current_user(authorization: str | None) -> Any:
    if not authorization or not str(authorization).strip():
        return None
    try:
        return get_current_user_from_auth_header(authorization)
    except (HTTPException, ValueError):
        return None


def _user_broker_snapshot(user_id: str) -> dict[str, Any] | None:
    svc = get_broker_service()
    try:
        acc = svc.get_account(user_id)
    except ValueError:
        return None
    return {
        "registered": True,
        "kis_app_key_masked": acc.kis_app_key_masked,
        "kis_account_no_masked": acc.kis_account_no_masked,
        "kis_account_product_code": acc.kis_account_product_code,
        "trading_mode": acc.trading_mode,
        "connection_status": acc.connection_status,
        "connection_message": acc.connection_message,
        "last_tested_at": acc.last_tested_at.isoformat() if acc.last_tested_at else None,
        "updated_at": acc.updated_at.isoformat(),
    }


def _broker_chain_ok(broker_probe: dict[str, Any], user_snap: dict[str, Any] | None) -> bool:
    """앱 등록 브로커가 성공이면 서버 .env 토큰 실패만으로는 연결 불가로 보지 않음."""
    if user_snap and str(user_snap.get("connection_status") or "") == "success":
        return True
    return bool(broker_probe.get("ok"))


def _dashboard_todos() -> list[str]:
    """UI에 그대로 노출 가능한 미구현·한계 설명."""
    return [
        "Paper 세션 실행 중에는 미체결·최근체결·포지션·랭킹 후보가 사용자 모의 계정(/api/paper-trading/dashboard-data)과 동일 소스입니다.",
        "손익 카드·월간 수익률 등 일부 지표는 여전히 서버 포트폴리오 sync·성과 집계 기준일 수 있습니다(계정 불일치 시 별도 안내).",
        "monthly_return_pct: performance_aggregate 와 /api/performance 동일(equity 곡선, UTC 월앵커).",
    ]


def _storage_diagnostics(cfg: BackendSettings) -> dict[str, Any]:
    paths = get_resolved_storage_paths()
    users_ok = path_is_writable_file_location(paths.auth_users_path)
    broker_ok = path_is_writable_file_location(paths.broker_accounts_db_path)
    data_ok = directory_is_writable(paths.backend_data_dir)
    backend_data_dir = str(paths.backend_data_dir)
    suspicious = ("/tmp/" in backend_data_dir) or ("\\temp\\" in backend_data_dir.lower()) or ("tmp\\" in backend_data_dir.lower())
    warning = ""
    if not data_ok or not users_ok or not broker_ok:
        warning = (
            "저장소 쓰기 불가 경고: users.json/broker_accounts.db/backend_data_dir 중 일부가 writable=false 입니다. "
            "Render Persistent Disk(BACKEND_DATA_DIR) 연결을 확인하세요."
        )
    elif suspicious and (cfg.app_env or "").lower() == "production":
        warning = (
            "BACKEND_DATA_DIR 가 임시 경로로 보입니다. Render 재시작 시 users.json/broker_accounts.db/paper 상태가 유실될 수 있습니다. "
            "Persistent Disk 경로를 BACKEND_DATA_DIR 로 설정하세요."
        )
    return {
        "backend_data_dir": backend_data_dir,
        "backend_data_dir_writable": data_ok,
        "users_json_writable": users_ok,
        "broker_accounts_db_writable": broker_ok,
        "warning": warning,
    }


def _tail_text_lines(path: Path, *, max_lines: int = 30) -> list[str]:
    if not path.is_file() or max_lines <= 0:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    return lines[-max_lines:]


def _probe_broker(cfg: BackendSettings) -> dict[str, Any]:
    global _broker_probe_cache
    now = time.monotonic()
    if _broker_probe_cache is not None:
        ts, cached = _broker_probe_cache
        if now - ts < _BROKER_PROBE_TTL_SEC:
            return dict(cached)

    api_base = resolved_kis_api_base_url(cfg)
    issues = validate_kis_inputs(
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        account_no="",
        account_product_code="",
        base_url=api_base,
        require_account=False,
    )
    if issues:
        out = {
            "ok": False,
            "status": "misconfigured",
            "message": " / ".join(issues),
            "kis_api_base": api_base,
            "trading_mode": cfg.trading_mode,
            "token_ok": False,
        }
        _broker_probe_cache = (now, out)
        return out
    tr = issue_access_token(
        app_key=cfg.kis_app_key,
        app_secret=cfg.kis_app_secret,
        base_url=api_base,
        timeout_sec=6,
    )
    ok = bool(tr.ok and tr.access_token)
    out = {
        "ok": ok,
        "status": "connected" if ok else "error",
        "message": (tr.message or "") if not ok else "token_ok",
        "kis_api_base": api_base,
        "trading_mode": cfg.trading_mode,
        "token_ok": ok,
        "error_code": getattr(tr, "error_code", None),
    }
    _broker_probe_cache = (time.monotonic(), out)
    return out


def _map_system_status(runtime_status: dict[str, Any]) -> str:
    st = str(runtime_status.get("engine_state") or "stopped")
    alive = bool(runtime_status.get("loop_thread_alive"))
    if st == "risk_off":
        return "risk-off"
    if not alive:
        return "stopped"
    if st in ("running", "premarket", "afterhours", "idle"):
        return "running"
    return "stopped"


def _account_status_from_broker(probe: dict[str, Any]) -> str:
    if probe.get("status") == "connected" and probe.get("token_ok"):
        return "connected"
    if probe.get("status") == "misconfigured":
        return "limited"
    return "disconnected"


def _risk_banner_from_aggregate(
    risk_st: dict[str, Any],
    runtime_st: dict[str, Any],
    portfolio_warnings: list[str],
    portfolio_sync_flag: bool,
    broker_probe: dict[str, Any],
    user_broker_snap: dict[str, Any] | None,
) -> dict[str, str]:
    chain_ok = _broker_chain_ok(broker_probe, user_broker_snap)
    if not chain_ok:
        if user_broker_snap and str(user_broker_snap.get("connection_status") or "") != "success":
            msg = user_broker_snap.get("connection_message") or "연결되지 않음"
            return {"level": "critical", "message": f"앱 등록 브로커: {msg}"}
        return {
            "level": "critical",
            "message": f"브로커(서버 런타임 .env KIS): {broker_probe.get('message') or broker_probe.get('status')}",
        }
    if str(runtime_st.get("engine_state")) == "risk_off":
        return {
            "level": "critical",
            "message": "런타임 엔진 RISK_OFF — /api/runtime-engine/risk-reset 후 점검",
        }
    if portfolio_sync_flag:
        return {
            "level": "critical",
            "message": "포트폴리오 동기화 연속 실패 임계 도달 — sync_risk_review.flag 확인",
        }
    if portfolio_warnings:
        return {
            "level": "warning",
            "message": f"포지션 불일치·리플레이 경고 {len(portfolio_warnings)}건 — POST /api/portfolio/sync",
        }
    events = risk_st.get("recent_events") or []
    audits = risk_st.get("recent_order_audits") or []
    if events:
        last = events[-1]
        code = str(last.get("reason_code") or last.get("event_type") or last.get("type") or "event")
        msg = str(last.get("reason") or last.get("note") or last.get("last_error") or "")
        level = "critical" if "FAIL" in code or "SYSTEM" in code or "risk_off" in code.lower() else "warning"
        return {"level": level, "message": f"[{code}] {msg}".strip()}
    if audits:
        last = audits[-1]
        d = last.get("decision") or {}
        if d.get("approved") is False:
            return {
                "level": "warning",
                "message": f"최근 주문 거부: {d.get('reason_code')} — {d.get('reason', '')}",
            }
    if int(runtime_st.get("failure_streak") or 0) > 0:
        return {
            "level": "warning",
            "message": f"런타임 실패 누적 streak={runtime_st.get('failure_streak')} (max={runtime_st.get('max_failures')})",
        }
    return {"level": "info", "message": "리스크·연결 상태 양호 (최근 치명 이벤트 없음)"}


def _server_runtime_account_ready() -> bool:
    """runtime_engine 장중 루프가 KisPaperBroker 를 만들기 위해 필요한 서버 .env 계좌."""
    try:
        from app.config import get_settings

        acfg = get_settings()
        return bool(acfg.resolved_account_no and acfg.resolved_account_product_code)
    except Exception:
        return False


def _server_runtime_banner(broker_probe: dict[str, Any], user_broker_snap: dict[str, Any] | None) -> dict[str, str]:
    if not _server_runtime_account_ready():
        return {
            "level": "critical",
            "title": "서버 runtime_engine 미구성",
            "message": (
                "서버 .env 에 KIS_ACCOUNT_NO · KIS_ACCOUNT_PRODUCT_CODE(또는 ACCOUNT_NUMBER/ACCOUNT_PRODUCT_CODE)가 없으면 "
                "runtime_engine 장중 세션 루프가 동작하지 않습니다. "
                "앱에 저장한 사용자 Paper 세션·브로커 계정과는 별개입니다."
            ),
        }
    ok = _broker_chain_ok(broker_probe, user_broker_snap)
    if ok:
        return {
            "level": "info",
            "title": "서버 런타임(.env) 상태",
            "message": "KIS 토큰·프로브 정상(서버 운영·포트폴리오 sync 기준).",
        }
    msg = str(broker_probe.get("message") or broker_probe.get("status") or "오류")
    return {
        "level": "critical",
        "title": "서버 런타임(.env) 상태",
        "message": f"토큰/설정 문제: {msg} — 앱 Paper 세션과는 별도 계정입니다.",
    }


def _user_paper_banner(paper_st: dict[str, Any], psd: dict[str, Any] | None) -> dict[str, str]:
    if paper_st.get("status") not in ("running", "risk_off") or not paper_st.get("user_session_active"):
        return {
            "level": "info",
            "title": "사용자 Paper 세션 상태",
            "message": "Paper 세션 미실행 — 미체결/체결/포지션은 서버 sync 기준으로 표시될 수 있습니다.",
        }
    err = str(paper_st.get("last_error") or "").strip()
    if err:
        return {
            "level": "critical",
            "title": "사용자 Paper 세션 상태",
            "message": f"틱 오류: {err}",
        }
    if psd and int(psd.get("failure_streak") or 0) > 0:
        return {
            "level": "warning",
            "title": "사용자 Paper 세션 상태",
            "message": f"실패 연속 {psd.get('failure_streak')} (서버 .env 실패와 무관)",
        }
    return {
        "level": "info",
        "title": "사용자 Paper 세션 상태",
        "message": "세션 실행 중 — 미체결·체결·포지션·후보는 앱 모의 계정 기준입니다.",
    }


def _recent_logs_aggregate(cfg: BackendSettings) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in _tail_text_lines(Path(cfg.runtime_error_log_path), max_lines=25):
        out.append({"source": "runtime_engine_log", "level": "error", "message": line})
    for row in read_jsonl_tail_risk(cfg.risk_events_jsonl, max_lines=8):
        out.append(
            {
                "source": "risk_events",
                "level": "warning",
                "message": json.dumps(row, ensure_ascii=False)[:500],
            }
        )
    return out[-40:]


def _safe_open_orders() -> tuple[list[dict[str, Any]], str | None]:
    global _open_orders_cache
    now = time.monotonic()
    if _open_orders_cache is not None:
        ts, rows, err = _open_orders_cache
        if now - ts < _OPEN_ORDERS_TTL_SEC:
            return list(rows), err
    try:
        eng = build_kis_mock_execution_engine()
        oo = eng.get_broker().get_open_orders()
        rows = [
            {
                "order_id": o.order_id,
                "symbol": o.symbol,
                "side": o.side,
                "quantity": o.quantity,
                "remaining_quantity": o.remaining_quantity,
                "price": o.price,
                "created_at": o.created_at.isoformat(),
            }
            for o in oo
        ]
        _open_orders_cache = (time.monotonic(), rows, None)
        return rows, None
    except Exception as exc:
        err = str(exc)
        _open_orders_cache = (time.monotonic(), [], err)
        return [], err


def _safe_recent_fills(cfg: BackendSettings, limit: int = 15) -> tuple[list[dict[str, Any]], str | None]:
    try:
        from backend.app.core.storage_paths import resolve_portfolio_data_dir

        p = resolve_portfolio_data_dir(cfg) / "fills.jsonl"
        raw = read_jsonl_tail(p, max_lines=min(500, limit * 5))
        items: list[dict[str, Any]] = []
        for r in reversed(raw):
            if len(items) >= limit:
                break
            odt = str(r.get("ord_dt") or "")
            otm = str(r.get("ord_tmd") or "")
            filled = f"{odt}{otm}" if odt else ""
            items.append(
                {
                    "fill_id": r.get("exec_id"),
                    "symbol": r.get("symbol"),
                    "side": r.get("side"),
                    "quantity": r.get("quantity"),
                    "price": r.get("price"),
                    "order_no": r.get("order_no"),
                    "strategy_id": r.get("strategy_id"),
                    "filled_at_compact": filled,
                }
            )
        return items, None
    except Exception as exc:
        return [], str(exc)


@router.get("/summary")
def dashboard_summary(authorization: str | None = Header(default=None)) -> dict[str, object]:
    cfg = get_backend_settings()
    now_iso = datetime.now(ZoneInfo("UTC")).isoformat()

    user = _try_current_user(authorization)
    user_broker_snap = _user_broker_snapshot(user.id) if user else None

    risk_st = build_public_risk_status(cfg)
    screener_snap = get_screener_engine().get_snapshot()
    screener_dash = screening_snapshot_to_dashboard_dict(screener_snap)

    rt = get_runtime_engine().status()
    broker_probe = _probe_broker(cfg)

    portfolio = load_last_snapshot(cfg)
    portfolio_warnings = list(portfolio.get("warnings") or []) if portfolio else []
    from backend.app.core.storage_paths import resolve_portfolio_data_dir

    sync_flag = (resolve_portfolio_data_dir(cfg) / "sync_risk_review.flag").is_file()

    equity = float(portfolio.get("equity") or 0.0) if portfolio else 0.0
    perf_aligned = build_dashboard_performance_block()
    today_pct = float(perf_aligned["today_return_pct"])
    monthly_pct = float(perf_aligned["monthly_return_pct"])
    cumulative_pct = float(perf_aligned["cumulative_return_pct"])

    realized = float(portfolio.get("realized_pnl") or 0.0) if portfolio else 0.0
    unrealized = float(portfolio.get("unrealized_pnl") or 0.0) if portfolio else 0.0
    position_count = int(portfolio.get("position_count") or 0) if portfolio else 0
    positions = list(portfolio.get("positions") or []) if portfolio else []

    sig_snap = get_swing_signal_engine().get_snapshot()
    strategy_block: dict[str, Any]
    if sig_snap is None:
        strategy_block = {
            "status": "empty",
            "message": "신호 엔진 스냅샷 없음 — POST /api/strategy-signals/evaluate",
        }
    else:
        j = snapshot_to_jsonable(sig_snap)
        strategy_block = {
            "status": "ok",
            "engine_id": "swing_signal_engine",
            "evaluated_at_utc": j.get("evaluated_at_utc"),
            "market_regime": j.get("market_regime"),
            "pending_signals_count": len(j.get("signals") or []),
            "symbols_diagnosed": len(j.get("per_symbol") or []),
            "top_signals": (j.get("signals") or [])[:5],
        }

    open_orders, orders_err = _safe_open_orders()
    recent_fills, fills_err = _safe_recent_fills(cfg, limit=15)

    paper_trading_status_domestic = _paper_trading_status()
    try:
        from backend.app.engine.paper_session_controller import get_paper_session_controller

        paper_trading_status_us = get_paper_session_controller().status_payload(market="us")
    except Exception as exc:
        paper_trading_status_us = {"status": "unknown", "error": str(exc)}
    paper_trading_status = dict(paper_trading_status_domestic)
    paper_session_dashboard: dict[str, Any] | None = None
    use_paper_dashboard = bool(
        user
        and str(paper_trading_status.get("session_user_id") or "") == user.id
        and paper_trading_status.get("status") == "running"
        and paper_trading_status.get("user_session_active")
    )
    if use_paper_dashboard:
        try:
            from backend.app.engine.paper_session_controller import get_paper_session_controller

            try:
                paper_session_dashboard = get_paper_session_controller().get_dashboard_payload(user.id, market="domestic")
            except TypeError:
                paper_session_dashboard = get_paper_session_controller().get_dashboard_payload(user.id)
        except Exception as exc:
            paper_session_dashboard = {"ok": False, "error": str(exc)}
    psd = paper_session_dashboard if isinstance(paper_session_dashboard, dict) and paper_session_dashboard.get("ok") else None

    if psd:
        open_orders = list(psd.get("open_orders") or [])
        orders_err = psd.get("open_orders_error")
        recent_fills = list(psd.get("recent_fills") or [])
        fills_err = psd.get("recent_fills_error")
        positions = list(psd.get("positions") or [])
        position_count = len(positions)
        screener_dash = dict(screener_dash)
        ranking_rows = psd.get("ranking") or []
        screener_dash["candidates"] = [
            {"symbol": r.get("symbol"), "total_score": r.get("score"), "reasons": list(r.get("reasons") or [])}
            for r in ranking_rows
        ]
        if psd.get("regime"):
            screener_dash["regime"] = psd.get("regime")
        strategy_block = dict(strategy_block)
        if psd.get("regime"):
            strategy_block["market_regime"] = psd.get("regime")
        strategy_block["paper_no_order_reason"] = psd.get("no_order_reason")
        strategy_block["paper_generated_order_count"] = psd.get("generated_order_count")

    store = TrackedOrderStore(cfg.order_tracked_store_json)
    tracked_active = len(filter_active_submitted(store.list_all()))

    persisted = rt.get("persisted") or {}
    last_hb = persisted.get("heartbeat_at") or (rt.get("volatile_summary") or {}).get("last_loop_at")

    server_rt_banner = _server_runtime_banner(broker_probe, user_broker_snap)
    paper_usr_banner = _user_paper_banner(paper_trading_status_domestic, psd)
    storage_diag = _storage_diagnostics(cfg)

    return {
        "updated_at_utc": now_iso,
        # --- flat fields (모바일·기존 클라이언트 호환) ---
        "mode": (cfg.trading_mode or "paper").strip().lower(),
        "live_execution_armed": is_live_order_execution_configured(cfg),
        "account_status": _account_status_from_broker(broker_probe),
        "today_return_pct": today_pct,
        "monthly_return_pct": monthly_pct,
        "cumulative_return_pct": cumulative_pct,
        "position_count": position_count,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "system_status": _map_system_status(rt),
        "risk_banner": _risk_banner_from_aggregate(
            risk_st, rt, portfolio_warnings, sync_flag, broker_probe, user_broker_snap
        ),
        "risk_limits_summary": risk_st["limits"],
        "screener": screener_dash,
        "performance_aligned": perf_aligned,
        # --- 운영 상세 ---
        "broker": broker_probe,
        "runtime_engine": {
            "engine_state": rt.get("engine_state"),
            "loop_thread_alive": rt.get("loop_thread_alive"),
            "failure_streak": rt.get("failure_streak"),
            "max_failures": rt.get("max_failures"),
            "loop_interval_sec": rt.get("loop_interval_sec"),
            "last_error": rt.get("last_error"),
            "market_phase_now": rt.get("market_phase_now"),
            "persisted": persisted,
            "last_loop_summary": (rt.get("volatile_summary") or {}).get("last_summary"),
            "last_kis_token_failure": rt.get("last_kis_token_failure"),
            "server_runtime_account_configured": _server_runtime_account_ready(),
        },
        "portfolio": {
            "synced": portfolio is not None,
            "updated_at_utc": portfolio.get("updated_at_utc") if portfolio else None,
            "equity": equity,
            "cash": float(portfolio.get("cash") or 0.0) if portfolio else 0.0,
            "daily_pnl_krw": float(portfolio.get("daily_pnl_krw") or 0.0) if portfolio else 0.0,
            "cumulative_pnl_krw": float(portfolio.get("cumulative_pnl_krw") or 0.0) if portfolio else 0.0,
            "warnings": portfolio_warnings,
            "mismatch_count": len(portfolio.get("mismatches") or []) if portfolio else 0,
            "new_fills_last_sync": int(portfolio.get("new_fills_this_sync") or 0) if portfolio else 0,
        },
        "positions": positions,
        "open_orders": open_orders,
        "open_orders_error": orders_err,
        "recent_fills": recent_fills,
        "recent_fills_error": fills_err,
        "order_engine": {
            "tracked_active_submitted": tracked_active,
        },
        "risk": {
            "limits": risk_st["limits"],
            "policy_notes": risk_st.get("policy_notes"),
            "recent_order_audits_tail": risk_st.get("recent_order_audits"),
            "recent_events_tail": risk_st.get("recent_events"),
        },
        "market_regime": {
            "screener_regime": screener_dash.get("regime"),
            "signal_engine_regime": strategy_block.get("market_regime"),
            "screener_blocked": bool(screener_dash.get("blocked")),
        },
        "strategy_signals": strategy_block,
        "selected_candidates": screener_dash.get("candidates") or [],
        "last_heartbeat_utc": last_hb,
        "recent_logs": _recent_logs_aggregate(cfg),
        "alerts": {
            "portfolio_sync_risk_review": sync_flag,
            "runtime_risk_off": str(rt.get("engine_state")) == "risk_off",
            "broker_ok": _broker_chain_ok(broker_probe, user_broker_snap),
            "user_broker_connected": bool(
                user_broker_snap and user_broker_snap.get("connection_status") == "success"
            ),
        },
        "user_broker_account": user_broker_snap,
        "server_runtime_banner": server_rt_banner,
        "user_paper_banner": paper_usr_banner,
        "storage_diagnostics": storage_diag,
        "paper_session_dashboard": paper_session_dashboard,
        "market_status_cards": _build_market_status_cards(paper_trading_status_domestic, paper_trading_status_us, psd, rt),
        "active_paper_market": (
            "domestic"
            if paper_trading_status.get("user_session_active")
            and str(paper_trading_status.get("status") or "") in ("running", "risk_off")
            else None
        ),
        "dashboard_scope": {
            "positions_open_orders_fills": "user_paper_session" if psd else "server_env",
            "paper_active": bool(psd),
        },
        "value_sources": {
            "today_return_pct": "performance_aggregate.build_dashboard_performance_block (pnl_history, /performance 동일)",
            "monthly_return_pct": "performance_aggregate (equity curve, /performance 동일)",
            "cumulative_return_pct": "performance_aggregate (equity curve, /performance 동일)",
            "performance_aligned": "fills FIFO + KIS/KRX 비율·체결 컬럼, pnl_history 수익률",
            "realized_pnl": "portfolio_snapshot.realized_pnl",
            "unrealized_pnl": "portfolio_snapshot.unrealized_pnl",
            "current_positions": (
                "paper_session_user_kis (GET /api/paper-trading/dashboard-data)"
                if psd
                else "portfolio_snapshot.positions (KIS balance + fills replay merge)"
            ),
            "open_orders": (
                "paper_session_user_kis" if psd else "kis_broker_get_open_orders_via_order_engine (server runtime account)"
            ),
            "recent_fills": "paper_session_user_kis" if psd else "portfolio_data/fills.jsonl",
            "broker_connection_status": "broker_probe(server_env) + user_broker_account(connection_status)",
            "runtime_engine_status": "runtime_engine.status()",
            "risk_status": "risk.service.build_public_risk_status()",
            "selected_candidates": (
                "paper_tick_ranking" if psd else "screener_engine.latest_snapshot.candidates"
            ),
            "current_market_regime": "strategy_signal_snapshot.market_regime + screener_snapshot.regime",
        },
        "data_quality": {
            "open_orders_user_scoped": bool(psd),
            "recent_fills_user_scoped": bool(psd),
            "monthly_return_estimated": False,
            "regime_dual_source": not bool(psd),
        },
        "dashboard_todos": _dashboard_todos(),
        "paper_trading": {
            "domestic": paper_trading_status_domestic,
            "us": paper_trading_status_us,
        },
        "paper_trading_demo": paper_trading_status_domestic,  # backward compatibility
        "broker_cross_checks": {
            "server_env_token_ok": bool(broker_probe.get("token_ok")),
            "app_broker_connection_ok": bool(
                user_broker_snap and user_broker_snap.get("connection_status") == "success"
            ),
            "server_env_mismatch_warning": bool(
                user_broker_snap
                and user_broker_snap.get("connection_status") == "success"
                and not broker_probe.get("token_ok")
            ),
            "paper_dashboard_note": (
                "Paper 세션 실행 중에는 미체결·체결·포지션·랭킹 후보가 사용자 모의 계정 기준으로 표시됩니다. "
                "서버 .env 토큰 실패는 Paper 틱과 별개일 수 있습니다."
            ),
        },
    }


@router.get("/portfolio-snapshot")
def dashboard_portfolio_snapshot() -> dict[str, Any]:
    """스냅샷 없어도 200 — 대시보드 빈 상태 표시용."""
    cfg = get_backend_settings()
    snap = load_last_snapshot(cfg)
    return {
        "synced": snap is not None,
        "snapshot": snap,
        "updated_at_utc": snap.get("updated_at_utc") if snap else None,
    }


@router.get("/recent-fills")
def dashboard_recent_fills(limit: int = Query(default=15, ge=1, le=200)) -> dict[str, Any]:
    items, err = _safe_recent_fills(get_backend_settings(), limit=limit)
    return {"items": items, "error": err, "source": "portfolio_data/fills.jsonl"}


@router.get("/risk-status")
def dashboard_risk_status() -> dict[str, Any]:
    return build_public_risk_status(get_backend_settings())


@router.get("/runtime-status")
def dashboard_runtime_status() -> dict[str, Any]:
    rt = get_runtime_engine().status()
    persisted = rt.get("persisted") or {}
    last_hb = persisted.get("heartbeat_at") or (rt.get("volatile_summary") or {}).get("last_loop_at")
    return {
        "updated_at_utc": datetime.now(ZoneInfo("UTC")).isoformat(),
        "system_status": _map_system_status(rt),
        "last_heartbeat_utc": last_hb,
        "runtime_engine": {
            "engine_state": rt.get("engine_state"),
            "loop_thread_alive": rt.get("loop_thread_alive"),
            "failure_streak": rt.get("failure_streak"),
            "max_failures": rt.get("max_failures"),
            "loop_interval_sec": rt.get("loop_interval_sec"),
            "market_phase_now": rt.get("market_phase_now"),
            "last_error": rt.get("last_error"),
            "persisted": persisted,
            "last_loop_summary": (rt.get("volatile_summary") or {}).get("last_summary"),
            "last_kis_token_failure": rt.get("last_kis_token_failure"),
            "server_runtime_account_configured": _server_runtime_account_ready(),
        },
    }


@router.get("/broker-status")
def dashboard_broker_status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    cfg = get_backend_settings()
    probe = _probe_broker(cfg)
    user = _try_current_user(authorization)
    u_snap = _user_broker_snapshot(user.id) if user else None
    return {
        "updated_at_utc": datetime.now(ZoneInfo("UTC")).isoformat(),
        "server_env_broker": probe,
        "user_broker_account": u_snap,
        "broker_chain_ok": _broker_chain_ok(probe, u_snap),
    }


def _paper_trading_status() -> dict[str, Any]:
    """앱 Paper 세션(KIS 모의·사용자 자격). 전역 RuntimeEngine 과 별도. (기본: domestic)"""
    try:
        from backend.app.engine.paper_session_controller import get_paper_session_controller

        return get_paper_session_controller().status_payload(market="domestic")
    except Exception as exc:
        return {"status": "unknown", "error": str(exc)}
