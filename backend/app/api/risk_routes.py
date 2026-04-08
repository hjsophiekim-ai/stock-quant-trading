from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.app.risk.service import build_public_risk_status

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/status")
def risk_status() -> dict[str, Any]:
    return build_public_risk_status()


@router.get("/reason-codes")
def risk_reason_codes() -> dict[str, list[str]]:
    st = build_public_risk_status()
    return {"codes": st["reason_codes_enum"]}
