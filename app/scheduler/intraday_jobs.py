"""Paper 인트라데이(분봉) 사이클 — 일봉 `run_daily_cycle` 과 분리."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from app.brokers.base_broker import BaseBroker
from app.brokers.paper_broker import PaperBroker
from app.clients.kis_client import KISClient, KISClientError
from app.config import get_settings
from app.orders.models import OrderRequest, OrderSignal
from app.orders.order_manager import OrderManager
from app.portfolio.pnl import compute_cumulative_return_pct, compute_daily_return_pct
from app.risk.kill_switch import KillSwitch
from app.risk.rules import RiskSnapshot, RiskRules
from app.scheduler.equity_tracker import EquityTracker
from app.scheduler.kis_intraday import first_intraday_api_error_row, summarize_intraday_fetch_errors
from app.scheduler.kis_universe import build_mock_volatility_series
from app.strategy.base_strategy import StrategyContext
from app.strategy.intraday_common import (
    IntradaySessionSnapshot,
    analyze_krx_intraday_session,
    krx_session_config_from_settings,
    should_force_flatten_before_close_kst,
)
from app.strategy.intraday_paper_state import IntradayPaperStateStore, iso_now_utc
from app.strategy.market_regime import MarketRegimeConfig, MarketRegimeInputs, classify_market_regime

_KST = ZoneInfo("Asia/Seoul")


def _order_request_to_dict(order: OrderRequest) -> dict[str, object]:
    return {
        "symbol": order.symbol,
        "side": order.side,
        "quantity": order.quantity,
        "price": order.price,
        "stop_loss_pct": order.stop_loss_pct,
        "strategy_id": order.strategy_id,
    }


def _intraday_no_order_reason(
    *,
    halted: bool,
    halt_message: str | None,
    forced_flatten: bool,
    fetch_allowed: bool,
    order_allowed: bool,
    fetch_block_reason: str,
    order_block_reason: str,
    krx_session_state: str,
    minute_bars_present: bool,
    symbols_request_count: int,
    candidate_count: int,
    generated_order_count: int,
) -> str:
    if halted:
        return (halt_message or "").strip() or "사이클 중단"
    if forced_flatten:
        return "장 종료 직전 강제 청산 틱"
    if not fetch_allowed:
        return _human_fetch_block_message(fetch_block_reason, krx_session_state)
    if symbols_request_count > 0 and not minute_bars_present:
        return "분봉 API 응답 없음"
    if not order_allowed:
        return _human_order_block_message(krx_session_state, order_block_reason)
    if candidate_count > 0 and generated_order_count == 0:
        return "후보는 있으나 전략 신호 0개"
    if generated_order_count == 0:
        return "조회 종목은 있으나 후보 0개"
    return ""


def _human_fetch_block_message(code: str, state: str) -> str:
    c = (code or "").strip()
    if c == "skipped_closed_session":
        return "완전 장외(또는 세션 밖) — 분봉 조회 안 함"
    if c == "skipped_preopen_disabled":
        return "장전 구간이나 설정에서 장전 분봉 조회 비활성"
    if c == "skipped_afterhours_disabled":
        return "장후 구간이나 설정에서 장후 분봉 조회 비활성"
    return f"분봉 조회 비활성({state}, {c or 'reason_unknown'})"


def _human_order_block_message(state: str, order_block_reason: str) -> str:
    r = (order_block_reason or "").strip()
    if r == "extended_order_disabled":
        return f"{_session_label_ko(state)} — 실제 주문 비활성(확장 주문 플래그 OFF)"
    if r == "kis_domestic_order_regular_hours_only":
        return f"{_session_label_ko(state)} — 국내 REST 주문은 정규장 기준만(코드상 장전·장후 전용 파라미터 없음) — 관찰만"
    if r == "closed_session":
        return "세션 외 — 주문 불가"
    return f"주문 비활성({state}, {r or 'reason_unknown'})"


def _session_label_ko(state: str) -> str:
    s = (state or "").strip()
    if s == "pre_open":
        return "장전 세션"
    if s == "after_hours":
        return "장후 세션"
    if s == "regular":
        return "정규장"
    return s or "세션"


@dataclass
class IntradaySchedulerJobs:
    strategy: Any
    broker: BaseBroker = field(default_factory=PaperBroker)
    risk_rules: RiskRules = field(default_factory=RiskRules)
    kill_switch: KillSwitch | None = None
    equity_tracker: EquityTracker | None = None
    state_store: IntradayPaperStateStore | None = None
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("app.scheduler.intraday_jobs"))
    manual_override_enabled: bool = False

    def run_intraday_cycle(
        self,
        *,
        universe_tf: pd.DataFrame,
        kospi_index: pd.DataFrame,
        sp500_index: pd.DataFrame,
        timeframe: str,
        quote_by_symbol: dict[str, dict[str, Any]],
        forced_flatten: bool,
        paper_trading_symbols_resolved: list[str] | None = None,
        intraday_bar_fetch_summary: list[dict[str, Any]] | None = None,
        intraday_universe_row_count: int | None = None,
        regular_session_kst: bool | None = None,
        intraday_session_snapshot: IntradaySessionSnapshot | None = None,
    ) -> dict[str, Any]:
        cfg = get_settings()
        self.logger.info("[INTRADAY] cycle start tf=%s rows=%s", timeframe, len(universe_tf))

        sym_res = [s.strip() for s in (paper_trading_symbols_resolved or []) if s and str(s).strip()]
        fetch_summary = list(intraday_bar_fetch_summary or [])
        snap = intraday_session_snapshot or analyze_krx_intraday_session(
            session_config=krx_session_config_from_settings(cfg),
        )
        reg_kst = bool(regular_session_kst) if regular_session_kst is not None else snap.regular_session_kst
        fetch_ok = bool(snap.fetch_allowed)
        order_ok = bool(snap.order_allowed)
        urows = int(intraday_universe_row_count) if intraday_universe_row_count is not None else int(len(universe_tf))
        symbols_request_count = len(sym_res)

        st_store = self.state_store
        state = st_store.load() if st_store else None
        if state is None:
            from app.strategy.intraday_paper_state import IntradayPaperState

            state = IntradayPaperState()

        vol = build_mock_volatility_series(kospi_index)
        rcfg = getattr(self.strategy, "regime_config", MarketRegimeConfig())
        regime_snap = classify_market_regime(
            MarketRegimeInputs(kospi=kospi_index, sp500=sp500_index, volatility=vol),
            rcfg,
        )
        regime_label = regime_snap.regime

        candidate_syms = sorted({str(s).strip() for s in universe_tf["symbol"].unique()}) if not universe_tf.empty else []
        candidate_count = len(candidate_syms)

        minute_bars_present = urows > 0
        session_ok = fetch_ok and candidate_count > 0

        snapshot_gate = self._build_risk_snapshot(universe_tf)
        daily_pct = float(snapshot_gate.daily_pnl_pct)
        risk_halt = (not self.manual_override_enabled) and (daily_pct <= -float(cfg.paper_intraday_max_daily_loss_pct))
        self.strategy.intraday_state = state
        self.strategy.quote_by_symbol = quote_by_symbol
        self.strategy.risk_halt_new_entries = risk_halt
        setattr(self.strategy, "manual_override_enabled", bool(self.manual_override_enabled))
        self.strategy.intraday_session_context = {
            "krx_session_state": snap.state,
            "fetch_allowed": snap.fetch_allowed,
            "order_allowed": snap.order_allowed,
            "fetch_block_reason": snap.fetch_block_reason,
            "order_block_reason": snap.order_block_reason,
            "regular_session_kst": snap.regular_session_kst,
        }
        if hasattr(self.strategy, "timeframe_label"):
            self.strategy.timeframe_label = timeframe

        if self.kill_switch is not None:
            try:
                from backend.app.risk.kill_switch import attach_kill_switch_event_logging

                attach_kill_switch_event_logging(self.kill_switch)
            except Exception:
                pass
        if (not self.manual_override_enabled) and self.kill_switch is not None and self.kill_switch.evaluate(snapshot_gate):
            pos_n = len(self.broker.get_positions())
            halt_msg = f"킬스위치 활성 — {self.kill_switch.last_reason}"
            return self._report(
                halted=True,
                reason=self.kill_switch.last_reason,
                regime_label=regime_label,
                universe_tf=universe_tf,
                candidate_syms=candidate_syms,
                state=state,
                forced_flatten=forced_flatten,
                session_ok=session_ok,
                daily_pct=daily_pct,
                risk_halt=risk_halt,
                accepted=0,
                rejected=0,
                strategy_orders=[],
                halt_message=halt_msg,
                pos_n=pos_n,
                paper_trading_symbols_resolved=sym_res,
                intraday_bar_fetch_summary=fetch_summary,
                intraday_universe_row_count=urows,
                regular_session_kst=reg_kst,
                intraday_session_snapshot=snap,
                minute_bars_present=minute_bars_present,
                symbols_request_count=symbols_request_count,
            )

        context = StrategyContext(
            prices=universe_tf,
            kospi_index=kospi_index,
            sp500_index=sp500_index,
            portfolio=self._portfolio_df_from_broker(),
            volatility_index=vol,
        )
        strategy_orders = self.strategy.generate_orders(context)
        self.logger.info("[INTRADAY] raw orders=%s", len(strategy_orders))

        order_manager = OrderManager(broker=self.broker, risk_rules=self.risk_rules)
        accepted = 0
        rejected = 0
        filtered: list[OrderRequest] = []

        for order in strategy_orders:
            if order.side == "buy":
                gate = self._intraday_buy_gate(order.symbol, state, cfg)
                if not gate["ok"]:
                    self.logger.info("[INTRADAY] buy gated symbol=%s reason=%s", order.symbol, gate["reason"])
                    rejected += 1
                    continue
            filtered.append(order)

        orders_blocked_session = 0
        for order in filtered:
            if not order_ok:
                orders_blocked_session += 1
                self.logger.info(
                    "[INTRADAY] order suppressed by session state=%s reason=%s",
                    snap.state,
                    snap.order_block_reason,
                )
                continue
            signal = OrderSignal(
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                limit_price=order.price or self._latest_close(universe_tf, order.symbol),
                stop_loss_pct=order.stop_loss_pct,
                strategy_id=order.strategy_id,
                signal_id=str(uuid.uuid4()),
            )
            snapshot = self._build_risk_snapshot(universe_tf)
            result = order_manager.process_signal(signal, snapshot)
            if result.accepted:
                accepted += 1
                self._on_accepted_order(order, state, cfg)
                self.logger.info("[INTRADAY] accepted id=%s", result.order_id)
            else:
                rejected += 1
                self.logger.warning("[INTRADAY] rejected msg=%s", result.message)

        if st_store:
            st_store.save(state)

        rep = self._build_report(
            universe_tf,
            accepted=accepted,
            rejected=rejected,
            strategy_orders=strategy_orders,
            filtered_orders=filtered,
        )
        pos_n = len(self.broker.get_positions())
        rep.update(
            {
                "halted": False,
                "kill_state": None,
                "reason": None,
                "regime": regime_label,
                "candidate_count": candidate_count,
                "candidates": candidate_syms,
                "generated_order_count": len(strategy_orders),
                "generated_orders": [_order_request_to_dict(o) for o in strategy_orders],
                "last_diagnostics": list(getattr(self.strategy, "last_diagnostics", []) or []),
                "timeframe": timeframe,
                "intraday_filter_breakdown": list(getattr(self.strategy, "last_intraday_filter_breakdown", []) or []),
                "intraday_signal_breakdown": dict(getattr(self.strategy, "last_intraday_signal_breakdown", {}) or {}),
                "trade_count_today": int(state.trade_count_today),
                "cooldown_symbols": sorted(state.cooldown_until_iso.keys()),
                "forced_flatten": bool(forced_flatten),
                "flatten_before_close_armed": bool(
                    should_force_flatten_before_close_kst(
                        minutes_before_close=int(cfg.paper_intraday_flatten_before_close_minutes),
                        session_config=krx_session_config_from_settings(cfg),
                    )
                ),
                "session_open_kst": reg_kst,
                "regular_session_kst": reg_kst,
                "krx_session_state": snap.state,
                "fetch_allowed": fetch_ok,
                "order_allowed": order_ok,
                "fetch_block_reason": snap.fetch_block_reason,
                "order_block_reason": snap.order_block_reason,
                "orders_blocked_session": int(orders_blocked_session),
                "minute_bars_present": minute_bars_present,
                "symbols_request_count": symbols_request_count,
                "paper_trading_symbols_resolved": sym_res,
                "intraday_bar_fetch_summary": fetch_summary,
                "fetch_error_summary": summarize_intraday_fetch_errors(fetch_summary),
                "intraday_first_api_error": first_intraday_api_error_row(fetch_summary),
                "intraday_universe_row_count": urows,
                "daily_pnl_pct_snapshot": daily_pct,
                "risk_halt_new_entries": risk_halt,
                "paper_intraday_target_round_trip_trades": int(cfg.paper_intraday_target_round_trip_trades),
                "ranking": [],
                "no_order_reason": _intraday_no_order_reason(
                    halted=False,
                    halt_message=None,
                    forced_flatten=forced_flatten,
                    fetch_allowed=fetch_ok,
                    order_allowed=order_ok,
                    fetch_block_reason=snap.fetch_block_reason,
                    order_block_reason=snap.order_block_reason,
                    krx_session_state=snap.state,
                    minute_bars_present=minute_bars_present,
                    symbols_request_count=symbols_request_count,
                    candidate_count=candidate_count,
                    generated_order_count=len(strategy_orders),
                ),
            }
        )
        rep["no_order_reason"] = self._refine_no_order_reason(
            rep,
            pos_n,
            session_ok_effective=session_ok,
        )
        self.logger.info("[INTRADAY] done %s", {k: rep[k] for k in ("accepted_orders", "rejected_orders", "trade_count_today") if k in rep})
        return rep

    def _refine_no_order_reason(
        self,
        rep: dict[str, Any],
        pos_n: int,
        *,
        session_ok_effective: bool,
    ) -> str:
        _ = session_ok_effective
        base = str(rep.get("no_order_reason") or "")
        gen_ct = int(rep.get("generated_order_count") or 0)
        if gen_ct > 0 and not rep.get("order_allowed", True):
            return "세션 정책으로 주문 실행 차단(신호는 생성됨)"
        if gen_ct > 0:
            return ""
        if (
            not rep.get("minute_bars_present")
            and int(rep.get("symbols_request_count") or 0) > 0
            and rep.get("intraday_first_api_error")
        ):
            return (
                "분봉 KIS API 오류(api_error)로 데이터가 없어 전략 조건 평가 전에 중단됨 "
                "(조건 미충족 아님 · intraday_first_api_error·심볼별 요약 참고)"
            )
        if not rep.get("fetch_allowed", True):
            return base or "분봉 조회 비활성"
        if not rep.get("order_allowed", True):
            return base or "확장 세션 — 주문 비활성"
        if not rep.get("regular_session_kst", rep.get("session_open_kst")):
            if any(x in base for x in ("분봉", "장전", "장후", "장외")):
                return base
            return base or "정규장 외"
        if rep.get("risk_halt_new_entries"):
            return "인트라데이 일중 손실 한도로 신규 진입 중지"
        if rep.get("regime") == "high_volatility_risk":
            return "고변동 국면으로 신규 진입 제한"
        if pos_n > 0 and "후보는 있으나" in base:
            return "포지션 관리·청산만 해당 (신규 진입 없음)"
        if pos_n > 0 and base.endswith("주문 없음"):
            return "포지션 관리·청산 조건만 해당될 수 있음(신규 없음)"
        return base or "조건 미충족"

    def _intraday_buy_gate(self, symbol: str, state: Any, cfg: Any) -> dict[str, Any]:
        now_m = time.monotonic()
        dup = float(cfg.paper_intraday_duplicate_order_guard_sec)
        last = float(state.last_buy_mono.get(symbol, 0.0))
        if dup > 0 and last > 0 and (now_m - last) < dup:
            return {"ok": False, "reason": "duplicate_order_guard"}
        cd_iso = state.cooldown_until_iso.get(symbol)
        if cd_iso:
            try:
                cd = datetime.fromisoformat(cd_iso.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) < cd:
                    return {"ok": False, "reason": "cooldown"}
            except ValueError:
                pass
        return {"ok": True, "reason": ""}

    def _on_accepted_order(self, order: OrderRequest, state: Any, cfg: Any) -> None:
        now_m = time.monotonic()
        if order.side == "buy":
            state.last_buy_mono[order.symbol] = now_m
            state.entry_ts_iso[order.symbol] = iso_now_utc()
            px = float(order.price or 0.0)
            if px > 0:
                state.peak_price[order.symbol] = px
            state.trade_count_today += 1
            cd_min = int(cfg.paper_intraday_cooldown_minutes)
            if cd_min > 0:
                until = datetime.now(timezone.utc) + timedelta(minutes=cd_min)
                state.cooldown_until_iso[order.symbol] = until.isoformat()
        elif order.side == "sell":
            state.entry_ts_iso.pop(order.symbol, None)
            state.peak_price.pop(order.symbol, None)
            state.cooldown_until_iso.pop(order.symbol, None)

    def _report(
        self,
        *,
        halted: bool,
        reason: str | None,
        regime_label: str,
        universe_tf: pd.DataFrame,
        candidate_syms: list[str],
        state: Any,
        forced_flatten: bool,
        session_ok: bool,
        daily_pct: float,
        risk_halt: bool,
        accepted: int,
        rejected: int,
        strategy_orders: list[OrderRequest],
        halt_message: str,
        pos_n: int,
        paper_trading_symbols_resolved: list[str] | None = None,
        intraday_bar_fetch_summary: list[dict[str, Any]] | None = None,
        intraday_universe_row_count: int = 0,
        regular_session_kst: bool = False,
        minute_bars_present: bool = False,
        symbols_request_count: int = 0,
        intraday_session_snapshot: IntradaySessionSnapshot | None = None,
    ) -> dict[str, Any]:
        cfg = get_settings()
        snap = intraday_session_snapshot or analyze_krx_intraday_session(
            session_config=krx_session_config_from_settings(cfg),
        )
        rep = self._build_report(universe_tf, accepted=accepted, rejected=rejected, strategy_orders=strategy_orders)
        sym_res = list(paper_trading_symbols_resolved or [])
        sreq = int(symbols_request_count or len(sym_res))
        urows = int(intraday_universe_row_count or 0)
        mb = bool(minute_bars_present) if minute_bars_present is not None else urows > 0
        fs = list(intraday_bar_fetch_summary or [])
        rep.update(
            {
                "halted": halted,
                "reason": reason,
                "regime": regime_label,
                "candidate_count": len(candidate_syms),
                "candidates": candidate_syms,
                "generated_order_count": len(strategy_orders),
                "generated_orders": [_order_request_to_dict(o) for o in strategy_orders],
                "last_diagnostics": [],
                "timeframe": "",
                "intraday_filter_breakdown": [],
                "intraday_signal_breakdown": {},
                "trade_count_today": int(state.trade_count_today),
                "cooldown_symbols": sorted(state.cooldown_until_iso.keys()),
                "forced_flatten": forced_flatten,
                "session_open_kst": bool(regular_session_kst),
                "regular_session_kst": bool(regular_session_kst),
                "krx_session_state": snap.state,
                "fetch_allowed": snap.fetch_allowed,
                "order_allowed": snap.order_allowed,
                "fetch_block_reason": snap.fetch_block_reason,
                "order_block_reason": snap.order_block_reason,
                "orders_blocked_session": 0,
                "minute_bars_present": mb,
                "symbols_request_count": sreq,
                "paper_trading_symbols_resolved": sym_res,
                "intraday_bar_fetch_summary": fs,
                "fetch_error_summary": summarize_intraday_fetch_errors(fs),
                "intraday_first_api_error": first_intraday_api_error_row(fs),
                "intraday_universe_row_count": urows,
                "daily_pnl_pct_snapshot": daily_pct,
                "risk_halt_new_entries": risk_halt,
                "paper_intraday_target_round_trip_trades": int(cfg.paper_intraday_target_round_trip_trades),
                "ranking": [],
                "no_order_reason": _intraday_no_order_reason(
                    halted=True,
                    halt_message=halt_message,
                    forced_flatten=forced_flatten,
                    fetch_allowed=snap.fetch_allowed,
                    order_allowed=snap.order_allowed,
                    fetch_block_reason=snap.fetch_block_reason,
                    order_block_reason=snap.order_block_reason,
                    krx_session_state=snap.state,
                    minute_bars_present=mb,
                    symbols_request_count=sreq,
                    candidate_count=len(candidate_syms),
                    generated_order_count=len(strategy_orders),
                ),
            }
        )
        _ = pos_n
        return rep

    def _build_risk_snapshot(self, price_df: pd.DataFrame) -> RiskSnapshot:
        cash = self.broker.get_cash()
        positions = self.broker.get_positions()
        position_values: dict[str, float] = {}
        for pos in positions:
            latest_price = self._latest_close_safe(price_df, pos.symbol)
            position_values[pos.symbol] = latest_price * pos.quantity
        equity = cash + sum(position_values.values())
        if self.equity_tracker is not None:
            daily_pnl_pct, total_pnl_pct = self.equity_tracker.pnl_snapshot(equity)
        else:
            daily_pnl_pct = 0.0
            total_pnl_pct = 0.0
        return RiskSnapshot(
            daily_pnl_pct=daily_pnl_pct,
            total_pnl_pct=total_pnl_pct,
            equity=equity if equity > 0 else 1.0,
            market_filter_ok=True,
            position_values=position_values,
        )

    def _portfolio_df_from_broker(self) -> pd.DataFrame:
        rows = []
        for p in self.broker.get_positions():
            rows.append(
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "average_price": p.average_price,
                    "hold_days": 0,
                }
            )
        return pd.DataFrame(rows, columns=["symbol", "quantity", "average_price", "hold_days"])

    def _build_report(
        self,
        price_df: pd.DataFrame,
        *,
        accepted: int,
        rejected: int,
        strategy_orders: list[OrderRequest],
        filtered_orders: list[OrderRequest] | None = None,
    ) -> dict[str, object]:
        _ = filtered_orders
        cash = self.broker.get_cash()
        positions = self.broker.get_positions()
        market_value = sum(self._latest_close_safe(price_df, p.symbol) * p.quantity for p in positions)
        equity_now = cash + market_value
        equity_series = pd.Series([self.broker.initial_cash, equity_now], index=["start", "close"], dtype="float64")
        daily_ret = float(compute_daily_return_pct(equity_series).iloc[-1])
        cumulative_ret = float(compute_cumulative_return_pct(equity_series).iloc[-1])
        return {
            "accepted_orders": accepted,
            "rejected_orders": rejected,
            "cash": round(cash, 2),
            "market_value": round(market_value, 2),
            "equity": round(equity_now, 2),
            "daily_return_pct": round(daily_ret, 4),
            "cumulative_return_pct": round(cumulative_ret, 4),
            "position_count": len(positions),
        }

    def _latest_close_safe(self, price_df: pd.DataFrame, symbol: str) -> float:
        sub = price_df[price_df["symbol"] == symbol]
        if not sub.empty:
            row = sub.sort_values("date").iloc[-1]
            return float(row["close"])
        for pos in self.broker.get_positions():
            if pos.symbol == symbol:
                return float(pos.average_price or 1.0)
        return 1.0

    @staticmethod
    def _latest_close(price_df: pd.DataFrame, symbol: str) -> float:
        row = price_df[price_df["symbol"] == symbol].sort_values("date").iloc[-1]
        return float(row["close"])


def fetch_quotes_throttled(
    client: KISClient,
    symbols: list[str],
    *,
    min_interval_sec: float = 0.25,
    logger: logging.Logger | None = None,
) -> dict[str, dict[str, Any]]:
    """종목별 호가·거래대금(유동성 필터) — 클라이언트 스로틀에 더해 순차 간격."""
    log = logger or logging.getLogger("app.scheduler.intraday_jobs")
    out: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        sym = sym.strip()
        if not sym:
            continue
        try:
            if min_interval_sec > 0:
                time.sleep(min_interval_sec)
            out[sym] = client.get_quote(sym)
        except KISClientError as exc:
            log.warning("quote failed symbol=%s err=%s", sym, exc)
    return out


def infer_forced_flatten(cfg: Any) -> bool:
    sc = krx_session_config_from_settings(cfg)
    return should_force_flatten_before_close_kst(
        minutes_before_close=int(cfg.paper_intraday_flatten_before_close_minutes),
        session_config=sc,
    )
