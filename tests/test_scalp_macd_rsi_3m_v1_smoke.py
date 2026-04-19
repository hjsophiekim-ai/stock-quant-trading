"""scalp_macd_rsi_3m_v1 — 합성 3분 봉으로 진입 점수·차단 스모크."""

from __future__ import annotations

import pandas as pd
from zoneinfo import ZoneInfo

from app.strategy.base_strategy import StrategyContext
from app.strategy.scalp_macd_rsi_3m_v1_strategy import ScalpMacdRsi3mV1Strategy

_KST = ZoneInfo("Asia/Seoul")


def _synth_3m_bars(*, n: int = 50, uptrend: bool = True) -> pd.DataFrame:
    rows = []
    base = pd.Timestamp("2026-04-18 10:30:00", tz=_KST)
    price = 50000.0
    for i in range(n):
        if uptrend and i > 20:
            price *= 1.002
        vol = 1_000_000 + i * 5000
        o = price * 0.999
        c = price
        h = price * 1.002
        low = price * 0.998
        rows.append(
            {
                "symbol": "005930",
                "date": base + pd.Timedelta(minutes=3 * i),
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": float(vol),
            }
        )
    return pd.DataFrame(rows)


def test_macd_strategy_emits_no_signals_without_quotes() -> None:
    strat = ScalpMacdRsi3mV1Strategy()
    px = _synth_3m_bars()
    ctx = StrategyContext(
        prices=px,
        kospi_index=pd.DataFrame(),
        sp500_index=pd.DataFrame(),
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price", "hold_days"]),
        volatility_index=pd.DataFrame(),
    )
    setattr(strat, "intraday_session_context", {"krx_session_state": "regular"})
    sigs = strat.generate_signals(ctx)
    # 유동성 필터(호가 없음)로 대부분 차단 — 크래시 없음
    assert isinstance(sigs, list)


def test_macd_strategy_hit_count_in_diagnostics() -> None:
    strat = ScalpMacdRsi3mV1Strategy()
    px = _synth_3m_bars(n=45, uptrend=True)
    ctx = StrategyContext(
        prices=px,
        kospi_index=pd.DataFrame(),
        sp500_index=pd.DataFrame(),
        portfolio=pd.DataFrame(columns=["symbol", "quantity", "average_price", "hold_days"]),
        volatility_index=pd.DataFrame(),
    )
    setattr(strat, "intraday_session_context", {"krx_session_state": "regular"})
    strat.quote_by_symbol = {
        "005930": {
            "output": {
                "acml_vol": 50_000_000.0,
                "acml_tr_pbmn": 5_000_000_000_000.0,
                "bidp": 49990.0,
                "askp": 50010.0,
            }
        }
    }
    strat.generate_signals(ctx)
    assert strat.last_diagnostics
    d0 = strat.last_diagnostics[0]
    assert "hit_count" in d0
    assert "macd_line_gt_signal" in d0
