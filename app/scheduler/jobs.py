from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import uuid

import pandas as pd

from app.brokers.base_broker import BaseBroker
from app.brokers.paper_broker import PaperBroker
from app.orders.models import OrderRequest, OrderSignal
from app.orders.order_manager import OrderManager
from app.portfolio.pnl import compute_cumulative_return_pct, compute_daily_return_pct
from app.risk.kill_switch import KillSwitch
from app.risk.rules import RiskSnapshot, RiskRules
from app.scheduler.equity_tracker import EquityTracker
from app.strategy.base_strategy import StrategyContext
from app.scheduler.kis_universe import build_mock_volatility_series
from app.strategy.filters import explain_swing_candidate_filters, filter_quality_swing_candidates
from app.strategy.market_regime import MarketRegimeConfig, MarketRegimeInputs, classify_market_regime
from app.strategy.swing_strategy import SwingStrategy


def _order_request_to_dict(order: OrderRequest) -> dict[str, object]:
    return {
        "symbol": order.symbol,
        "side": order.side,
        "quantity": order.quantity,
        "price": order.price,
        "stop_loss_pct": order.stop_loss_pct,
        "strategy_id": order.strategy_id,
    }


def _no_order_reason(
    *,
    halted: bool,
    halt_message: str | None,
    candidate_count: int,
    generated_order_count: int,
    regime: str | None,
    position_count: int,
) -> str:
    if halted:
        return (halt_message or "").strip() or "사이클 중단"
    if candidate_count == 0:
        return "후보 종목 없음"
    if regime == "high_volatility_risk" and generated_order_count == 0:
        return "고변동 리스크 국면으로 신규 진입 차단"
    if generated_order_count == 0 and position_count > 0:
        return "기존 포지션 보유 중이며 추가 진입 없음(청산·홀드만 해당할 수 있음)"
    if generated_order_count == 0:
        return "후보는 있으나 전략 진입 조건 미충족"
    return ""


@dataclass
class SchedulerJobs:
    strategy: SwingStrategy = field(default_factory=SwingStrategy)
    broker: BaseBroker = field(default_factory=PaperBroker)
    risk_rules: RiskRules = field(default_factory=RiskRules)
    kill_switch: KillSwitch | None = None
    equity_tracker: EquityTracker | None = None
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("app.scheduler.jobs"))

    def run_daily_cycle(
        self,
        universe: pd.DataFrame | None = None,
        *,
        kospi_index: pd.DataFrame | None = None,
        sp500_index: pd.DataFrame | None = None,
    ) -> dict[str, object]:
        self.logger.info("[START] Paper trading daily cycle started")
        universe = universe if universe is not None else self._build_mock_universe()
        if universe.empty:
            self.logger.error("[ABORT] Empty price universe; skip cycle")
            return {
                "halted": True,
                "reason": "EMPTY_UNIVERSE",
                "message": "No OHLC data for configured symbols",
                "candidate_count": 0,
                "candidates": [],
                "candidate_filter_breakdown": [],
                "generated_order_count": 0,
                "generated_orders": [],
                "regime": None,
                "no_order_reason": "유니버스 가격 데이터 없음",
                "last_diagnostics": [],
            }

        kospi = kospi_index if kospi_index is not None else self._build_mock_index("KOSPI")
        sp500 = sp500_index if sp500_index is not None else self._build_mock_index("SP500")
        vol = build_mock_volatility_series(kospi)
        rcfg = getattr(self.strategy, "regime_config", MarketRegimeConfig())
        regime_snap = classify_market_regime(
            MarketRegimeInputs(kospi=kospi, sp500=sp500, volatility=vol),
            rcfg,
        )
        regime_label = regime_snap.regime

        cand_fn = getattr(self.strategy, "paper_candidate_symbols", None)
        if callable(cand_fn):
            candidates = cand_fn(universe)
        else:
            candidates = filter_quality_swing_candidates(universe)
        candidate_count = len(candidates)
        candidates_sorted = sorted(list(candidates))
        candidate_filter_breakdown: list = []
        if candidate_count == 0 and not universe.empty:
            candidate_filter_breakdown = explain_swing_candidate_filters(universe)
        self.logger.info("[PRE-MARKET] Candidate count=%s symbols=%s", candidate_count, candidates_sorted)

        snapshot_gate = self._build_risk_snapshot(universe)
        if self.kill_switch is not None:
            try:
                from backend.app.risk.kill_switch import attach_kill_switch_event_logging

                attach_kill_switch_event_logging(self.kill_switch)
            except Exception:
                pass
        if self.kill_switch is not None and self.kill_switch.evaluate(snapshot_gate):
            self.logger.warning(
                "[HALT] Kill switch active state=%s reason=%s",
                self.kill_switch.state,
                self.kill_switch.last_reason,
            )
            pos_n = len(self.broker.get_positions())
            halt_msg = f"킬스위치 활성 — {self.kill_switch.last_reason}"
            return {
                "halted": True,
                "kill_state": self.kill_switch.state,
                "reason": self.kill_switch.last_reason,
                "equity": snapshot_gate.equity,
                "daily_pnl_pct": snapshot_gate.daily_pnl_pct,
                "total_pnl_pct": snapshot_gate.total_pnl_pct,
                "candidate_count": candidate_count,
                "candidates": candidates_sorted,
                "candidate_filter_breakdown": candidate_filter_breakdown,
                "generated_order_count": 0,
                "generated_orders": [],
                "regime": regime_label,
                "no_order_reason": _no_order_reason(
                    halted=True,
                    halt_message=halt_msg,
                    candidate_count=candidate_count,
                    generated_order_count=0,
                    regime=regime_label,
                    position_count=pos_n,
                ),
                "last_diagnostics": [],
            }

        self.logger.info("[INTRADAY] Price check and strategy signal generation")
        context = StrategyContext(
            prices=universe,
            kospi_index=kospi,
            sp500_index=sp500,
            portfolio=self._portfolio_df_from_broker(),
            volatility_index=vol,
        )
        strategy_orders = self.strategy.generate_orders(context)
        self.logger.info("[INTRADAY] Generated %s raw strategy orders", len(strategy_orders))
        if getattr(self.strategy, "last_ranking", None):
            ranking_lines = [
                f"{r.symbol}:{r.total_score:.3f} ({', '.join(r.reasons)})"
                for r in self.strategy.last_ranking
            ]
            self.logger.info("[INTRADAY] Ranking top picks: %s", " | ".join(ranking_lines))

        order_manager = OrderManager(broker=self.broker, risk_rules=self.risk_rules)
        accepted = 0
        rejected = 0
        for order in strategy_orders:
            signal = OrderSignal(
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                limit_price=order.price or self._latest_close(universe, order.symbol),
                stop_loss_pct=order.stop_loss_pct,
                strategy_id=order.strategy_id,
                signal_id=str(uuid.uuid4()),
            )
            snapshot = self._build_risk_snapshot(universe)
            result = order_manager.process_signal(signal, snapshot)
            if result.accepted:
                accepted += 1
                self.logger.info("[INTRADAY] Order accepted id=%s msg=%s", result.order_id, result.message)
            else:
                rejected += 1
                self.logger.warning("[INTRADAY] Order rejected msg=%s", result.message)

        self.logger.info("[CLOSE] Building end-of-day report")
        report = self._build_end_of_day_report(universe, accepted=accepted, rejected=rejected)
        report["ranking"] = [
            {
                "symbol": r.symbol,
                "score": round(r.total_score, 4),
                "factors": r.factor_scores,
                "reasons": r.reasons,
            }
            for r in getattr(self.strategy, "last_ranking", [])
        ]
        report["candidate_count"] = candidate_count
        report["candidates"] = candidates_sorted
        report["candidate_filter_breakdown"] = candidate_filter_breakdown
        report["generated_order_count"] = len(strategy_orders)
        report["generated_orders"] = [_order_request_to_dict(o) for o in strategy_orders]
        report["regime"] = regime_label
        report["last_diagnostics"] = list(getattr(self.strategy, "last_diagnostics", []) or [])
        pos_n = len(self.broker.get_positions())
        report["no_order_reason"] = _no_order_reason(
            halted=False,
            halt_message=None,
            candidate_count=candidate_count,
            generated_order_count=len(strategy_orders),
            regime=regime_label,
            position_count=pos_n,
        )
        self.logger.info("[DONE] Daily cycle complete: %s", report)
        return report

    def _build_risk_snapshot(self, price_df: pd.DataFrame) -> RiskSnapshot:
        cash = self.broker.get_cash()
        positions = self.broker.get_positions()
        position_values: dict[str, float] = {}
        for pos in positions:
            latest_price = self._latest_close(price_df, pos.symbol)
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
                    "hold_days": 1,
                }
            )
        return pd.DataFrame(rows, columns=["symbol", "quantity", "average_price", "hold_days"])

    def _build_end_of_day_report(self, price_df: pd.DataFrame, *, accepted: int, rejected: int) -> dict[str, object]:
        cash = self.broker.get_cash()
        positions = self.broker.get_positions()
        market_value = sum(self._latest_close(price_df, p.symbol) * p.quantity for p in positions)
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

    @staticmethod
    def _latest_close(price_df: pd.DataFrame, symbol: str) -> float:
        row = price_df[price_df["symbol"] == symbol].sort_values("date").iloc[-1]
        return float(row["close"])

    @staticmethod
    def _build_mock_universe() -> pd.DataFrame:
        symbols = ["005930", "000660", "035420"]
        rows: list[dict[str, object]] = []
        end = datetime.now(timezone.utc).date()
        for symbol in symbols:
            for i in range(80):
                d = end - timedelta(days=80 - i)
                base = 50000 + i * 100
                close = float(base if symbol != "035420" else base * 0.8)
                # Last 3 days pullback for one candidate to trigger entry pattern.
                if symbol == "005930" and i >= 77:
                    close = close * (0.98 - (80 - i) * 0.01)
                rows.append(
                    {
                        "symbol": symbol,
                        "date": pd.Timestamp(d),
                        "open": close * 0.995,
                        "high": close * 1.01,
                        "low": close * 0.99,
                        "close": close,
                        "volume": 1_000_000 + i * 5000,
                    }
                )
        return pd.DataFrame(rows)

    @staticmethod
    def _build_mock_index(name: str) -> pd.DataFrame:
        _ = name
        end = datetime.now(timezone.utc).date()
        rows = []
        for i in range(40):
            d = end - timedelta(days=40 - i)
            close = 2500 + i * 2
            rows.append({"date": pd.Timestamp(d), "close": float(close)})
        return pd.DataFrame(rows)
