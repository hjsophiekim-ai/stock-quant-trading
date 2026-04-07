from fastapi import APIRouter, Query

router = APIRouter(prefix="/performance", tags=["performance"])


@router.get("/metrics")
def performance_metrics(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> dict[str, object]:
    _ = (start_date, end_date, strategy_id, symbol)
    return {
        "daily_return_pct": 0.52,
        "weekly_return_pct": 1.84,
        "monthly_return_pct": 4.21,
        "cumulative_return_pct": 13.37,
        "realized_pnl": 2_180_000.0,
        "unrealized_pnl": 340_000.0,
        "max_drawdown_pct": -6.9,
        "win_rate_pct": 58.7,
        "payoff_ratio": 1.63,
    }


@router.get("/pnl-history")
def pnl_history(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> dict[str, object]:
    _ = (start_date, end_date, strategy_id, symbol)
    return {
        "items": [
            {"date": "2026-03-31", "daily_return_pct": -0.14, "equity": 100_120_000.0},
            {"date": "2026-04-01", "daily_return_pct": 0.22, "equity": 100_340_000.0},
            {"date": "2026-04-02", "daily_return_pct": 0.08, "equity": 100_420_000.0},
            {"date": "2026-04-03", "daily_return_pct": 0.47, "equity": 100_890_000.0},
            {"date": "2026-04-04", "daily_return_pct": -0.11, "equity": 100_780_000.0},
            {"date": "2026-04-05", "daily_return_pct": 0.36, "equity": 101_140_000.0},
            {"date": "2026-04-06", "daily_return_pct": 0.52, "equity": 101_660_000.0},
        ]
    }


@router.get("/trade-history")
def trade_history(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> dict[str, object]:
    _ = (start_date, end_date, strategy_id, symbol)
    return {
        "items": [
            {"trade_id": "PT-101", "symbol": "005930", "strategy_id": "swing_v1", "pnl": 128000.0, "result": "win"},
            {"trade_id": "PT-100", "symbol": "000660", "strategy_id": "bull_focus_v1", "pnl": -42000.0, "result": "loss"},
            {"trade_id": "PT-099", "symbol": "035420", "strategy_id": "swing_v1", "pnl": 64000.0, "result": "win"},
            {"trade_id": "PT-098", "symbol": "207940", "strategy_id": "defensive_v1", "pnl": 18000.0, "result": "win"},
            {"trade_id": "PT-097", "symbol": "051910", "strategy_id": "swing_v1", "pnl": -31000.0, "result": "loss"},
        ]
    }


@router.get("/symbol-performance")
def symbol_performance(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> dict[str, object]:
    _ = (start_date, end_date, strategy_id, symbol)
    return {
        "items": [
            {"symbol": "005930", "pnl": 390000.0, "return_pct": 4.2, "win_rate_pct": 66.0},
            {"symbol": "000660", "pnl": 210000.0, "return_pct": 3.1, "win_rate_pct": 57.0},
            {"symbol": "035420", "pnl": 120000.0, "return_pct": 2.0, "win_rate_pct": 54.0},
            {"symbol": "051910", "pnl": -50000.0, "return_pct": -0.9, "win_rate_pct": 41.0},
        ]
    }


@router.get("/strategy-performance")
def strategy_performance(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> dict[str, object]:
    _ = (start_date, end_date, strategy_id, symbol)
    return {
        "items": [
            {"strategy_id": "swing_v1", "pnl": 840000.0, "return_pct": 5.6, "win_rate_pct": 61.0},
            {"strategy_id": "bull_focus_v1", "pnl": 520000.0, "return_pct": 4.1, "win_rate_pct": 58.0},
            {"strategy_id": "defensive_v1", "pnl": 160000.0, "return_pct": 1.8, "win_rate_pct": 63.0},
        ]
    }


@router.get("/regime-performance")
def regime_performance(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
) -> dict[str, object]:
    _ = (start_date, end_date, strategy_id, symbol)
    return {
        "items": [
            {"regime": "bullish_trend", "pnl": 960000.0, "return_pct": 6.2, "win_rate_pct": 64.0},
            {"regime": "sideways", "pnl": 180000.0, "return_pct": 1.6, "win_rate_pct": 55.0},
            {"regime": "bearish_trend", "pnl": 110000.0, "return_pct": 0.9, "win_rate_pct": 52.0},
            {"regime": "high_volatility_risk", "pnl": -12000.0, "return_pct": -0.2, "win_rate_pct": 48.0},
        ]
    }
