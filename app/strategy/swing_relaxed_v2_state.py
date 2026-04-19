"""swing_relaxed_v2 전용 Paper 상태: TP1 부분청산 1회만 허용."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")


def _today_kst() -> str:
    return datetime.now(_KST).strftime("%Y%m%d")


@dataclass
class SwingRelaxedV2PaperState:
    day_kst: str = ""
    """종목별 TP1(부분 익절) 이미 실행 여부."""
    tp1_done: dict[str, bool] = field(default_factory=dict)
    """종목별 포지션 시그니처(평단·수량). 변하면 새 포지션으로 간주해 tp1 리셋."""
    position_sig: dict[str, str] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_jsonable(cls, raw: dict[str, Any]) -> SwingRelaxedV2PaperState:
        return cls(
            day_kst=str(raw.get("day_kst") or ""),
            tp1_done={str(k): bool(v) for k, v in (raw.get("tp1_done") or {}).items()},
            position_sig={str(k): str(v) for k, v in (raw.get("position_sig") or {}).items()},
        )


class SwingRelaxedV2StateStore:
    def __init__(self, path: Path, *, logger: logging.Logger | None = None) -> None:
        self.path = path
        self.logger = logger or logging.getLogger("app.strategy.swing_relaxed_v2_state")

    def load(self) -> SwingRelaxedV2PaperState:
        if not self.path.is_file():
            return SwingRelaxedV2PaperState(day_kst=_today_kst())
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return SwingRelaxedV2PaperState(day_kst=_today_kst())
            st = SwingRelaxedV2PaperState.from_jsonable(raw)
            return self._roll_day(st)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.logger.warning("swing_relaxed_v2 state reset: %s", exc)
            return SwingRelaxedV2PaperState(day_kst=_today_kst())

    def save(self, state: SwingRelaxedV2PaperState) -> None:
        state = self._roll_day(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state.to_jsonable(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _roll_day(self, state: SwingRelaxedV2PaperState) -> SwingRelaxedV2PaperState:
        today = _today_kst()
        if state.day_kst == today:
            return state
        return SwingRelaxedV2PaperState(day_kst=today, tp1_done={}, position_sig={})


def position_signature(average_price: float, quantity: int) -> str:
    return f"avg={average_price:.6f}|qty={int(quantity)}"


def sync_tp1_with_portfolio(
    state: SwingRelaxedV2PaperState,
    held: dict[str, tuple[float, int]],
) -> SwingRelaxedV2PaperState:
    """보유 종목이 사라지면 플래그 제거. 수량 증가(추가 매수) 시에만 tp1 리셋 — 부분 매도로 수량만 줄면 tp1 유지."""
    tp1 = dict(state.tp1_done)
    sig = dict(state.position_sig)
    held_syms = set(held.keys())
    for sym in list(tp1.keys()):
        if sym not in held_syms:
            tp1.pop(sym, None)
            sig.pop(sym, None)
    for sym, (avg, qty) in held.items():
        ps = position_signature(avg, qty)
        prev = sig.get(sym)
        if prev is not None and prev != ps:
            try:
                old_qty = int(prev.split("qty=")[-1])
            except (ValueError, IndexError):
                old_qty = -1
            if int(qty) > old_qty:
                tp1.pop(sym, None)
        sig[sym] = ps
    return SwingRelaxedV2PaperState(day_kst=state.day_kst, tp1_done=tp1, position_sig=sig)
