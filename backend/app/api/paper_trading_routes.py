from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.brokers.paper_broker import PaperBroker
from app.orders.models import OrderRequest

router = APIRouter(prefix="/paper-trading", tags=["paper-trading"])


class StartPaperTradingRequest(BaseModel):
    strategy_id: str = Field(min_length=2, max_length=64)


class PaperLogItem(BaseModel):
    ts: str
    level: Literal["info", "warning", "error"]
    message: str


@dataclass
class PaperTradingRuntime:
    mode: Literal["paper"] = "paper"
    status: Literal["running", "stopped", "risk-off"] = "stopped"
    strategy_id: str | None = None
    started_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    broker: PaperBroker = field(default_factory=PaperBroker)
    logs: list[PaperLogItem] = field(default_factory=list)
    chart_seed: list[tuple[str, float]] = field(default_factory=list)

    def start(self, strategy_id: str) -> None:
        if self.status == "running":
            raise ValueError("Paper trading already running")
        self.status = "running"
        self.strategy_id = strategy_id
        self.started_at = datetime.now(timezone.utc)
        self.last_heartbeat_at = self.started_at
        self._append_log("info", f"Paper trading started with strategy={strategy_id}")
        self._seed_mock_if_empty()

    def stop(self) -> None:
        if self.status == "stopped":
            raise ValueError("Paper trading already stopped")
        self.status = "stopped"
        self.last_heartbeat_at = datetime.now(timezone.utc)
        self._append_log("info", "Paper trading stopped")

    def status_payload(self) -> dict[str, str | None]:
        return {
            "mode": "paper",
            "status": self.status,
            "strategy_id": self.strategy_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_heartbeat_at": self.last_heartbeat_at.isoformat() if self.last_heartbeat_at else None,
        }

    def _append_log(self, level: Literal["info", "warning", "error"], message: str) -> None:
        self.logs.insert(0, PaperLogItem(ts=datetime.now(timezone.utc).isoformat(), level=level, message=message))
        self.logs = self.logs[:50]

    def _seed_mock_if_empty(self) -> None:
        if self.chart_seed:
            return
        now = datetime.now(timezone.utc)
        for idx, v in enumerate([0.1, 0.12, 0.18, 0.15, 0.23, 0.31, 0.29]):
            ts = (now - timedelta(minutes=(6 - idx) * 10)).isoformat()
            self.chart_seed.append((ts, v))
        if not self.broker.get_positions():
            self.broker.place_order(OrderRequest(symbol="005930", side="buy", quantity=2, price=77000.0))
            self.broker.place_order(OrderRequest(symbol="000660", side="buy", quantity=1, price=168000.0))


runtime = PaperTradingRuntime()


@router.post("/start")
def start_paper_trading(payload: StartPaperTradingRequest) -> dict[str, object]:
    # Hard guard: this route never executes live trading.
    if payload.strategy_id.lower().strip() == "live":
        raise HTTPException(status_code=400, detail="Invalid paper strategy id")
    try:
        runtime.start(payload.strategy_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **runtime.status_payload()}


@router.post("/stop")
def stop_paper_trading() -> dict[str, object]:
    try:
        runtime.stop()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **runtime.status_payload()}


@router.get("/status")
def get_paper_trading_status() -> dict[str, object]:
    return runtime.status_payload()


@router.get("/positions")
def get_paper_positions() -> dict[str, object]:
    items = [
        {"symbol": p.symbol, "quantity": p.quantity, "average_price": p.average_price}
        for p in runtime.broker.get_positions()
    ]
    return {"items": items}


@router.get("/pnl")
def get_paper_pnl() -> dict[str, object]:
    fills = runtime.broker.get_fills()
    realized = 0.0
    for fill in fills:
        if fill.side == "sell":
            realized += float(fill.quantity) * float(fill.fill_price) * 0.01
    unrealized = 180000.0 if runtime.status == "running" else 120000.0
    return {
        "today_return_pct": runtime.chart_seed[-1][1] if runtime.chart_seed else 0.0,
        "monthly_return_pct": 3.4,
        "cumulative_return_pct": 9.7,
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": unrealized,
        "chart": [{"ts": ts, "return_pct": val} for ts, val in runtime.chart_seed],
    }


@router.get("/logs")
def get_paper_logs() -> dict[str, object]:
    if not runtime.logs:
        runtime._append_log("info", "Paper engine initialized in safe mode")
    return {"items": [log.model_dump() for log in runtime.logs[:20]]}
