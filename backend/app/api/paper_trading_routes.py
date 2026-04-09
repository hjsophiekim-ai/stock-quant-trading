from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

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


class StartPaperTradingRequest(BaseModel):
    strategy_id: str = Field(min_length=2, max_length=64)
    link_runtime_engine: bool = Field(
        default=True,
        description="true 이면 paper start 시 전역 runtime engine도 함께 start",
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
    sid = payload.strategy_id.lower().strip()
    if sid == "live":
        raise HTTPException(status_code=400, detail="strategy_id 'live' 는 사용할 수 없습니다 (live 차단).")
    ctrl = get_paper_session_controller()
    try:
        ctrl.start(user.id, payload.strategy_id.strip())
    except ValueError as exc:
        code = str(exc)
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
def stop_paper_trading(authorization: str | None = Header(default=None)) -> dict[str, object]:
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
def paper_trading_risk_reset(authorization: str | None = Header(default=None)) -> dict[str, Any]:
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
def get_paper_trading_status() -> dict[str, object]:
    return {
        **get_paper_session_controller().status_payload(),
        "runtime_engine": get_runtime_engine().status(),
    }


@router.get("/engine/status")
def paper_engine_status() -> dict[str, Any]:
    """Paper 전용 런타임(사용자 모의 루프) 상태 — `/api/runtime-engine` 과 구분."""
    return get_paper_session_controller().status_payload()


@router.get("/positions")
def get_paper_positions() -> dict[str, object]:
    items = get_paper_session_controller().get_positions()
    return {"items": items}


@router.get("/pnl")
def get_paper_pnl() -> dict[str, object]:
    return get_paper_session_controller().pnl_from_last_report()


@router.get("/diagnostics")
def get_paper_diagnostics() -> dict[str, object]:
    """Paper 세션 마지막 KIS 실패 맥락·토큰 출처(민감값 제외)."""
    return get_paper_session_controller().diagnostics_payload()


@router.get("/logs")
def get_paper_logs() -> dict[str, object]:
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
