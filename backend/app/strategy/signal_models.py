"""
리스크·주문 계층으로 넘기기 위한 표준 전략 신호 모델.

`OrderSignal`(app.orders.models)로 변환해 `OrderManager.process_signal`에 그대로 전달할 수 있습니다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from app.orders.models import OrderSignal

SignalSide = Literal["buy", "sell"]
SignalKind = Literal[
    "entry_leg1",
    "entry_leg2",
    "exit_stop_loss",
    "exit_take_profit_partial",
    "exit_take_profit_full",
    "exit_time",
    "exit_trailing",
]


class SymbolStrategyPhase(StrEnum):
    """종목별 스윙·분할매매 상태."""

    FLAT = "flat"
    """보유 없음, 신규 분할 진입 가능."""

    SCALE_IN = "scale_in"
    """1차 매수 후 2차 분할 대기."""

    HOLDING = "holding"
    """계획 수량까지 충족, 익절·손절·시간·트레일링 관리."""

    REDUCED = "reduced"
    """1차 익절 후 잔량 보유(트레일링 등)."""


@dataclass
class SymbolStrategyState:
    """엔진이 추적하는 종목별 전략 상태(브로커 체결과 병합)."""

    symbol: str
    phase: SymbolStrategyPhase = SymbolStrategyPhase.FLAT
    entry_legs_done: int = 0
    first_take_profit_done: bool = False
    highest_price_since_entry: float | None = None
    last_phase_change_utc: str | None = None
    notes: list[str] = field(default_factory=list)

    def touch(self) -> None:
        self.last_phase_change_utc = datetime.now(timezone.utc).isoformat()


@dataclass
class LiveQuoteView:
    """KIS inquire-price 등에서 추출한 실시간 시세."""

    symbol: str
    last: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    raw_keys: dict[str, Any] = field(default_factory=dict)


@dataclass
class SwingSignalEngineConfig:
    """우량주 스윙 + 추세 + 분할매매 파라미터."""

    strategy_id: str = "swing_signal_engine"
    order_quantity: int = 10
    first_leg_drawdown_pct: float = -3.0
    second_leg_drawdown_pct: float = -5.0
    ret_3d_min: float = -6.0
    ret_3d_max: float = -3.0
    rsi_max: float = 40.0
    stop_loss_pct: float = 4.0
    first_take_profit_pct: float = 6.0
    second_take_profit_pct: float = 10.0
    time_exit_days: int = 7
    swing_high_lookback: int = 20
    trailing_mode: Literal["atr", "n_day_low"] = "atr"
    trailing_atr_multiplier: float = 2.5
    trailing_n_day_low_window: int = 5
    block_new_entries_regimes: tuple[str, ...] = ("high_volatility_risk",)


@dataclass
class StandardEngineSignal:
    """
    표준 신호: 사유·종류·메타데이터를 유지하고, 리스크 검증용 `OrderSignal`로 투영합니다.
    """

    symbol: str
    side: SignalSide
    quantity: int
    limit_price: float | None
    stop_loss_pct: float | None
    strategy_id: str
    kind: SignalKind
    reasons: list[str]
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_order_signal(self) -> OrderSignal:
        return OrderSignal(
            symbol=self.symbol,
            side=self.side,
            quantity=self.quantity,
            limit_price=self.limit_price,
            stop_loss_pct=self.stop_loss_pct,
            strategy_id=self.strategy_id,
            signal_id=self.signal_id,
        )


@dataclass
class SymbolSignalDiagnosis:
    """진입/비진입·청산 판단 설명(로그·API)."""

    symbol: str
    phase: str
    would_enter: bool
    would_exit: bool
    checklist: dict[str, bool | float | str]
    narrative: list[str]


@dataclass
class SignalEngineSnapshot:
    evaluated_at_utc: str
    market_regime: str | None
    signals: list[StandardEngineSignal]
    suppressed: list[dict[str, Any]]
    per_symbol: list[SymbolSignalDiagnosis]
    states: dict[str, dict[str, Any]]
