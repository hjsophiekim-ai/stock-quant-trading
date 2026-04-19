"""인트라데이 단타 전략용 지표·세션 유틸 (Paper 검증용)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Literal

import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

from app.config import get_settings

_KST = ZoneInfo("Asia/Seoul")

# KIS KISClient.place_order 는 국내 현금주문(지정가/시장가)만 지원하며,
# 장전/시간외 전용 주문구분·세션 파라미터가 분리되어 있지 않다(코드 기준).
# 실제 장전/장후 주문을 켜려면 별도 TR/필드가 문서·모의검증으로 확인된 뒤에만 True 로 전환한다.
KIS_DOMESTIC_REST_EXTENDED_ORDER_SUPPORTED = False

KrxSessionState = Literal["pre_open", "regular", "after_hours", "closed"]


def kst_now() -> datetime:
    return datetime.now(_KST)


def _to_kst(n: datetime) -> datetime:
    if n.tzinfo is None:
        return n.replace(tzinfo=_KST)
    return n.astimezone(_KST)


def parse_krx_hhmm(raw: str, *, default: time | None = None) -> time:
    """'0900', '09:00', '090000' 등 → time."""
    s = "".join(c for c in str(raw or "").strip() if c.isdigit())
    if not s and default is not None:
        return default
    if not s:
        return time(9, 0)
    if len(s) <= 2:
        return time(int(s), 0)
    if len(s) <= 4:
        s = s.zfill(4)[:4]
        return time(int(s[:2]), int(s[2:4]))
    s = s.zfill(6)[:6]
    return time(int(s[:2]), int(s[2:4]), int(s[4:6]))


@dataclass(frozen=True)
class KrxSessionConfig:
    """KST 기준 장전·정규·장후 경계(설정에서 로드)."""

    preopen_start: time
    regular_open: time
    regular_close: time
    afterhours_close: time
    preopen_enabled: bool
    afterhours_enabled: bool
    extended_fetch_enabled: bool
    extended_order_enabled: bool


def krx_session_config_from_settings(settings: Any) -> KrxSessionConfig:
    from app.config import Settings as SettingsCls

    if not isinstance(settings, SettingsCls):
        raise TypeError("settings must be Settings")
    return KrxSessionConfig(
        preopen_start=parse_krx_hhmm(
            getattr(settings, "paper_krx_preopen_start_hhmm", "080000"),
            default=time(8, 0),
        ),
        regular_open=parse_krx_hhmm(
            getattr(settings, "paper_krx_regular_open_hhmm", "090000"),
            default=time(9, 0),
        ),
        regular_close=parse_krx_hhmm(
            getattr(settings, "paper_krx_regular_close_hhmm", "153000"),
            default=time(15, 30),
        ),
        afterhours_close=parse_krx_hhmm(
            getattr(settings, "paper_krx_afterhours_close_hhmm", "180000"),
            default=time(18, 0),
        ),
        preopen_enabled=bool(getattr(settings, "paper_krx_preopen_enabled", False)),
        afterhours_enabled=bool(getattr(settings, "paper_krx_afterhours_enabled", False)),
        extended_fetch_enabled=bool(getattr(settings, "paper_krx_extended_fetch_enabled", False)),
        extended_order_enabled=bool(getattr(settings, "paper_krx_extended_order_enabled", False)),
    )


def get_krx_session_state_kst(
    now: datetime | None = None,
    *,
    session_config: KrxSessionConfig | None = None,
) -> KrxSessionState:
    """평일 기준으로 장전/정규/장후/완전 장외를 구분한다(공휴일 캘린더는 미적용)."""
    cfg = session_config or krx_session_config_from_settings(get_settings())
    n = _to_kst(now or kst_now())
    if n.weekday() >= 5:
        return "closed"
    hm = n.time()
    if hm < cfg.preopen_start or hm > cfg.afterhours_close:
        return "closed"
    if hm < cfg.regular_open:
        return "pre_open"
    if hm <= cfg.regular_close:
        return "regular"
    if hm <= cfg.afterhours_close:
        return "after_hours"
    return "closed"


def evaluate_intraday_fetch_gate(
    now: datetime | None,
    *,
    session_config: KrxSessionConfig | None = None,
) -> tuple[bool, str]:
    """분봉 API 호출 허용 여부와 차단 코드(빈 문자열이면 허용)."""
    cfg = session_config or krx_session_config_from_settings(get_settings())
    state = get_krx_session_state_kst(now, session_config=cfg)
    if state == "closed":
        return False, "skipped_closed_session"
    if state == "regular":
        return True, ""
    if state == "pre_open":
        if not cfg.extended_fetch_enabled or not cfg.preopen_enabled:
            return False, "skipped_preopen_disabled"
        return True, ""
    if state == "after_hours":
        if not cfg.extended_fetch_enabled or not cfg.afterhours_enabled:
            return False, "skipped_afterhours_disabled"
        return True, ""
    return False, "skipped_closed_session"


def evaluate_intraday_order_gate(
    now: datetime | None,
    *,
    session_config: KrxSessionConfig | None = None,
) -> tuple[bool, str]:
    """실제 주문(브로커 실행) 허용 여부 — 정규장은 기본 허용, 장전/장후는 플래그+KIS 지원 여부."""
    cfg = session_config or krx_session_config_from_settings(get_settings())
    state = get_krx_session_state_kst(now, session_config=cfg)
    if state == "closed":
        return False, "closed_session"
    if state == "regular":
        return True, ""
    if not cfg.extended_order_enabled:
        return False, "extended_order_disabled"
    if not KIS_DOMESTIC_REST_EXTENDED_ORDER_SUPPORTED:
        return False, "kis_domestic_order_regular_hours_only"
    return False, "extended_order_not_implemented"


def is_tradeable_intraday_session(
    now: datetime | None = None,
    *,
    session_config: KrxSessionConfig | None = None,
) -> bool:
    """인트라데이 루프가 의미 있는 '거래일 창'인지(완전 장외·주말이면 False)."""
    cfg = session_config or krx_session_config_from_settings(get_settings())
    return get_krx_session_state_kst(now, session_config=cfg) != "closed"


def is_orderable_session(
    now: datetime | None = None,
    *,
    session_config: KrxSessionConfig | None = None,
) -> bool:
    ok, _ = evaluate_intraday_order_gate(now, session_config=session_config)
    return ok


@dataclass(frozen=True)
class IntradaySessionSnapshot:
    state: KrxSessionState
    fetch_allowed: bool
    order_allowed: bool
    fetch_block_reason: str
    order_block_reason: str
    regular_session_kst: bool


def analyze_krx_intraday_session(
    now: datetime | None = None,
    *,
    session_config: KrxSessionConfig | None = None,
) -> IntradaySessionSnapshot:
    cfg = session_config or krx_session_config_from_settings(get_settings())
    st = get_krx_session_state_kst(now, session_config=cfg)
    fa, freason = evaluate_intraday_fetch_gate(now, session_config=cfg)
    oa, oreason = evaluate_intraday_order_gate(now, session_config=cfg)
    return IntradaySessionSnapshot(
        state=st,
        fetch_allowed=fa,
        order_allowed=oa,
        fetch_block_reason=freason,
        order_block_reason=oreason,
        regular_session_kst=st == "regular",
    )


def is_regular_krx_session(now: datetime | None = None) -> bool:
    """정규장 여부(기존 API 호환 — 09:00~15:30 경계는 설정값 사용)."""
    cfg = krx_session_config_from_settings(get_settings())
    return get_krx_session_state_kst(now, session_config=cfg) == "regular"


def minutes_since_session_open_kst(
    now: datetime | None = None,
    *,
    session_config: KrxSessionConfig | None = None,
) -> float:
    """정규장 개장(설정) 기준 개장 후 분(장외·주말은 음수/비정상)."""
    cfg = session_config or krx_session_config_from_settings(get_settings())
    n = _to_kst(now or kst_now())
    open_dt = n.replace(
        hour=cfg.regular_open.hour,
        minute=cfg.regular_open.minute,
        second=cfg.regular_open.second,
        microsecond=0,
    )
    if n < open_dt:
        return -1.0
    return (n - open_dt).total_seconds() / 60.0


def minutes_to_regular_close_kst(
    now: datetime | None = None,
    *,
    session_config: KrxSessionConfig | None = None,
) -> float:
    """정규장 종료(설정)까지 남은 분(장외·주말은 큰 음수)."""
    cfg = session_config or krx_session_config_from_settings(get_settings())
    n = _to_kst(now or kst_now())
    if n.weekday() >= 5:
        return -9999.0
    close_dt = n.replace(
        hour=cfg.regular_close.hour,
        minute=cfg.regular_close.minute,
        second=cfg.regular_close.second,
        microsecond=0,
    )
    return (close_dt - n).total_seconds() / 60.0


def macd_line_signal_hist(close: pd.Series, fast: int = 12, slow: int = 26, signal_n: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD line, signal, histogram (표준 EMA 정의)."""
    c = close.astype(float)
    ema_f = c.ewm(span=int(fast), adjust=False).mean()
    ema_s = c.ewm(span=int(slow), adjust=False).mean()
    macd = ema_f - ema_s
    sig = macd.ewm(span=int(signal_n), adjust=False).mean()
    hist = macd - sig
    return macd, sig, hist


def effective_intraday_max_open_positions(cfg: Any, strategy_id: str) -> int:
    """전략별 동시 보유 상한(글로벌 상한과 교차)."""
    sid = (strategy_id or "").lower().strip()
    base = int(getattr(cfg, "paper_intraday_max_open_positions", 3) or 3)
    if sid in ("scalp_momentum_v2", "scalp_momentum_v3"):
        return min(base, int(getattr(cfg, "paper_experimental_scalp_max_open_positions", 2)))
    if sid == "scalp_macd_rsi_3m_v1":
        return min(base, int(getattr(cfg, "paper_scalp_macd_max_open_positions", 3)))
    if sid == "scalp_rsi_flag_hf_v1":
        return min(base, int(getattr(cfg, "paper_rsi_hf_max_open_positions", 4)))
    return base


def should_force_flatten_before_close_kst(
    *,
    now: datetime | None = None,
    minutes_before_close: int = 15,
    session_config: KrxSessionConfig | None = None,
) -> bool:
    """장 종료 N분 전부터 당일 청산(overnight 금지)용 — 정규장 종료 시각 기준."""
    cfg = session_config or krx_session_config_from_settings(get_settings())
    n = _to_kst(now or kst_now())
    if n.weekday() >= 5:
        return True
    close_dt = n.replace(
        hour=cfg.regular_close.hour,
        minute=cfg.regular_close.minute,
        second=cfg.regular_close.second,
        microsecond=0,
    )
    trigger = close_dt - timedelta(minutes=int(minutes_before_close))
    return n >= trigger


def quote_liquidity_from_payload(payload: dict[str, Any]) -> dict[str, float]:
    out = payload.get("output")
    if not isinstance(out, dict):
        return {"acml_vol": 0.0, "acml_tr_pbmn": 0.0, "bidp": 0.0, "askp": 0.0, "spread_pct": 99.0}

    def _f(k: str) -> float:
        try:
            return float(out.get(k) or 0)
        except (TypeError, ValueError):
            return 0.0

    bid = _f("bidp")
    ask = _f("askp")
    mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else max(bid, ask, 1.0)
    spread_pct = ((ask - bid) / mid) * 100.0 if mid > 0 else 99.0
    return {
        "acml_vol": _f("acml_vol"),
        "acml_tr_pbmn": _f("acml_tr_pbmn"),
        "bidp": bid,
        "askp": ask,
        "spread_pct": float(spread_pct),
    }


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=int(span), adjust=False).mean()


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """분봉 OHLC: typical price * volume 누적."""
    if df.empty:
        return pd.Series(dtype="float64")
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].clip(lower=0.0)
    cum_vp = (tp * vol).cumsum()
    cum_v = vol.cumsum().replace(0, np.nan)
    return cum_vp / cum_v


def opening_range_high(df: pd.DataFrame, first_n_bars: int) -> float | None:
    if df.empty or len(df) < 2:
        return None
    head = df.sort_values("date").head(max(1, int(first_n_bars)))
    return float(head["high"].max())


def volume_zscore_recent(vol: pd.Series, window: int = 20) -> float | None:
    if len(vol) < window:
        return None
    tail = vol.iloc[-window:]
    mu = float(tail.mean())
    sd = float(tail.std()) or 1e-9
    return float((tail.iloc[-1] - mu) / sd)


def last_bar_body_pct(df: pd.DataFrame) -> float | None:
    if df.empty:
        return None
    last = df.sort_values("date").iloc[-1]
    o, h, low, c = float(last["open"]), float(last["high"]), float(last["low"]), float(last["close"])
    rng = h - low
    if rng <= 0:
        return 0.0
    return abs(c - o) / rng * 100.0


def intraday_liquidity_multipliers_for_state(state: str, settings: Any) -> tuple[float, float, float]:
    """(min_vol 계수, max_spread 계수, chase 캔들 계수) — 장후·장전은 더 보수적으로."""
    pv = float(getattr(settings, "paper_intraday_preopen_min_vol_mult", 1.15))
    ps = float(getattr(settings, "paper_intraday_preopen_spread_mult", 0.88))
    pc = float(getattr(settings, "paper_intraday_preopen_chase_mult", 0.82))
    av = float(getattr(settings, "paper_intraday_afterhours_min_vol_mult", 1.35))
    a_s = float(getattr(settings, "paper_intraday_afterhours_spread_mult", 0.65))
    ac = float(getattr(settings, "paper_intraday_afterhours_chase_mult", 0.72))
    if state == "pre_open":
        return pv, ps, pc
    if state == "after_hours":
        return av, a_s, ac
    return 1.0, 1.0, 1.0
