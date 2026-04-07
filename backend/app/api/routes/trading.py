from fastapi import APIRouter

router = APIRouter(prefix="/trading", tags=["trading"])


@router.get("/mode")
def get_mode() -> dict[str, str]:
    return {"default_mode": "paper", "live_status": "locked"}


@router.get("/orders")
def get_orders() -> dict[str, list[dict[str, str]]]:
    return {"items": []}


@router.get("/recent-trades")
def recent_trades() -> dict[str, list[dict[str, object]]]:
    return {
        "items": [
            {
                "trade_id": "T-20260406-0005",
                "symbol": "005930",
                "side": "sell",
                "quantity": 5,
                "price": 78400.0,
                "filled_at": "2026-04-06T13:28:00+09:00",
                "status": "filled",
            },
            {
                "trade_id": "T-20260406-0004",
                "symbol": "000660",
                "side": "buy",
                "quantity": 2,
                "price": 170500.0,
                "filled_at": "2026-04-06T11:17:00+09:00",
                "status": "filled",
            },
            {
                "trade_id": "T-20260405-0011",
                "symbol": "035420",
                "side": "sell",
                "quantity": 4,
                "price": 188500.0,
                "filled_at": "2026-04-05T14:42:00+09:00",
                "status": "filled",
            },
            {
                "trade_id": "T-20260405-0009",
                "symbol": "207940",
                "side": "buy",
                "quantity": 1,
                "price": 790000.0,
                "filled_at": "2026-04-05T10:03:00+09:00",
                "status": "filled",
            },
            {
                "trade_id": "T-20260404-0002",
                "symbol": "051910",
                "side": "buy",
                "quantity": 3,
                "price": 394000.0,
                "filled_at": "2026-04-04T09:22:00+09:00",
                "status": "filled",
            },
        ]
    }
