from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.app.engine.runtime_engine import get_runtime_engine

router = APIRouter(prefix="/runtime-engine", tags=["runtime-engine"])


@router.post("/start")
def start_runtime_engine() -> dict[str, Any]:
    """백그라운드 루프 시작 (이미 동작 중이면 already_running)."""
    return get_runtime_engine().start()


@router.post("/stop")
def stop_runtime_engine() -> dict[str, Any]:
    """루프 중지 및 상태 stopped."""
    return get_runtime_engine().stop()


@router.get("/status")
def runtime_engine_status() -> dict[str, Any]:
    """엔진 상태, 하트비트 파일, 실패 횟수, 현재 시장 구간."""
    return get_runtime_engine().status()


@router.post("/risk-reset")
def runtime_risk_reset() -> dict[str, Any]:
    """risk_off 또는 실패 누적 해제 후 수동 재개."""
    return get_runtime_engine().risk_reset()


@router.post("/risk-off")
def runtime_force_risk_off() -> dict[str, Any]:
    """즉시 risk_off (주문 루프는 구간 처리만 스킵)."""
    return get_runtime_engine().force_risk_off()


@router.post("/manual-override-toggle")
def runtime_manual_override_toggle() -> dict[str, Any]:
    """리스크 차단 수동 해제/복구 토글 (한 번 ON, 다시 누르면 OFF)."""
    return get_runtime_engine().toggle_manual_override()
