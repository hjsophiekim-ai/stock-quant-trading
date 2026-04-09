"""백엔드 스크리너 랭킹·필터 단위 테스트 (KIS 없음)."""

from __future__ import annotations

from backend.app.strategy.ranking import (
    apply_hard_filters,
    apply_return_top_percentile,
    apply_screening_gates,
    rank_candidates,
    regime_adjusted_top_n_and_percentile,
)


def test_apply_hard_filters_ma_and_volume() -> None:
    base = {"vol_std_pct": 1.0, "gap_pct": 0.0}
    rows = [
        {"symbol": "A", "ma60_rising": True, "vol_ratio": 1.2, "ret_60": 5.0, **base},
        {"symbol": "B", "ma60_rising": False, "vol_ratio": 1.2, "ret_60": 10.0, **base},
        {"symbol": "C", "ma60_rising": True, "vol_ratio": 0.5, "ret_60": 3.0, **base},
    ]
    passed, log = apply_hard_filters(rows)
    assert {r["symbol"] for r in passed} == {"A"}
    assert any("B" in x for x in log)
    assert any("C" in x for x in log)


def test_apply_screening_gates_vol_and_gap() -> None:
    rows = [
        {
            "symbol": "V",
            "ma60_rising": True,
            "vol_ratio": 1.1,
            "ret_60": 5.0,
            "vol_std_pct": 10.0,
            "gap_pct": 0.0,
        },
        {
            "symbol": "G",
            "ma60_rising": True,
            "vol_ratio": 1.1,
            "ret_60": 5.0,
            "vol_std_pct": 1.0,
            "gap_pct": 8.0,
        },
    ]
    passed, excl, _log = apply_screening_gates(
        rows,
        max_vol_std_pct=4.0,
        max_abs_gap_pct=5.0,
        min_volume_ratio=1.0,
    )
    assert passed == []
    assert len(excl) == 2
    blob = " ".join(str(x) for e in excl for x in (e.get("block_reasons") or []))
    assert "변동성" in blob and "갭" in blob


def test_return_top_percentile() -> None:
    rows = [
        {
            "symbol": f"S{i}",
            "ma60_rising": True,
            "vol_ratio": 1.0,
            "ret_60": float(i),
            "vol_std_pct": 1.0,
            "gap_pct": 0.0,
        }
        for i in range(10)
    ]
    out, log, excl, thr = apply_return_top_percentile(rows, top_pct=0.3)
    assert thr is not None
    assert len(out) <= 4
    assert len(excl) == 10 - len(out)
    assert all(float(r["ret_60"]) >= thr for r in out)
    assert log


def test_rank_candidates_order() -> None:
    rows = [
        {
            "symbol": "W",
            "ret_60": 20.0,
            "ma60_slope_pct": 1.0,
            "vol_ratio": 2.0,
            "vol_std_pct": 1.0,
            "gap_pct": 0.0,
        },
        {
            "symbol": "L",
            "ret_60": 2.0,
            "ma60_slope_pct": 0.1,
            "vol_ratio": 1.0,
            "vol_std_pct": 2.0,
            "gap_pct": 0.0,
        },
    ]
    ranked = rank_candidates(rows, regime="bullish_trend", top_n=2)
    assert ranked[0].symbol == "W"
    assert ranked[0].total_score >= ranked[1].total_score
    assert ranked[0].reasons
    assert ranked[0].reasons_detail


def test_regime_adjustments() -> None:
    n, p, _ = regime_adjusted_top_n_and_percentile("bullish_trend", 10, 0.3)
    assert n == 10 and p == 0.3
    n2, p2, r2 = regime_adjusted_top_n_and_percentile("bearish_trend", 10, 0.3)
    assert n2 == 5 and p2 == 0.2
    n3, _, _ = regime_adjusted_top_n_and_percentile("high_volatility_risk", 10, 0.3)
    assert n3 == 0
