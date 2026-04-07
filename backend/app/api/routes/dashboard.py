from fastapi import APIRouter

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def dashboard_summary() -> dict[str, object]:
    return {
        "mode": "paper",
        "account_status": "connected",
        "today_return_pct": 0.41,
        "monthly_return_pct": 4.2,
        "cumulative_return_pct": 12.8,
        "position_count": 4,
        "realized_pnl": 1_840_000.0,
        "unrealized_pnl": 260_000.0,
        "system_status": "running",
        "risk_banner": {
            "level": "warning",
            "message": "연속 손실 2회 감지: 신규 진입 크기 자동 축소 중",
        },
        # TODO: Replace mock payload with live service aggregation from risk/portfolio modules.
    }
