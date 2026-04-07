from fastapi import APIRouter

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/summary")
def portfolio_summary() -> dict[str, object]:
    return {
        "equity": 102_340_000.0,
        "daily_pnl": 420_000.0,
        "monthly_return_pct": 4.2,
        "cumulative_return_pct": 12.8,
        "position_count": 4,
        "realized_pnl": 1_840_000.0,
        "unrealized_pnl": 260_000.0,
        "positions": [
            {"symbol": "005930", "quantity": 12, "average_price": 76800.0, "market_price": 78400.0},
            {"symbol": "000660", "quantity": 8, "average_price": 168000.0, "market_price": 171500.0},
            {"symbol": "035420", "quantity": 20, "average_price": 191000.0, "market_price": 186000.0},
            {"symbol": "207940", "quantity": 3, "average_price": 786000.0, "market_price": 792000.0},
        ],
    }
