from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.clients.kis_client import KISClientError, sanitize_kis_params_for_log
from backend.app.clients.kis_client import build_kis_client_for_paper_user
from backend.app.engine.runtime_engine import get_runtime_engine
from backend.app.engine.paper_session_controller import get_paper_session_controller

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
    try:
        ctrl.start(user.id, payload.strategy_id.strip(), market=payload.market)
    except ValueError as exc:
        code = str(exc)
        snap = ctrl.paper_token_ensure_snapshot()
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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="final_betting_v1 은 서버 환경에서 PAPER_FINAL_BETTING_ENABLED=true 로 켠 뒤 시작할 수 있습니다.",
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
    return {"ok": True, **ctrl.status_payload(), "runtime_engine_start": runtime_start}


@router.post("/stop")
def stop_paper_trading(
    authorization: str | None = Header(default=None),
    market: str | None = Query(
        default=None,
        description="모바일에서 domestic | us 로 명시(예약). 현재는 쿼리를 읽기만 하고 동작은 동일.",
    ),
) -> dict[str, object]:
    user = _paper_user(authorization)
    ctrl = get_paper_session_controller()
    try:
        ctrl.stop(user.id)
    except RuntimeError as exc:
        if "NOT_OWNER" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="이 Paper 세션을 시작한 사용자만 중지할 수 있습니다.",
            ) from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    runtime_stop = get_runtime_engine().stop()
    return {"ok": True, **ctrl.status_payload(), "runtime_engine_stop": runtime_stop}


@router.post("/risk-reset")
def paper_trading_risk_reset(
    authorization: str | None = Header(default=None),
    market: str | None = Query(default=None, description="예약: domestic | us"),
) -> dict[str, Any]:
    """paper 세션 risk_off 해제(시작한 사용자만)."""
    user = _paper_user(authorization)
    ctrl = get_paper_session_controller()
    try:
        out = ctrl.risk_reset(user.id)
    except RuntimeError as exc:
        if "NOT_OWNER" in str(exc):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="세션 소유자만 risk-reset 할 수 있습니다.") from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("message") or "risk_reset rejected")
    return out


@router.get("/status")
def get_paper_trading_status(
    market: str | None = Query(default=None, description="예약: domestic | us"),
) -> dict[str, object]:
    return {
        **get_paper_session_controller().status_payload(),
        "runtime_engine": get_runtime_engine().status(),
    }


@router.get("/engine/status")
def paper_engine_status() -> dict[str, Any]:
    """Paper 전용 런타임(사용자 모의 루프) 상태 — `/api/runtime-engine` 과 구분."""
    return get_paper_session_controller().status_payload()


@router.get("/positions")
def get_paper_positions(
    market: str | None = Query(default=None, description="예약: domestic | us"),
) -> dict[str, object]:
    items = get_paper_session_controller().get_positions()
    return {"items": items}


@router.get("/pnl")
def get_paper_pnl(
    market: str | None = Query(default=None, description="예약: domestic | us"),
) -> dict[str, object]:
    return get_paper_session_controller().pnl_from_last_report()


@router.get("/diagnostics")
def get_paper_diagnostics(
    market: str | None = Query(default=None, description="예약: domestic | us"),
) -> dict[str, object]:
    """Paper 세션 마지막 KIS 실패 맥락·토큰 출처(민감값 제외)."""
    return get_paper_session_controller().diagnostics_payload()


@router.get("/dashboard-data")
def get_paper_dashboard_data(
    authorization: str | None = Header(default=None),
    market: str | None = Query(default=None, description="예약: domestic | us"),
) -> dict[str, object]:
    """사용자 Paper 계정 기준 포지션·미체결·체결·틱 리포트(대시보드와 동일 소스)."""
    user = _paper_user(authorization)
    return get_paper_session_controller().get_dashboard_payload(user.id)


@router.get("/logs")
def get_paper_logs(
    market: str | None = Query(default=None, description="예약: domestic | us"),
) -> dict[str, object]:
    ctrl = get_paper_session_controller()
    logs = ctrl.get_logs()
    if not logs:
        logs = [
            {
                "ts": "",
                "level": "info",
                "message": "Paper 로그 없음 — 시작 후 틱이 돌면 누적됩니다.",
            }
        ]
    return {"items": logs[:40]}
