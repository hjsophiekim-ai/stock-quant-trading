"""Paper 인트라데이 틱 간 상태(당일 매매 수·쿨다운·진입 시각)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_KST = ZoneInfo("Asia/Seoul")


def _today_kst() -> str:
    return datetime.now(_KST).strftime("%Y%m%d")


@dataclass
class IntradayPaperState:
    day_kst: str = ""
    trade_count_today: int = 0
    cooldown_until_iso: dict[str, str] = field(default_factory=dict)
    last_buy_mono: dict[str, float] = field(default_factory=dict)
    entry_ts_iso: dict[str, str] = field(default_factory=dict)
    peak_price: dict[str, float] = field(default_factory=dict)
    """종목별 당일 매수 체결 횟수(고빈도 전략 과매매 방지)."""
    symbol_entries_today: dict[str, int] = field(default_factory=dict)
    halted_new_entries_today: bool = False
    # final_betting_v1: 일자 롤 시에도 유지(overnight 메타·쿨다운). 스캘프 일카운터와 분리.
    final_betting_carry: dict[str, Any] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_jsonable(cls, raw: dict[str, Any]) -> IntradayPaperState:
        return cls(
            day_kst=str(raw.get("day_kst") or ""),
            trade_count_today=int(raw.get("trade_count_today") or 0),
            cooldown_until_iso=dict(raw.get("cooldown_until_iso") or {}),
            last_buy_mono={k: float(v) for k, v in (raw.get("last_buy_mono") or {}).items()},
            entry_ts_iso=dict(raw.get("entry_ts_iso") or {}),
            peak_price={k: float(v) for k, v in (raw.get("peak_price") or {}).items()},
            symbol_entries_today={str(k): int(v) for k, v in (raw.get("symbol_entries_today") or {}).items()},
            halted_new_entries_today=bool(raw.get("halted_new_entries_today")),
            final_betting_carry=dict(raw.get("final_betting_carry") or {}),
        )


class IntradayPaperStateStore:
    def __init__(self, path: Path, *, logger: logging.Logger | None = None) -> None:
        self.path = path
        self.logger = logger or logging.getLogger("app.strategy.intraday_paper_state")

    def load(self) -> IntradayPaperState:
        if not self.path.is_file():
            return IntradayPaperState(day_kst=_today_kst())
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return IntradayPaperState(day_kst=_today_kst())
            st = IntradayPaperState.from_jsonable(raw)
            return self._roll_day(st)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.logger.warning("intraday paper state reset: %s", exc)
            return IntradayPaperState(day_kst=_today_kst())

    def save(self, state: IntradayPaperState) -> None:
        state = self._roll_day(state)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state.to_jsonable(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _roll_day(self, state: IntradayPaperState) -> IntradayPaperState:
        today = _today_kst()
        if state.day_kst == today:
            return state
        carry: dict[str, Any] = dict(state.final_betting_carry or {})
        # 신규 진입 일카운터만 초기화. overnight positions / last_exit 는 유지.
        carry["entered_symbols_today"] = []
        carry["entries_kst_date"] = today
        carry["fb_intraday_meta"] = {"date_kst": today, "stopout_counts": {}}
        return IntradayPaperState(day_kst=today, final_betting_carry=carry, symbol_entries_today={})


def iso_now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
