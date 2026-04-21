from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.clients.kis_client import KISClientError, sanitize_kis_params_for_log
from app.config import paper_final_betting_diagnostics
from backend.app.clients.kis_client import build_kis_client_for_paper_user
from backend.app.engine.runtime_engine import get_runtime_engine
from backend.app.engine.paper_session_controller import get_paper_session_controller, normalize_paper_market_param

from .auth_routes import get_current_user_from_auth_header
from .broker_routes import get_broker_service

router = APIRouter(prefix="/paper-trading", tags=["paper-trading"])


def _paper_user(authorization: str | None):
    try:
        return get_current_user_from_auth_header(authorization)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except HTTPException:
        raise


def _optional_pref_user_id(authorization: str | None) -> str | None:
    """Bearer가 유효하면 사용자 id, 아니면 None (Paper status/diagnostics용 비차단)."""
    if not authorization:
        return None
    try:
        return get_current_user_from_auth_header(authorization).id
    except (ValueError, HTTPException):
        return None


def _has_market_hub(ctrl: object) -> bool:
    return hasattr(ctrl, "controller_for_market")


def _market_ctrl(ctrl: object, market: str | None):
    if _has_market_hub(ctrl):
        return ctrl.controller_for_market(market)  # type: ignore[attr-defined]
    return ctrl


def _require_broker_ready_for_start(user_id: str) -> None:
    svc = get_broker_service()
    try:
        account = svc.get_account(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="브로커 계정이 등록되어 있지 않습니다. 설정에서 한국투자 정보를 저장한 뒤 다시 시도하세요.",
        ) from None
    if account.connection_status != "success":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="한국투자 연결 테스트에 성공한 뒤에만 모의 자동매매를 시작할 수 있습니다. 설정 화면에서 「연결 테스트」를 실행하세요.",
        )


def _run_balance_preflight(user_id: str, *, market: str | None = None) -> dict[str, object]:
    svc = get_broker_service()
    app_key, app_secret, account_no, product_code, trading_mode = svc.get_plain_credentials(user_id)
    api_base = svc._resolve_kis_api_base(trading_mode)
    if "openapivts" not in (api_base or ""):
        return {
            "ok": False,
            "failure_kind": "invalid_mode",
            "error": "paper 모드(openapivts)만 허용됩니다.",
        }
    tok = svc.ensure_cached_token_for_paper_start(user_id)
    if not tok.ok or not tok.access_token:
        return {
            "ok": False,
            "failure_kind": "token_not_ready",
            "error": tok.message,
            "token_error_code": tok.token_error_code,
        }
    client = build_kis_client_for_paper_user(
        base_url=api_base,
        access_token=tok.access_token,
        app_key=app_key,
        app_secret=app_secret,
    )
    mkt = (market or "domestic").strip().lower()
    if mkt in ("us", "usa", "nyse", "nasdaq", "us_equity", "us_equities"):
        req_params = {
            "CANO": account_no,
            "ACNT_PRDT_CD": product_code,
            "OVRS_EXCG_CD": "NASD",
            "TR_CRCY_CD": "USD",
        }
        tr_id = client._resolve_tr_id(
            paper_tr_id=client.overseas_tr_ids.balance_paper,
            live_tr_id=client.overseas_tr_ids.balance_live,
        )
        path = client.overseas_paths.inquire_balance
        try:
            client.get_overseas_inquire_balance(
                account_no=account_no,
                account_product_code=product_code,
                ovrs_excg_cd="NASD",
                tr_crcy_cd="USD",
            )
        except KISClientError as exc:
            ctx = getattr(exc, "kis_context", {}) or {}
            return {
                "ok": False,
                "failure_kind": "kis_error",
                "error": str(exc),
                "path": ctx.get("path") or path,
                "tr_id": ctx.get("tr_id") or tr_id,
                "sanitized_params": ctx.get("params") or sanitize_kis_params_for_log(req_params),
                "http_status": ctx.get("http_status"),
            }
        return {
            "ok": True,
            "path": path,
            "tr_id": tr_id,
            "sanitized_params": sanitize_kis_params_for_log(req_params),
        }

    req_params = {
        "CANO": account_no,
        "ACNT_PRDT_CD": product_code,
        "AFHR_FLPR_YN": "N",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01",
    }
    tr_id = client._resolve_tr_id(paper_tr_id=client.tr_ids.balance_paper, live_tr_id=client.tr_ids.balance_live)
    path = client.endpoints.get_balance
    try:
        client.get_balance(account_no=account_no, account_product_code=product_code)
        return {
            "ok": True,
            "path": path,
            "tr_id": tr_id,
            "sanitized_params": sanitize_kis_params_for_log(req_params),
        }
    except KISClientError as exc:
        ctx = getattr(exc, "kis_context", {}) or {}
        return {
            "ok": False,
            "failure_kind": "kis_error",
            "error": str(exc),
            "path": ctx.get("path") or path,
            "tr_id": ctx.get("tr_id") or tr_id,
            "sanitized_params": ctx.get("params") or sanitize_kis_params_for_log(req_params),
            "http_status": ctx.get("http_status"),
        }


class StartPaperTradingRequest(BaseModel):
    strategy_id: str = Field(min_length=2, max_length=64)
    link_runtime_engine: bool = Field(
        default=True,
        description="true 이면 paper start 시 전역 runtime engine도 함께 start",
    )
    market: str | None = Field(
        default=None,
        description="domestic | us — us 이면 해외주식(미국) Paper 틱 경로(동일 KIS 모의 자격).",
    )


@router.post("/start")
def start_paper_trading(
    payload: StartPaperTradingRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    """
    사용자 KIS **모의** 계정으로 Paper 세션 시작 (전역 RuntimeEngine 과 별도).
    브로커 trading_mode 가 paper 이고 연결 테스트 성공인 경우만 허용 — live 혼선 방지.
    """
    user = _paper_user(authorization)
    _require_broker_ready_for_start(user.id)
    preflight = _run_balance_preflight(user.id, market=payload.market)
    if not preflight.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "PAPER_BALANCE_PREFLIGHT_FAILED",
                "message": preflight.get("error") or "balance preflight failed",
                "failure_kind": preflight.get("failure_kind"),
                "path": preflight.get("path"),
                "tr_id": preflight.get("tr_id"),
                "sanitized_params": preflight.get("sanitized_params"),
                "http_status": preflight.get("http_status"),
            },
        )
    sid = payload.strategy_id.lower().strip()
    if sid == "live":
        raise HTTPException(status_code=400, detail="strategy_id 'live' 는 사용할 수 없습니다 (live 차단).")
    ctrl = get_paper_session_controller()
    slot = _market_ctrl(ctrl, payload.market)
    req_strategy_raw = payload.strategy_id.strip()
    mk_raw = (payload.market or "domestic").strip().lower()
    req_market_norm = (
        "us"
        if mk_raw in ("us", "usa", "nyse", "nasdaq", "us_equity", "us_equities")
        else "domestic"
    )
    try:
        ctrl.start(user.id, payload.strategy_id.strip(), market=req_market_norm)
    except ValueError as exc:
        code = str(exc)
        snap = slot.paper_token_ensure_snapshot()
        if code == "TOKEN_RATE_LIMIT_WAIT":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "TOKEN_RATE_LIMIT_WAIT",
                    "message": snap.get("start_blocked_reason") or "KIS 접근 토큰 발급 제한 — 잠시 후 다시 시도하세요.",
                    "token_error_code": snap.get("token_error_code"),
                    "token_cache_persisted": snap.get("token_cache_persisted"),
                },
            ) from exc
        if code == "PAPER_TOKEN_NOT_READY":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "PAPER_TOKEN_NOT_READY",
                    "message": snap.get("start_blocked_reason") or "재사용 가능한 접근 토큰을 확보하지 못했습니다. 연결 테스트 후 다시 시도하세요.",
                    "token_error_code": snap.get("token_error_code"),
                    "cache_miss_reason": snap.get("cache_miss_reason"),
                },
            ) from exc
        if code == "PAPER_MODE_REQUIRED":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="앱 브로커가 paper 모드여야 Paper 자동매매를 시작할 수 있습니다. live 계정은 Paper에서 시작할 수 없습니다.",
            ) from exc
        if code == "BROKER_NOT_READY":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="브로커 연결 테스트를 먼저 통과하세요.",
            ) from exc
        if code == "MOCK_HOST_REQUIRED":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="모의투자 API 호스트(openapivts)만 허용됩니다. 브로커 설정을 확인하세요.",
            ) from exc
        if code == "BROKER_NOT_REGISTERED":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="브로커 계정이 등록되어 있지 않습니다.",
            ) from exc
        if code == "FINAL_BETTING_DISABLED":
            fb_diag = paper_final_betting_diagnostics()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "FINAL_BETTING_DISABLED",
                    "message": "final_betting_v1 은 서버에서 종가베팅 플래그가 켜져 있어야 합니다.",
                    "hint": "PAPER_FINAL_BETTING_ENABLED=true (또는 FINAL_BETTING_ENABLED / final_betting_enabled)",
                    "root_cause": (
                        "environment_variables_absent"
                        if fb_diag.get("final_betting_env_unset_in_process")
                        else "environment_or_settings_false"
                    ),
                    "deployment_fix_ko": str(fb_diag.get("final_betting_deploy_hint_ko") or "").strip()
                    or (
                        "백엔드에 PAPER_FINAL_BETTING_ENABLED=true 를 설정한 뒤 서비스를 재시작하세요. "
                        "(앱에서 다시 시작만으로는 서버 환경이 바뀌지 않습니다.)"
                    ),
                    "request_strategy_id": req_strategy_raw,
                    "request_market": payload.market,
                    "paper_start_diagnostics": slot.last_start_diagnostics_snapshot(),
                    "strategy_implemented": True,
                    "settings_not_reflected": bool(
                        (fb_diag.get("settings_cache_mismatch") or False)
                    ),
                    "final_betting": fb_diag,
                },
            ) from exc
        raise HTTPException(status_code=400, detail=code) from exc
    except RuntimeError as exc:
        if "OTHER_SESSION_ACTIVE" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="다른 사용자의 Paper 세션이 실행 중입니다. 해당 세션 중지 후 다시 시도하세요.",
            ) from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    runtime_start: dict[str, Any] | None = None
    if payload.link_runtime_engine:
        runtime_start = get_runtime_engine().start()
    return {
        "ok": True,
        "start_request_echo": {
            "strategy_id": req_strategy_raw,
            "market": req_market_norm,
        },
        **ctrl.status_payload(market=req_market_norm, pref_user_id=user.id),
        "runtime_engine_start": runtime_start,
    }


@router.post("/stop")
def stop_paper_trading(
    authorization: str | None = Header(default=None),
    market: str | None = Query(
        default=None,
        description="domestic | us",
    ),
) -> dict[str, object]:
    user = _paper_user(authorization)
    ctrl = get_paper_session_controller()
    try:
        if _has_market_hub(ctrl):
            ctrl.stop(user.id, market=market)  # type: ignore[call-arg]
        else:
            ctrl.stop(user.id)  # type: ignore[call-arg]
    except RuntimeError as exc:
        if "NOT_OWNER" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="이 Paper 세션을 시작한 사용자만 중지할 수 있습니다.",
            ) from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    runtime_stop = get_runtime_engine().stop()
    mk = normalize_paper_market_param(market)
    if _has_market_hub(ctrl):
        st = ctrl.status_payload(market=mk, pref_user_id=user.id)  # type: ignore[call-arg]
    else:
        st = ctrl.status_payload(pref_user_id=user.id)  # type: ignore[call-arg]
    return {"ok": True, **st, "runtime_engine_stop": runtime_stop}


@router.post("/risk-reset")
def paper_trading_risk_reset(
    authorization: str | None = Header(default=None),
    market: str | None = Query(default=None, description="domestic | us"),
) -> dict[str, Any]:
    """paper 세션 risk_off 해제(시작한 사용자만)."""
    user = _paper_user(authorization)
    ctrl = get_paper_session_controller()
    try:
        if _has_market_hub(ctrl):
            out = ctrl.risk_reset(user.id, market=market)  # type: ignore[call-arg]
        else:
            out = ctrl.risk_reset(user.id)  # type: ignore[call-arg]
    except RuntimeError as exc:
        if "NOT_OWNER" in str(exc):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="세션 소유자만 risk-reset 할 수 있습니다.") from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("message") or "risk_reset rejected")
    return out


@router.post("/manual-override-toggle")
def paper_trading_manual_override_toggle(
    authorization: str | None = Header(default=None),
    market: str | None = Query(default=None),
) -> dict[str, object]:
    user = _paper_user(authorization)
    ctrl = get_paper_session_controller()
    try:
        if _has_market_hub(ctrl):
            return ctrl.toggle_manual_override(user.id, market=market)  # type: ignore[call-arg]
        return ctrl.toggle_manual_override(user.id)  # type: ignore[call-arg]
    except RuntimeError as exc:
        if "NOT_OWNER" in str(exc):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="세션 소유자만 수동 오버라이드를 변경할 수 있습니다.") from exc
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get("/capabilities")
def get_paper_trading_capabilities() -> dict[str, object]:
    """앱이 US Paper·종가베팅 가능 여부를 동적으로 판단할 때 사용(네트워크 호출 없음)."""
    fb = paper_final_betting_diagnostics()
    return {
        "us_paper_supported": True,
        "us_symbol_search_supported": True,
        "us_strategies_supported": True,
        "final_betting_enabled_effective": fb.get("final_betting_enabled_effective"),
        "final_betting_env_sources": fb.get("final_betting_env_sources"),
        "paper_final_betting_cache_mismatch": fb.get("settings_cache_mismatch"),
    }


@router.get("/status")
def get_paper_trading_status(
    market: str | None = Query(default=None, description="domestic | us — 세션과 다르면 market_mismatch"),
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    ctrl = get_paper_session_controller()
    mk = normalize_paper_market_param(market)
    ok_m, req, sess = _market_ctrl(ctrl, mk).market_request_matches(mk)  # type: ignore[call-arg]
    pref_uid = _optional_pref_user_id(authorization)
    if _has_market_hub(ctrl):
        st = ctrl.status_payload(market=mk, pref_user_id=pref_uid)  # type: ignore[call-arg]
    else:
        st = ctrl.status_payload(pref_user_id=pref_uid)  # type: ignore[call-arg]
    return {
        **st,
        "requested_market": req,
        "paper_market_normalized": sess,
        "market_mismatch": not ok_m,
        "runtime_engine": get_runtime_engine().status(),
    }


@router.get("/engine/status")
def paper_engine_status(
    authorization: str | None = Header(default=None),
    market: str | None = Query(default=None, description="domestic | us"),
) -> dict[str, Any]:
    """Paper 전용 런타임(사용자 모의 루프) 상태 — `/api/runtime-engine` 과 구분."""
    pref_uid = _optional_pref_user_id(authorization)
    ctrl = get_paper_session_controller()
    if _has_market_hub(ctrl):
        return ctrl.status_payload(market=market, pref_user_id=pref_uid)  # type: ignore[call-arg]
    return ctrl.status_payload(pref_user_id=pref_uid)  # type: ignore[call-arg]


@router.get("/positions")
def get_paper_positions(
    market: str | None = Query(default=None, description="domestic | us"),
) -> dict[str, object]:
    ctrl = get_paper_session_controller()
    if _has_market_hub(ctrl):
        return ctrl.get_positions_payload(market=market)  # type: ignore[call-arg]
    return ctrl.get_positions_payload(market=market)  # type: ignore[call-arg]


@router.get("/pnl")
def get_paper_pnl(
    market: str | None = Query(default=None, description="domestic | us"),
) -> dict[str, object]:
    ctrl = get_paper_session_controller()
    if _has_market_hub(ctrl):
        return ctrl.pnl_payload(market=market)  # type: ignore[call-arg]
    return ctrl.pnl_payload(market=market)  # type: ignore[call-arg]


@router.get("/diagnostics")
def get_paper_diagnostics(
    market: str | None = Query(default=None, description="domestic | us"),
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    """Paper 세션 마지막 KIS 실패 맥락·토큰 출처(민감값 제외)."""
    pref_uid = _optional_pref_user_id(authorization)
    ctrl = get_paper_session_controller()
    if _has_market_hub(ctrl):
        return ctrl.diagnostics_payload(market=market, pref_user_id=pref_uid)  # type: ignore[call-arg]
    return ctrl.diagnostics_payload(pref_user_id=pref_uid)  # type: ignore[call-arg]


@router.get("/dashboard-data")
def get_paper_dashboard_data(
    authorization: str | None = Header(default=None),
    market: str | None = Query(default=None, description="domestic | us"),
) -> dict[str, object]:
    """사용자 Paper 계정 기준 포지션·미체결·체결·틱 리포트(대시보드와 동일 소스)."""
    user = _paper_user(authorization)
    ctrl = get_paper_session_controller()
    if _has_market_hub(ctrl):
        return ctrl.get_dashboard_payload(user.id, market=market)  # type: ignore[call-arg]
    return ctrl.get_dashboard_payload(user.id, market=market)  # type: ignore[call-arg]


@router.get("/logs")
def get_paper_logs(
    market: str | None = Query(default=None, description="domestic | us"),
) -> dict[str, object]:
    ctrl = get_paper_session_controller()
    if _has_market_hub(ctrl):
        out = ctrl.logs_payload(market=market)  # type: ignore[call-arg]
    else:
        out = ctrl.logs_payload(market=market)  # type: ignore[call-arg]
    logs = list(out.get("items") or [])
    if not logs:
        logs = [
            {
                "ts": "",
                "level": "info",
                "message": "Paper 로그 없음 — 시작 후 틱이 돌면 누적됩니다.",
            }
        ]
    out["items"] = logs[:40]
    return out


class PaperMarketModeBody(BaseModel):
    manual_market_mode: str = Field(
        default="auto",
        description="auto | aggressive | neutral | defensive",
        min_length=2,
        max_length=16,
    )


@router.get("/market-mode")
def get_paper_market_mode(
    authorization: str | None = Header(default=None),
    market: str | None = Query(default=None, description="domestic | us"),
) -> dict[str, object]:
    user = _paper_user(authorization)
    ctrl = get_paper_session_controller()
    if _has_market_hub(ctrl):
        return ctrl.get_paper_market_mode(user.id, market=market)  # type: ignore[call-arg]
    return ctrl.get_paper_market_mode(user.id)  # type: ignore[call-arg]


@router.post("/market-mode")
def set_paper_market_mode(
    body: PaperMarketModeBody,
    authorization: str | None = Header(default=None),
    market: str | None = Query(default=None, description="domestic | us"),
) -> dict[str, object]:
    user = _paper_user(authorization)
    ctrl = get_paper_session_controller()
    if _has_market_hub(ctrl):
        return ctrl.set_paper_market_mode(user.id, body.manual_market_mode, market=market)  # type: ignore[call-arg]
    return ctrl.set_paper_market_mode(user.id, body.manual_market_mode)  # type: ignore[call-arg]
