from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import uuid

import pandas as pd

from app.brokers.paper_broker import PaperBroker
from app.orders.models import OrderSignal
from app.orders.order_manager import OrderManager
from app.portfolio.pnl import compute_cumulative_return_pct, compute_daily_return_pct
from app.risk.rules import RiskSnapshot, RiskRules
from app.strategy.base_strategy import StrategyContext
from app.strategy.filters import filter_quality_swing_candidates
from app.strategy.swing_strategy import SwingStrategy


@dataclass
class SchedulerJobs:
    strategy: SwingStrategy = field(default_factory=SwingStrategy)
    broker: PaperBroker = field(default_factory=PaperBroker)
    risk_rules: RiskRules = field(default_factory=RiskRules)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("app.scheduler.jobs"))

    def run_daily_cycle(self) -> dict[str, object]:
        self.logger.info("[START] Paper trading daily cycle started")
        universe = self._build_mock_universe()

        self.logger.info("[PRE-MARKET] Filtering quality swing candidates")
        candidates = filter_quality_swing_candidates(universe)
        self.logger.info("[PRE-MARKET] Candidate count=%s symbols=%s", len(candidates), candidates)

        self.logger.info("[INTRADAY] Price check and strategy signal generation")
        context = StrategyContext(
            prices=universe,
            kospi_index=self._build_mock_index("KOSPI"),
            sp500_index=self._build_mock_index("SP500"),
            portfolio=self._portfolio_df_from_broker(),
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
        # Demo values for simulation; real runtime should be DB/account based.
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
