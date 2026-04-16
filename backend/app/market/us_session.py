"""
미국 현지(Eastern) 장세션 분류 — 주문 허용 여부는 한국투자 공식 `order()` 도움말과 결합.

- 정규장(09:30–16:00 America/New_York): 모의에서도 공식 예제가 허용하는 지정가(ord_dvsn=00) 주문을 시도할 수 있음.
- 프리마켓·애프터: 공식 예제 `order()` 도움말에 모의투자(V...)는 ord_dvsn `00`만 가능하다는 설명은 있으나,
  장전·시간외 주문 가능 여부는 동일 문서에서 확인되지 않아(order_allowed 불확실) 주문은 차단.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class UsEquitySessionSnapshot:
    state: str
    """premarket | regular | afterhours | closed_weekend — 요약 상태."""
    fetch_allowed: bool
    fetch_block_reason: str | None
    order_allowed: bool
    order_block_reason: str | None
    local_time_et_iso: str


def analyze_us_equity_session(now_utc: datetime | None = None) -> UsEquitySessionSnapshot:
    if now_utc is None:
        base = datetime.now(timezone.utc)
    else:
        base = now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=timezone.utc)
    local = base.astimezone(_ET)
    wd = local.weekday()
    if wd >= 5:
        return UsEquitySessionSnapshot(
            state="closed_weekend",
            fetch_allowed=True,
            fetch_block_reason=None,
            order_allowed=False,
            order_block_reason="주말 — 나스닥/뉴욕 정규장 외.",
            local_time_et_iso=local.isoformat(timespec="seconds"),
        )
    t = local.hour * 60 + local.minute
    pre_start = 4 * 60
    rth_open = 9 * 60 + 30
    rth_close = 16 * 60
    aft_end = 20 * 60
    reason_fetch = None
    fetch_ok = True
    if pre_start <= t < rth_open:
        ob = (
            "프리마켓: 한국투자 `open-trading-api` 해외주식 `order()` 도움말에 모의투자(V…)는 "
            "ord_dvsn `00`(지정가)만 가능하다는 설명은 있으나, 장전(프리마켓) 시간대의 주문 허용 여부는 "
            "동일 공식 예제·문서에서 확인되지 않아(order_allowed 미확인) 주문을 보내지 않습니다."
        )
        return UsEquitySessionSnapshot(
            state="premarket",
            fetch_allowed=fetch_ok,
            fetch_block_reason=reason_fetch,
            order_allowed=False,
            order_block_reason=ob,
            local_time_et_iso=local.isoformat(timespec="seconds"),
        )
    if rth_open <= t < rth_close:
        return UsEquitySessionSnapshot(
            state="regular",
            fetch_allowed=True,
            fetch_block_reason=None,
            order_allowed=True,
            order_block_reason=None,
            local_time_et_iso=local.isoformat(timespec="seconds"),
        )
    if rth_close <= t < aft_end:
        ob = (
            "애프터마켓: 공식 `order()` 예제 도움말만으로는 시간외 주문 가능 여부를 확정할 수 없어 "
            "주문을 차단합니다."
        )
        return UsEquitySessionSnapshot(
            state="afterhours",
            fetch_allowed=fetch_ok,
            fetch_block_reason=reason_fetch,
            order_allowed=False,
            order_block_reason=ob,
            local_time_et_iso=local.isoformat(timespec="seconds"),
        )
    return UsEquitySessionSnapshot(
        state="closed_overnight",
        fetch_allowed=True,
        fetch_block_reason=None,
        order_allowed=False,
        order_block_reason="현지 시간 기준 뉴욕 증시 휴장/비거래 구간으로 간주.",
        local_time_et_iso=local.isoformat(timespec="seconds"),
    )
