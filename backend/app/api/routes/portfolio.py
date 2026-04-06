from fastapi import APIRouter

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/summary")
def portfolio_summary() -> dict[str, object]:
    return {
        "equity": 0.0,
        "daily_pnl": 0.0,
        "cumulative_return_pct": 0.0,
        "positions": [],
    }
