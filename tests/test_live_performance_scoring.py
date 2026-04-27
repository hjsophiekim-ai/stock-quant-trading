from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from backend.app.core.config import BackendSettings
from backend.app.strategy.live_candidate_scoring import score_candidate
from backend.app.strategy.live_performance_scoring import get_performance_signal


def _cfg(tmp_path) -> BackendSettings:
    return BackendSettings(portfolio_data_dir=str(tmp_path), trading_mode="live", execution_mode="live_auto_guarded")


def _write_fills(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def _mk_trade_rows(*, strategy_id: str, symbol: str, ord_dt: str, base_tmd: int, buy_px: float, sell_px: float, n: int) -> list[dict]:
    rows: list[dict] = []
    t = base_tmd
    for i in range(n):
        rows.append(
            {
                "ord_dt": ord_dt,
                "ord_tmd": f"{t:06d}",
                "exec_id": f"b{i}",
                "symbol": symbol,
                "side": "buy",
                "quantity": 1,
                "price": float(buy_px),
                "strategy_id": strategy_id,
            }
        )
        t += 1
        rows.append(
            {
                "ord_dt": ord_dt,
                "ord_tmd": f"{t:06d}",
                "exec_id": f"s{i}",
                "symbol": symbol,
                "side": "sell",
                "quantity": 1,
                "price": float(sell_px),
                "strategy_id": strategy_id,
            }
        )
        t += 1
    return rows


def test_performance_neutral_when_insufficient_samples(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    ord_dt = datetime.now(timezone.utc).strftime("%Y%m%d")
    fills = _mk_trade_rows(strategy_id="final_betting_v1", symbol="AAA", ord_dt=ord_dt, base_tmd=90000, buy_px=100.0, sell_px=105.0, n=2)
    _write_fills(Path(cfg.portfolio_data_dir) / "fills.jsonl", fills)
    sig = get_performance_signal(cfg, strategy_id="final_betting_v1", lookback_days=60, min_sell_trades=10, cache_ttl_sec=0.0)
    assert sig.metrics["sample_ok"] is False
    assert sig.score_adjustment == 0.0
    assert sig.buy_blocked is False


def test_performance_bonus_for_good_strategy(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    ord_dt = datetime.now(timezone.utc).strftime("%Y%m%d")
    fills = _mk_trade_rows(strategy_id="final_betting_v1", symbol="AAA", ord_dt=ord_dt, base_tmd=90000, buy_px=100.0, sell_px=112.0, n=12)
    _write_fills(Path(cfg.portfolio_data_dir) / "fills.jsonl", fills)
    sig = get_performance_signal(cfg, strategy_id="final_betting_v1", lookback_days=60, min_sell_trades=10, cache_ttl_sec=0.0)
    assert sig.metrics["sample_ok"] is True
    assert sig.score_adjustment > 0
    assert sig.buy_blocked is False


def test_performance_penalty_and_block_for_bad_strategy(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    ord_dt = datetime.now(timezone.utc).strftime("%Y%m%d")
    fills = _mk_trade_rows(strategy_id="final_betting_v1", symbol="AAA", ord_dt=ord_dt, base_tmd=90000, buy_px=100.0, sell_px=92.0, n=12)
    _write_fills(Path(cfg.portfolio_data_dir) / "fills.jsonl", fills)
    sig = get_performance_signal(cfg, strategy_id="final_betting_v1", lookback_days=60, min_sell_trades=10, cache_ttl_sec=0.0)
    assert sig.metrics["sample_ok"] is True
    assert sig.score_adjustment <= 0
    assert sig.buy_blocked is True


def test_score_candidate_applies_performance_signal(tmp_path) -> None:
    cfg = _cfg(tmp_path)
    ord_dt = datetime.now(timezone.utc).strftime("%Y%m%d")
    fills = _mk_trade_rows(strategy_id="final_betting_v1", symbol="AAA", ord_dt=ord_dt, base_tmd=90000, buy_px=100.0, sell_px=112.0, n=12)
    _write_fills(Path(cfg.portfolio_data_dir) / "fills.jsonl", fills)
    sig = get_performance_signal(cfg, strategy_id="final_betting_v1", lookback_days=60, min_sell_trades=10, cache_ttl_sec=0.0)
    perf = {"score_adjustment": sig.score_adjustment, "buy_blocked": sig.buy_blocked, "reason": sig.reason, "metrics": sig.metrics}
    out = score_candidate(
        symbol="AAA",
        base_signal_score=0.2,
        order_price=100.0,
        market_mode={"market_mode_active": "aggressive"},
        already_holding=False,
        has_open_order=False,
        strategy_performance=perf,
    )
    assert out.score > 0

