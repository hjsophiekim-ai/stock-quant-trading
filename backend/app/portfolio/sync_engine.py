"""
KIS 모의 계좌 잔고·체결을 주기적으로 읽어 내부 포트폴리오 스냅샷·손익 이력을 갱신합니다.

- 체결 분은 일별주문체결조회(CCLD_DVSN=01) 기준으로 적재합니다.
- 실현손익·평단은 체결을 시간순으로 리플레이(분할매수·분할매도 반영)합니다.
- 평가손익은 잔고조회(output1)의 평가손익 필드를 우선 사용합니다.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from app.clients.kis_parsers import balance_snapshot_from_payload, normalized_fills_from_ccld_payload
from app.portfolio.positions import Position, apply_buy_fill, apply_sell_fill
from app.scheduler.equity_tracker import EquityTracker

from backend.app.core.config import BackendSettings, get_backend_settings
from backend.app.orders import build_kis_mock_execution_engine
from backend.app.orders.order_store import TrackedOrderRecord, TrackedOrderStore
from backend.app.risk.audit import append_risk_event

_logger = logging.getLogger(__name__)
_file_lock = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _yyyymmdd(d: datetime) -> str:
    return d.strftime("%Y%m%d")


def _sort_fills(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        fills,
        key=lambda f: (
            str(f.get("ord_dt") or ""),
            str(f.get("ord_tmd") or ""),
            str(f.get("exec_id") or ""),
        ),
    )


def _strategy_for_order_no(tracked: list[TrackedOrderRecord], order_no: str) -> str:
    if not order_no:
        return "unknown"
    for r in tracked:
        bid = (r.broker_order_id or "").strip()
        if not bid:
            continue
        if order_no in bid:
            return (r.strategy_id or "unknown").strip() or "unknown"
        if "|" in bid:
            _, tail = bid.split("|", 1)
            if tail.strip() == order_no:
                return (r.strategy_id or "unknown").strip() or "unknown"
    return "unknown"


@dataclass
class ReplayResult:
    positions: dict[str, Position]
    total_realized: float
    realized_by_symbol: dict[str, float]
    realized_by_strategy: dict[str, float]
    replay_warnings: list[str] = field(default_factory=list)


def replay_fills_for_pnl(fills: list[dict[str, Any]]) -> ReplayResult:
    """시간순 체결 리플레이로 평단·실현손익(종목·전략)을 계산합니다."""
    positions: dict[str, Position | None] = {}
    total_realized = 0.0
    realized_by_symbol: dict[str, float] = {}
    realized_by_strategy: dict[str, float] = {}
    warnings: list[str] = []

    for f in _sort_fills(fills):
        sym = str(f.get("symbol") or "").strip()
        if not sym:
            continue
        side = str(f.get("side") or "").lower()
        try:
            qty = int(f["quantity"])
        except (KeyError, TypeError, ValueError):
            continue
        try:
            price = float(f["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if qty <= 0 or price <= 0:
            continue
        strat = str(f.get("strategy_id") or "unknown")

        if side == "buy":
            cur = positions.get(sym)
            positions[sym] = apply_buy_fill(cur, qty, price, sym)
            continue

        if side != "sell":
            continue

        pos = positions.get(sym)
        if pos is None or pos.quantity <= 0:
            warnings.append(f"sell_without_position:{sym}:odno={f.get('order_no')}")
            continue
        sell_qty = qty
        if sell_qty > pos.quantity:
            warnings.append(
                f"sell_exceeds_internal_qty:{sym}:requested={sell_qty}:internal={pos.quantity}"
            )
            sell_qty = pos.quantity
        pnl = (price - pos.average_price) * sell_qty
        total_realized += pnl
        realized_by_symbol[sym] = realized_by_symbol.get(sym, 0.0) + pnl
        realized_by_strategy[strat] = realized_by_strategy.get(strat, 0.0) + pnl
        positions[sym] = apply_sell_fill(pos, sell_qty)

    out_pos: dict[str, Position] = {k: v for k, v in positions.items() if v is not None}
    return ReplayResult(
        positions=out_pos,
        total_realized=total_realized,
        realized_by_symbol=realized_by_symbol,
        realized_by_strategy=realized_by_strategy,
        replay_warnings=warnings,
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_jsonl_all(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    line = json.dumps(row, ensure_ascii=False)
    with _file_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def read_jsonl_tail(path: Path, *, max_lines: int) -> list[dict[str, Any]]:
    if not path.is_file() or max_lines <= 0:
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-max_lines:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _avg_close(a: float, b: float, *, rel_tol: float = 0.001, abs_tol: float = 1.0) -> bool:
    if abs(a - b) <= abs_tol:
        return True
    m = max(abs(a), abs(b), 1.0)
    return abs(a - b) / m <= rel_tol


@dataclass
class SyncRunResult:
    ok: bool
    message: str
    snapshot: dict[str, Any] | None = None


class PortfolioSyncEngine:
    def __init__(
        self,
        settings: BackendSettings | None = None,
        *,
        execution_engine_factory: Callable[[], Any] | None = None,
        tracked_store: TrackedOrderStore | None = None,
    ) -> None:
        self._settings = settings or get_backend_settings()
        self._engine_factory = execution_engine_factory or build_kis_mock_execution_engine
        self._tracked = tracked_store or TrackedOrderStore(self._settings.order_tracked_store_json)

    def _paths(self) -> tuple[Path, Path, Path, Path, Path, Path]:
        s = self._settings
        root = Path(s.portfolio_data_dir)
        return (
            root / "sync_state.json",
            root / "fills.jsonl",
            root / "pnl_history.jsonl",
            root / "sync_failures.json",
            Path(s.portfolio_equity_tracker_path),
            root / "sync_risk_review.flag",
        )

    def sync(self, *, backfill_days: int = 7) -> SyncRunResult:
        state_p, fills_p, pnl_hist_p, fail_p, equity_p, flag_p = self._paths()
        s = self._settings

        try:
            eng = self._engine_factory()
            broker = eng.get_broker()
            client = broker.kis_client
            acct = broker.account_no
            prod = broker.account_product_code
        except Exception as exc:
            self._record_failure(fail_p, str(exc), flag_p, s)
            return SyncRunResult(ok=False, message=str(exc))

        try:
            bal_payload = client.get_balance(acct, prod)
            snap = balance_snapshot_from_payload(bal_payload)
        except Exception as exc:
            _logger.warning("portfolio sync: balance failed: %s", exc)
            self._record_failure(fail_p, f"balance:{exc}", flag_p, s)
            return SyncRunResult(ok=False, message=str(exc))

        end = datetime.now()
        start = end - timedelta(days=max(0, int(backfill_days)))
        start_s = _yyyymmdd(start)
        end_s = _yyyymmdd(end)

        try:
            ccld_payload = client.inquire_daily_ccld(
                account_no=acct,
                account_product_code=prod,
                start_yyyymmdd=start_s,
                end_yyyymmdd=end_s,
                symbol="",
                sell_buy_code="00",
                ccld_div="01",
            )
            raw_fills = normalized_fills_from_ccld_payload(ccld_payload)
        except Exception as exc:
            _logger.warning("portfolio sync: ccld failed: %s", exc)
            self._record_failure(fail_p, f"ccld:{exc}", flag_p, s)
            return SyncRunResult(ok=False, message=str(exc))

        tracked = self._tracked.list_all()
        for row in raw_fills:
            row["strategy_id"] = _strategy_for_order_no(tracked, str(row.get("order_no") or ""))

        existing = read_jsonl_all(fills_p)
        known = {str(x.get("exec_id")) for x in existing if x.get("exec_id")}
        new_count = 0
        for row in raw_fills:
            eid = str(row.get("exec_id") or "")
            if not eid or eid in known:
                continue
            append_jsonl(fills_p, row)
            known.add(eid)
            new_count += 1

        all_fills = read_jsonl_all(fills_p)
        replay = replay_fills_for_pnl(all_fills)

        kis_positions: dict[str, dict[str, Any]] = {
            str(p["symbol"]): p for p in snap.get("positions", []) if p.get("symbol")
        }
        warnings: list[str] = list(replay.replay_warnings)
        mismatches: list[dict[str, Any]] = []

        unrealized_kis_sum = 0.0
        merged_positions: list[dict[str, Any]] = []
        for sym, krow in kis_positions.items():
            k_qty = int(krow.get("quantity") or 0)
            k_avg = float(krow.get("average_price") or 0.0)
            k_unrl = float(krow.get("unrealized_pnl_kis") or 0.0)
            unrealized_kis_sum += k_unrl
            ip = replay.positions.get(sym)
            i_qty = ip.quantity if ip else 0
            i_avg = ip.average_price if ip else 0.0
            if k_qty != i_qty:
                w = f"qty_mismatch:{sym}:kis={k_qty}:internal={i_qty}"
                warnings.append(w)
                mismatches.append({"symbol": sym, "kind": "quantity", "kis": k_qty, "internal": i_qty})
            elif k_qty > 0 and not _avg_close(k_avg, i_avg):
                w = f"avg_mismatch:{sym}:kis_avg={k_avg}:internal_avg={i_avg}"
                warnings.append(w)
                mismatches.append({"symbol": sym, "kind": "average_price", "kis": k_avg, "internal": i_avg})

            mkt = float(krow.get("current_price") or 0.0)
            unrealized_calc = (
                (mkt - i_avg) * i_qty if i_qty > 0 and mkt > 0 and i_avg > 0 else k_unrl
            )
            merged_positions.append(
                {
                    "symbol": sym,
                    "quantity": k_qty,
                    "average_price_kis": k_avg,
                    "average_price_internal": i_avg,
                    "current_price": mkt,
                    "unrealized_pnl_kis": k_unrl,
                    "unrealized_pnl_calc": unrealized_calc,
                    "market_value": float(krow.get("market_value") or 0.0),
                    "realized_pnl": float(replay.realized_by_symbol.get(sym, 0.0)),
                }
            )

        for sym, ip in replay.positions.items():
            if sym in kis_positions:
                continue
            w = f"internal_position_not_in_broker:{sym}:qty={ip.quantity}"
            warnings.append(w)
            mismatches.append({"symbol": sym, "kind": "orphan_internal", "internal_qty": ip.quantity})
            merged_positions.append(
                {
                    "symbol": sym,
                    "quantity": ip.quantity,
                    "average_price_kis": 0.0,
                    "average_price_internal": ip.average_price,
                    "current_price": 0.0,
                    "unrealized_pnl_kis": 0.0,
                    "unrealized_pnl_calc": 0.0,
                    "market_value": 0.0,
                    "realized_pnl": float(replay.realized_by_symbol.get(sym, 0.0)),
                }
            )

        cash = float(snap.get("cash") or 0.0)
        total_eval = float(snap.get("total_evaluated_amt") or 0.0)
        equity = total_eval if total_eval > 0 else cash + sum(
            float(p.get("market_value") or 0) for p in snap.get("positions", [])
        )

        eq_track = EquityTracker(equity_p, logger=_logger)
        daily_pct, cumulative_pct = eq_track.pnl_snapshot(equity)
        st = _read_json(equity_p)
        day_open = float(st.get("day_open_equity") or 0.0) if st else 0.0
        baseline = float(st.get("baseline_equity") or 0.0) if st else 0.0
        daily_krw = equity - day_open if day_open > 0 else 0.0
        cumulative_krw = equity - baseline if baseline > 0 else 0.0

        def _latest_buy_strategy(sym: str) -> str:
            for f in reversed(_sort_fills([x for x in all_fills if x.get("symbol") == sym])):
                if str(f.get("side")) == "buy":
                    return str(f.get("strategy_id") or "unknown")
            return "unknown"

        per_strategy: dict[str, dict[str, float]] = {}
        for sid, amt in replay.realized_by_strategy.items():
            per_strategy[sid] = {
                "realized_pnl": float(amt),
                "unrealized_pnl": 0.0,
                "total_pnl": float(amt),
            }
        for sym, krow in kis_positions.items():
            if int(krow.get("quantity") or 0) <= 0:
                continue
            sid = _latest_buy_strategy(sym)
            bucket = per_strategy.setdefault(
                sid, {"realized_pnl": 0.0, "unrealized_pnl": 0.0, "total_pnl": 0.0}
            )
            bucket["unrealized_pnl"] = float(bucket.get("unrealized_pnl", 0.0)) + float(
                krow.get("unrealized_pnl_kis") or 0.0
            )
        for sid, b in per_strategy.items():
            b["total_pnl"] = float(b.get("realized_pnl", 0.0)) + float(b.get("unrealized_pnl", 0.0))

        snapshot: dict[str, Any] = {
            "updated_at_utc": _utc_now_iso(),
            "cash": cash,
            "equity": equity,
            "total_evaluated_amt": total_eval,
            "unrealized_pnl": unrealized_kis_sum,
            "realized_pnl": replay.total_realized,
            "daily_pnl_pct": daily_pct,
            "cumulative_pnl_pct": cumulative_pct,
            "daily_pnl_krw": daily_krw,
            "cumulative_pnl_krw": cumulative_krw,
            "position_count": len(kis_positions),
            "positions": merged_positions,
            "per_symbol": {
                sym: {
                    "realized_pnl": float(replay.realized_by_symbol.get(sym, 0.0)),
                    "unrealized_pnl": float(kis_positions[sym].get("unrealized_pnl_kis") or 0.0)
                    if sym in kis_positions
                    else 0.0,
                    "quantity": int(kis_positions[sym]["quantity"])
                    if sym in kis_positions
                    else int(replay.positions[sym].quantity)
                    if sym in replay.positions
                    else 0,
                }
                for sym in set(replay.realized_by_symbol) | set(kis_positions.keys()) | set(replay.positions.keys())
            },
            "per_strategy": per_strategy,
            "warnings": warnings,
            "mismatches": mismatches,
            "fills_stored": len(all_fills),
            "new_fills_this_sync": new_count,
            "backfill_days": backfill_days,
        }

        for w in warnings:
            _logger.warning("portfolio sync: %s", w)

        _write_json(state_p, snapshot)
        append_jsonl(
            pnl_hist_p,
            {
                "ts_utc": _utc_now_iso(),
                "equity": equity,
                "cash": cash,
                "unrealized_pnl": unrealized_kis_sum,
                "realized_pnl": replay.total_realized,
                "daily_pnl_pct": daily_pct,
                "cumulative_pnl_pct": cumulative_pct,
                "daily_pnl_krw": daily_krw,
                "cumulative_pnl_krw": cumulative_krw,
                "warning_count": len(warnings),
            },
        )

        _reset_failures(fail_p)
        if flag_p.is_file():
            try:
                flag_p.unlink()
            except OSError:
                pass

        return SyncRunResult(ok=True, message="ok", snapshot=snapshot)

    def _record_failure(self, fail_p: Path, msg: str, flag_p: Path, s: BackendSettings) -> None:
        data = _read_json(fail_p)
        n = int(data.get("consecutive_failures") or 0) + 1
        row = {
            "consecutive_failures": n,
            "last_error": msg,
            "last_at_utc": _utc_now_iso(),
        }
        _write_json(fail_p, row)
        _logger.error("portfolio sync failure #%s: %s", n, msg)
        if n >= s.portfolio_sync_max_consecutive_failures:
            append_risk_event(
                s.risk_events_jsonl,
                {
                    "ts_utc": _utc_now_iso(),
                    "event_type": "PORTFOLIO_SYNC_FAIL_THRESHOLD",
                    "consecutive_failures": n,
                    "last_error": msg,
                    "risk_review_recommended": True,
                    "note": "포트폴리오 동기화 연속 실패 — 브로커 상태 확인 후 risk_off 검토",
                },
            )
            flag_p.parent.mkdir(parents=True, exist_ok=True)
            flag_p.write_text(
                json.dumps(
                    {"ts_utc": _utc_now_iso(), "consecutive_failures": n, "last_error": msg},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )


def _reset_failures(fail_p: Path) -> None:
    _write_json(fail_p, {"consecutive_failures": 0, "last_error": "", "last_at_utc": _utc_now_iso()})


def run_portfolio_sync(*, backfill_days: int = 7, settings: BackendSettings | None = None) -> SyncRunResult:
    return PortfolioSyncEngine(settings=settings).sync(backfill_days=backfill_days)


def load_last_snapshot(settings: BackendSettings | None = None) -> dict[str, Any] | None:
    s = settings or get_backend_settings()
    p = Path(s.portfolio_data_dir) / "sync_state.json"
    if not p.is_file():
        return None
    data = _read_json(p)
    return data if data else None


def install_portfolio_sync_background(settings: BackendSettings | None = None) -> None:
    s = settings or get_backend_settings()
    interval = int(s.portfolio_sync_interval_sec)
    if interval <= 0:
        return

    def _loop() -> None:
        time.sleep(2.0)
        while True:
            try:
                run_portfolio_sync(backfill_days=s.portfolio_sync_backfill_days, settings=s)
            except Exception:
                _logger.exception("portfolio sync background loop error")
            time.sleep(float(interval))

    t = threading.Thread(target=_loop, name="portfolio-sync", daemon=True)
    t.start()
    _logger.info("portfolio sync background started (interval=%ss)", interval)
