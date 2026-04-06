from fastapi import APIRouter

router = APIRouter(prefix="/trading", tags=["trading"])


@router.get("/mode")
def get_mode() -> dict[str, str]:
    return {"default_mode": "paper", "live_status": "locked"}


@router.get("/orders")
def get_orders() -> dict[str, list[dict[str, str]]]:
    return {"items": []}
