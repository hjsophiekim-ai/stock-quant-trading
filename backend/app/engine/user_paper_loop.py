"""
앱에 저장된 KIS **모의** 자격증명으로 장중 1틱: 유니버스 → 전략 신호 → 리스크 → KisPaperBroker 주문.
서버 .env 계정과 무관하게 동작 (단, portfolio 백그라운드 sync 는 .env 기준이면 대시보드 정합은 .env 일치 권장).
"""

from __future__ import annotations

from dataclasses import replace
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.brokers.kis_paper_broker import KisPaperBroker
from app.brokers.kis_us_paper_broker import KisUsPaperBroker
from app.clients.kis_client import KISClientError
from app.config import get_settings, paper_final_betting_enabled_fresh
from app.risk.kill_switch import KillSwitch
from app.risk.rules import RiskLimits, RiskRules
from app.scheduler.equity_tracker import EquityTracker
from app.scheduler.final_betting_intraday_jobs import FinalBettingIntradayJobs
from app.scheduler.intraday_jobs import IntradaySchedulerJobs, fetch_quotes_throttled, infer_forced_flatten
from app.scheduler.jobs import SchedulerJobs
from app.scheduler.kis_intraday import (
    IntradayChartCache,
    build_intraday_universe_1m,
    universe_as_timeframe,
)
from app.scheduler.kis_universe import (
    build_kis_stock_universe,
    build_kospi_index_series,
    build_mock_sp500_proxy_from_kospi,
)
from app.strategy.intraday_common import analyze_krx_intraday_session, krx_session_config_from_settings
from app.strategy.intraday_paper_state import IntradayPaperStateStore

from backend.app.auth.kis_auth import issue_access_token
from backend.app.clients.kis_client import build_kis_client_for_paper_user
from backend.app.core.config import BackendSettings, get_backend_settings
from backend.app.engine.paper_strategy import strategy_for_paper_id
from backend.app.engine.portfolio_strategy_router import notionals_for_legs, route_swing_vs_scalp_symbols
from backend.app.market.us_paper_universe import (
    build_us_swing_daily_universe,
    fetch_us_minute_universe,
    minimal_macro_series,
)
from backend.app.market.us_session import analyze_us_equity_session, us_equity_session_to_intraday_snapshot

logger = logging.getLogger("backend.app.engine.user_paper_loop")


def _is_intraday_scalp_strategy(strategy_id: str) -> bool:
    s = (strategy_id or "").lower().strip()
    return s in (
        "scalp_momentum_v1",
        "scalp_momentum_v2",
        "scalp_momentum_v3",
        "scalp_macd_rsi_3m_v1",
        "scalp_rsi_flag_hf_v1",
    )


def _is_final_betting_strategy(strategy_id: str) -> bool:
    return (strategy_id or "").lower().strip() == "final_betting_v1"


def _is_us_scalp_strategy(strategy_id: str) -> bool:
    return (strategy_id or "").lower().strip() == "us_scalp_momentum_v1"


def _is_us_swing_strategy(strategy_id: str) -> bool:
    return (strategy_id or "").lower().strip() == "us_swing_relaxed_v1"


def _paper_risk_limits_for_strategy(strategy_id: str | None, cfg) -> RiskLimits:
    """전략 유형별 일손실·연패 적응 임계를 소폭 차등(스캘프는 더 타이트, 스윙은 휩소 여유)."""
    base = RiskLimits(
        daily_loss_limit_pct=cfg.daily_loss_limit_pct,
        total_loss_limit_pct=cfg.total_loss_limit_pct,
        default_stop_loss_pct=cfg.default_stop_loss_pct,
    )
    sid = (strategy_id or "").strip().lower()
    if any(x in sid for x in ("scalp_momentum", "scalp_macd", "scalp_rsi", "us_scalp")):
        return replace(
            base,
            daily_loss_limit_pct=min(float(base.daily_loss_limit_pct), 2.5),
            adaptive_loss_streak_threshold=3,
            rolling_loss_limit_pct=min(float(base.rolling_loss_limit_pct), 3.5),
        )
    if sid.startswith("swing") or "us_swing" in sid:
        return replace(
            base,
            adaptive_loss_streak_threshold=4,
            rolling_loss_limit_pct=max(float(base.rolling_loss_limit_pct), 4.5),
        )
    if "final_betting" in sid:
        return replace(
            base,
            adaptive_loss_streak_threshold=4,
            daily_loss_limit_pct=min(float(base.daily_loss_limit_pct), 2.75),
        )
    return base


class UserPaperTradingLoop:
    def __init__(
        self,
        *,
        app_key: str,
        app_secret: str,
        account_no: str,
        product_code: str,
        api_base: str,
        strategy_id: str,
        user_tag: str,
        backend_settings: BackendSettings | None = None,
        initial_access_token: str | None = None,
        initial_token_source_label: str | None = None,
        paper_market: str = "domestic",
        manual_override_enabled: bool = False,
    ) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._account_no = account_no
        self._product_code = product_code
        self._api_base = api_base.rstrip("/")
        self._strategy_id = strategy_id
        self._user_tag = user_tag
        self._backend = backend_settings or get_backend_settings()
        self._access_token: str | None = initial_access_token
        self._token_monotonic: float = time.monotonic() if initial_access_token else 0.0
        self._token_issued_locally: bool = False
        self._initial_token_source_label: str | None = initial_token_source_label
        self._paper_market = (paper_market or "domestic").strip().lower()
        self._manual_override_enabled = bool(manual_override_enabled)
        self._univ_sig: str | None = None
        self._univ_ts: float = 0.0
        self._univ_df: Any = None
        self._kospi_sig: str | None = None
        self._kospi_ts: float = 0.0
        self._kospi_df: Any = None
        self._last_token_failure_at_iso: str | None = None
        self._last_token_error_code: str | None = None
        self._last_token_http_status: int | None = None

    def _issue_token(self) -> str:
        tr = issue_access_token(
            app_key=self._app_key,
            app_secret=self._app_secret,
            base_url=self._api_base,
            timeout_sec=12,
        )
        self._last_token_http_status = tr.status_code
        if not tr.ok or not tr.access_token:
            code = tr.error_code or ""
            self._last_token_failure_at_iso = datetime.now(timezone.utc).isoformat()
            self._last_token_error_code = code or "TOKEN_FAILURE"
            msg = tr.message or "token_failed"
            if code == "TOKEN_RATE_LIMIT":
                raise RuntimeError("TOKEN_RATE_LIMIT: " + msg)
            raise RuntimeError(msg)
        self._last_token_failure_at_iso = None
        self._last_token_error_code = None
        self._access_token = tr.access_token
        self._token_monotonic = time.monotonic()
        self._token_issued_locally = True
        return tr.access_token

    def token_source_for_diagnostics(self) -> str:
        """브로커 메모리/DB 캐시·루프 내 재발급 구분 (diagnostics token_cache_source)."""
        if self._token_issued_locally:
            return "fresh_issue"
        if self._initial_token_source_label:
            return self._initial_token_source_label
        return "broker_reuse"

    def _kis_client(self):
        if not self._access_token or (time.monotonic() - self._token_monotonic) > 1500:
            self._issue_token()
        return build_kis_client_for_paper_user(
            base_url=self._api_base,
            access_token=self._access_token or "",
            app_key=self._app_key,
            app_secret=self._app_secret,
        )

    def _build_jobs(self, client, *, strategy_id: str | None = None):
        cfg = get_settings()
        broker = KisPaperBroker(
            kis_client=client,
            account_no=self._account_no,
            account_product_code=self._product_code,
            logger=logger,
        )
        eq_path = Path(cfg.paper_session_state_path).parent / f"equity_tracker_{self._user_tag}.json"
        tracker = EquityTracker(eq_path, logger=logger)
        sid = (strategy_id or self._strategy_id or "").strip()
        rules = RiskRules(_paper_risk_limits_for_strategy(sid, cfg))
        kill = KillSwitch(rules=rules)
        strat = strategy_for_paper_id(sid)
        setattr(strat, "manual_override_enabled", bool(self._manual_override_enabled))
        return SchedulerJobs(
            strategy=strat,
            broker=broker,
            risk_rules=rules,
            kill_switch=kill,
            equity_tracker=tracker,
            logger=logger,
            manual_override_enabled=bool(self._manual_override_enabled),
        )

    def _build_intraday_jobs(self, client, *, state_store: IntradayPaperStateStore, strategy_id: str | None = None):
        cfg = get_settings()
        broker = KisPaperBroker(
            kis_client=client,
            account_no=self._account_no,
            account_product_code=self._product_code,
            logger=logger,
        )
        eq_path = Path(cfg.paper_session_state_path).parent / f"equity_tracker_{self._user_tag}.json"
        tracker = EquityTracker(eq_path, logger=logger)
        sid = (strategy_id or self._strategy_id or "").strip()
        rules = RiskRules(_paper_risk_limits_for_strategy(sid, cfg))
        kill = KillSwitch(rules=rules)
        strat = strategy_for_paper_id(sid)
        setattr(strat, "manual_override_enabled", bool(self._manual_override_enabled))
        return IntradaySchedulerJobs(
            strategy=strat,
            broker=broker,
            risk_rules=rules,
            kill_switch=kill,
            equity_tracker=tracker,
            state_store=state_store,
            logger=logger,
            manual_override_enabled=bool(self._manual_override_enabled),
        )

    def _build_final_betting_jobs(self, client, *, state_store: IntradayPaperStateStore, strategy_id: str | None = None):
        cfg = get_settings()
        broker = KisPaperBroker(
            kis_client=client,
            account_no=self._account_no,
            account_product_code=self._product_code,
            logger=logger,
        )
        eq_path = Path(cfg.paper_session_state_path).parent / f"equity_tracker_{self._user_tag}.json"
        tracker = EquityTracker(eq_path, logger=logger)
        sid = (strategy_id or self._strategy_id or "").strip()
        rules = RiskRules(_paper_risk_limits_for_strategy(sid, cfg))
        kill = KillSwitch(rules=rules)
        strat = strategy_for_paper_id(sid)
        setattr(strat, "manual_override_enabled", bool(self._manual_override_enabled))
        return FinalBettingIntradayJobs(
            strategy=strat,
            broker=broker,
            risk_rules=rules,
            kill_switch=kill,
            equity_tracker=tracker,
            state_store=state_store,
            logger=logger,
            manual_override_enabled=bool(self._manual_override_enabled),
        )

    def _build_us_daily_jobs(self, client, *, strategy_id: str | None = None):
        cfg = get_settings()
        broker = KisUsPaperBroker(
            kis_client=client,
            account_no=self._account_no,
            account_product_code=self._product_code,
            logger=logger,
        )
        eq_path = Path(cfg.paper_session_state_path).parent / f"equity_tracker_us_{self._user_tag}.json"
        tracker = EquityTracker(eq_path, logger=logger)
        sid = (strategy_id or self._strategy_id or "").strip()
        rules = RiskRules(_paper_risk_limits_for_strategy(sid, cfg))
        kill = KillSwitch(rules=rules)
        strat = strategy_for_paper_id(sid)
        setattr(strat, "manual_override_enabled", bool(self._manual_override_enabled))
        return SchedulerJobs(
            strategy=strat,
            broker=broker,
            risk_rules=rules,
            kill_switch=kill,
            equity_tracker=tracker,
            logger=logger,
            manual_override_enabled=bool(self._manual_override_enabled),
        )

    def _build_us_intraday_jobs(self, client, *, state_store: IntradayPaperStateStore, strategy_id: str | None = None):
        cfg = get_settings()
        broker = KisUsPaperBroker(
            kis_client=client,
            account_no=self._account_no,
            account_product_code=self._product_code,
            logger=logger,
        )
        eq_path = Path(cfg.paper_session_state_path).parent / f"equity_tracker_us_{self._user_tag}.json"
        tracker = EquityTracker(eq_path, logger=logger)
        sid = (strategy_id or self._strategy_id or "").strip()
        rules = RiskRules(_paper_risk_limits_for_strategy(sid, cfg))
        kill = KillSwitch(rules=rules)
        strat = strategy_for_paper_id(sid)
        setattr(strat, "manual_override_enabled", bool(self._manual_override_enabled))
        return IntradaySchedulerJobs(
            strategy=strat,
            broker=broker,
            risk_rules=rules,
            kill_switch=kill,
            equity_tracker=tracker,
            state_store=state_store,
            logger=logger,
            manual_override_enabled=bool(self._manual_override_enabled),
        )

    def set_manual_override(self, enabled: bool) -> None:
        self._manual_override_enabled = bool(enabled)

    def _run_swing_daily_tick(self, client, swing_symbols: list[str], *, swing_strategy_id: str) -> dict[str, Any]:
        """멀티 모드 스윙 레그: 일봉 유니버스 + run_daily_cycle."""
        cfg = get_settings()
        sym = [s.strip() for s in swing_symbols if s and str(s).strip()]
        if not sym:
            return {
                "generated_order_count": 0,
                "accepted_orders": 0,
                "rejected_orders": 0,
                "no_order_reason": "multi_no_swing_symbols",
            }
        if cfg.paper_smoke_mode:
            sym = sym[:1]
        lookback = min(60, int(cfg.paper_kis_chart_lookback_days)) if cfg.paper_smoke_mode else max(int(cfg.paper_kis_chart_lookback_days), 60)
        jobs = self._build_jobs(client, strategy_id=swing_strategy_id)
        universe = build_kis_stock_universe(
            client,
            sym,
            lookback_calendar_days=lookback,
            logger=logger,
        )
        kospi = build_kospi_index_series(
            client,
            lookback_calendar_days=lookback,
            logger=logger,
        )
        sp500 = build_mock_sp500_proxy_from_kospi(kospi)
        return dict(jobs.run_daily_cycle(universe=universe, kospi_index=kospi, sp500_index=sp500))

    def _run_multi_strategy_tick(self) -> dict[str, Any]:
        """스윙(일봉) + 선택된 스캘프(분봉) 순차 1틱. 단일 브로커·동일 현금 풀."""
        failed_step = "kis_client"
        try:
            client = self._kis_client()
        except RuntimeError as exc:
            err_s = str(exc)
            is_rl = err_s.startswith("TOKEN_RATE_LIMIT:") or "TOKEN_RATE_LIMIT" in err_s
            fk = "token_rate_limit" if is_rl else "token_failure"
            return {
                "ok": False,
                "error": err_s,
                "failed_step": "kis_token",
                "kis_context": {},
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": fk,
                "token_error_code": "TOKEN_RATE_LIMIT" if is_rl else (self._last_token_error_code or "TOKEN_FAILURE"),
                "paper_loop_fresh_issue": False,
                "paper_loop_last_token_failure_at": self._last_token_failure_at_iso,
                "paper_loop_last_token_http_status": self._last_token_http_status,
            }

        cfg = get_settings()
        route = route_swing_vs_scalp_symbols(
            swing_csv=cfg.paper_trading_symbols,
            intraday_symbols=cfg.resolved_intraday_symbol_list(),
            prefer_scalp_on_overlap=cfg.paper_multi_router_prefer_scalp_on_overlap,
        )
        swing_sid = (cfg.paper_multi_swing_strategy_id or "swing_relaxed_v2").strip()
        br = KisPaperBroker(
            kis_client=client,
            account_no=self._account_no,
            account_product_code=self._product_code,
            logger=logger,
        )
        cash = float(br.get_cash())
        mv = sum(float(p.quantity) * float(p.average_price or 0.0) for p in br.get_positions())
        equity = cash + mv
        legs = notionals_for_legs(
            equity_krw=equity,
            cash_krw=cash,
            swing_pct=float(cfg.paper_swing_capital_pct),
            intraday_pct=float(cfg.paper_intraday_capital_pct),
        )
        rep_swing = self._run_swing_daily_tick(client, route.swing_symbols, swing_strategy_id=swing_sid)
        if not route.scalp_symbols:
            merged = dict(rep_swing)
            merged.setdefault("minute_bars_present", False)
            merged.setdefault("intraday_universe_row_count", 0)
            merged.setdefault("intraday_universe_symbol_count", 0)
            merged.setdefault("trade_count_today", merged.get("trade_count_today", 0))
            merged.setdefault("risk_halt_new_entries", merged.get("risk_halt_new_entries", False))
            merged["multi_strategy_snapshot"] = {
                "enabled": True,
                "swing_strategy_id": swing_sid,
                "scalp_strategy_id": self._strategy_id,
                "swing_symbols": route.swing_symbols,
                "scalp_symbols": [],
                "router_diagnostics": route.diagnostics,
                "notionals": legs,
                "swing_leg": rep_swing,
                "intraday_leg": None,
            }
            merged["paper_intraday_mode"] = True
            return {
                "ok": True,
                "report": merged,
                "token_source": self.token_source_for_diagnostics(),
                "token_cache_source": self.token_source_for_diagnostics(),
                "token_error_code": None,
                "paper_loop_fresh_issue": self._token_issued_locally,
                "paper_loop_last_token_failure_at": self._last_token_failure_at_iso,
                "paper_loop_last_token_error_code": self._last_token_error_code,
                "paper_loop_last_token_http_status": self._last_token_http_status,
                "universe_cache_hit": False,
                "kospi_cache_hit": False,
                "request_budget_mode": "paper_multi",
                "throttled_mode": int(cfg.kis_min_request_interval_ms) > 0,
                "paper_tick_interval_sec": int(cfg.paper_intraday_loop_interval_sec),
                "paper_intraday_mode": True,
            }

        intra_out = self._run_intraday_scalp_tick(
            client_override=client,
            symbols_override=list(route.scalp_symbols),
            router_equity_krw=equity,
            router_intraday_budget_krw=float(legs["intraday_notional_krw"]),
        )
        if not intra_out.get("ok"):
            return intra_out
        rep_i = dict(intra_out.get("report") or {})
        rep_s = dict(rep_swing)
        merged = dict(rep_i)
        merged["accepted_orders"] = int(rep_s.get("accepted_orders", 0) or 0) + int(rep_i.get("accepted_orders", 0) or 0)
        merged["rejected_orders"] = int(rep_s.get("rejected_orders", 0) or 0) + int(rep_i.get("rejected_orders", 0) or 0)
        merged["generated_order_count"] = int(rep_s.get("generated_order_count", 0) or 0) + int(
            rep_i.get("generated_order_count", 0) or 0
        )
        merged["multi_strategy_snapshot"] = {
            "enabled": True,
            "swing_strategy_id": swing_sid,
            "scalp_strategy_id": self._strategy_id,
            "swing_symbols": route.swing_symbols,
            "scalp_symbols": route.scalp_symbols,
            "router_diagnostics": route.diagnostics,
            "notionals": legs,
            "swing_leg": rep_swing,
            "intraday_leg": rep_i,
        }
        merged["no_order_reason"] = (
            f"멀티: 스윙 {rep_s.get('no_order_reason') or ''} | 단타 {rep_i.get('no_order_reason') or ''}".strip()
        )[:500]

        out = dict(intra_out)
        out["report"] = merged
        out["request_budget_mode"] = "paper_multi"
        return out

    def _run_close_betting_tick(self) -> dict[str, Any]:
        """종가베팅(T+1) — 분봉 파이프라인은 재사용하되 장마감 scalp 강제청산(forced_flatten) 비사용."""
        failed_step = "kis_client"
        try:
            try:
                client = self._kis_client()
            except RuntimeError as exc:
                err_s = str(exc)
                is_rl = err_s.startswith("TOKEN_RATE_LIMIT:") or "TOKEN_RATE_LIMIT" in err_s
                fk = "token_rate_limit" if is_rl else "token_failure"
                return {
                    "ok": False,
                    "error": err_s,
                    "failed_step": "kis_token",
                    "kis_context": {},
                    "token_source": self.token_source_for_diagnostics(),
                    "failure_kind": fk,
                    "token_error_code": "TOKEN_RATE_LIMIT" if is_rl else (self._last_token_error_code or "TOKEN_FAILURE"),
                    "paper_loop_fresh_issue": False,
                    "paper_loop_last_token_failure_at": self._last_token_failure_at_iso,
                    "paper_loop_last_token_http_status": self._last_token_http_status,
                }

            cfg = get_settings()
            symbols = cfg.resolved_final_betting_symbol_list()
            if not symbols:
                return {
                    "ok": False,
                    "error": "final_betting: PAPER_TRADING_SYMBOLS 가 비어 있습니다.",
                    "failed_step": "config",
                    "kis_context": {},
                    "token_source": self.token_source_for_diagnostics(),
                    "failure_kind": "config",
                }
            if cfg.paper_smoke_mode:
                symbols = symbols[:1]

            state_path = Path(cfg.paper_session_state_path).parent / f"paper_final_betting_state_{self._user_tag}.json"
            state_store = IntradayPaperStateStore(state_path, logger=logger)
            chart_cache = IntradayChartCache(
                ttl_sec=float(cfg.paper_intraday_chart_cache_ttl_sec),
                min_interval_sec=float(cfg.paper_intraday_chart_min_interval_sec),
            )

            failed_step = "intraday_universe"
            scfg = krx_session_config_from_settings(cfg)
            session_snap = analyze_krx_intraday_session(session_config=scfg)
            universe_1m, intraday_bar_fetch_summary = build_intraday_universe_1m(
                client,
                symbols,
                target_bars_per_symbol=140,
                logger=logger,
                cache=chart_cache,
                intraday_fetch_allowed=session_snap.fetch_allowed,
                intraday_fetch_block_reason=session_snap.fetch_block_reason,
                session_state=session_snap.state,
                order_allowed=session_snap.order_allowed,
            )
            intraday_universe_row_count = int(len(universe_1m))
            intraday_universe_symbol_count = (
                int(universe_1m["symbol"].nunique()) if not universe_1m.empty and "symbol" in universe_1m.columns else 0
            )
            paper_trading_symbols_resolved = list(symbols)
            regular_session_kst = session_snap.regular_session_kst
            universe_tf = universe_1m
            timeframe = "1m"

            failed_step = "kospi_series"
            now_m = time.monotonic()
            ttl_u = int(cfg.paper_kis_kospi_cache_ttl_sec)
            lookback = max(int(cfg.paper_kis_chart_lookback_days), 60)
            univ_key = f"kospi|{lookback}"
            kospi_cache_hit = False
            if (
                ttl_u > 0
                and self._kospi_df is not None
                and self._kospi_sig == univ_key
                and (now_m - self._kospi_ts) < float(ttl_u)
            ):
                kospi = self._kospi_df
                kospi_cache_hit = True
            else:
                kospi = build_kospi_index_series(
                    client,
                    lookback_calendar_days=lookback,
                    logger=logger,
                )
                self._kospi_sig = univ_key
                self._kospi_ts = time.monotonic()
                self._kospi_df = kospi

            sp500 = build_mock_sp500_proxy_from_kospi(kospi)

            failed_step = "intraday_quotes"
            quote_by_symbol = fetch_quotes_throttled(
                client,
                symbols,
                min_interval_sec=max(0.15, float(cfg.paper_intraday_chart_min_interval_sec)),
                logger=logger,
            )

            failed_step = "intraday_jobs"
            jobs = self._build_final_betting_jobs(client, state_store=state_store, strategy_id=self._strategy_id)
            cash_b = float(jobs.broker.get_cash())
            mv_b = sum(float(p.quantity) * float(p.average_price or 0.0) for p in jobs.broker.get_positions())
            eq_b = cash_b + mv_b
            setattr(jobs.strategy, "_final_betting_equity_krw", float(eq_b))

            report = jobs.run_intraday_cycle(
                universe_tf=universe_tf,
                kospi_index=kospi,
                sp500_index=sp500,
                timeframe=timeframe,
                quote_by_symbol=quote_by_symbol,
                forced_flatten=False,
                paper_trading_symbols_resolved=paper_trading_symbols_resolved,
                intraday_bar_fetch_summary=intraday_bar_fetch_summary,
                intraday_universe_row_count=intraday_universe_row_count,
                regular_session_kst=regular_session_kst,
                intraday_session_snapshot=session_snap,
            )
            report = dict(report)
            report["paper_trading_symbols_resolved"] = paper_trading_symbols_resolved
            report["intraday_symbols_source"] = "PAPER_TRADING_SYMBOLS(final_betting)"
            report["intraday_universe_symbol_count"] = intraday_universe_symbol_count
            report["intraday_universe_row_count"] = intraday_universe_row_count
            report["intraday_bar_fetch_summary"] = intraday_bar_fetch_summary
            report["forced_flatten"] = False
            report["flatten_before_close_armed"] = False
            report["strategy_profile"] = "final_betting_v1"
            report["close_betting_forced_flatten"] = False

            return {
                "ok": True,
                "report": report,
                "token_source": self.token_source_for_diagnostics(),
                "token_cache_source": self.token_source_for_diagnostics(),
                "token_error_code": None,
                "paper_loop_fresh_issue": self._token_issued_locally,
                "paper_loop_last_token_failure_at": self._last_token_failure_at_iso,
                "paper_loop_last_token_error_code": self._last_token_error_code,
                "paper_loop_last_token_http_status": self._last_token_http_status,
                "universe_cache_hit": False,
                "kospi_cache_hit": kospi_cache_hit,
                "request_budget_mode": "paper_close_betting",
                "throttled_mode": int(cfg.kis_min_request_interval_ms) > 0,
                "paper_tick_interval_sec": int(cfg.paper_final_betting_loop_interval_sec),
                "paper_intraday_mode": True,
            }
        except KISClientError as exc:
            ctx = getattr(exc, "kis_context", {}) or {}
            if ctx.get("rate_limit"):
                fk = "rate_limit"
            elif "business error" in str(exc).lower():
                fk = "kis_business_error"
            else:
                fk = "kis_client_error"
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": ctx,
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": fk,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": {},
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": type(exc).__name__,
            }

    def _run_intraday_scalp_tick(
        self,
        *,
        client_override: Any = None,
        symbols_override: list[str] | None = None,
        router_equity_krw: float | None = None,
        router_intraday_budget_krw: float | None = None,
    ) -> dict[str, Any]:
        """분봉 단타 전용 — 일봉 유니버스와 분리."""
        failed_step = "kis_client"
        try:
            try:
                client = client_override if client_override is not None else self._kis_client()
            except RuntimeError as exc:
                err_s = str(exc)
                is_rl = err_s.startswith("TOKEN_RATE_LIMIT:") or "TOKEN_RATE_LIMIT" in err_s
                fk = "token_rate_limit" if is_rl else "token_failure"
                return {
                    "ok": False,
                    "error": err_s,
                    "failed_step": "kis_token",
                    "kis_context": {},
                    "token_source": self.token_source_for_diagnostics(),
                    "failure_kind": fk,
                    "token_error_code": "TOKEN_RATE_LIMIT" if is_rl else (self._last_token_error_code or "TOKEN_FAILURE"),
                    "paper_loop_fresh_issue": False,
                    "paper_loop_last_token_failure_at": self._last_token_failure_at_iso,
                    "paper_loop_last_token_http_status": self._last_token_http_status,
                }

            cfg = get_settings()
            symbols = list(symbols_override) if symbols_override is not None else cfg.resolved_intraday_symbol_list()
            if not symbols:
                return {
                    "ok": False,
                    "error": "인트라데이 조회 종목이 비어 있음 (PAPER_INTRADAY_SYMBOLS / 인트라데이 fallback)",
                    "failed_step": "config",
                    "kis_context": {},
                    "token_source": self.token_source_for_diagnostics(),
                    "failure_kind": "config",
                }
            if cfg.paper_smoke_mode:
                symbols = symbols[:1]

            state_path = Path(cfg.paper_session_state_path).parent / f"paper_intraday_state_{self._user_tag}.json"
            state_store = IntradayPaperStateStore(state_path, logger=logger)
            chart_cache = IntradayChartCache(
                ttl_sec=float(cfg.paper_intraday_chart_cache_ttl_sec),
                min_interval_sec=float(cfg.paper_intraday_chart_min_interval_sec),
            )

            failed_step = "intraday_universe"
            scfg = krx_session_config_from_settings(cfg)
            session_snap = analyze_krx_intraday_session(session_config=scfg)
            universe_1m, intraday_bar_fetch_summary = build_intraday_universe_1m(
                client,
                symbols,
                target_bars_per_symbol=140,
                logger=logger,
                cache=chart_cache,
                intraday_fetch_allowed=session_snap.fetch_allowed,
                intraday_fetch_block_reason=session_snap.fetch_block_reason,
                session_state=session_snap.state,
                order_allowed=session_snap.order_allowed,
            )
            intraday_universe_row_count = int(len(universe_1m))
            intraday_universe_symbol_count = (
                int(universe_1m["symbol"].nunique()) if not universe_1m.empty and "symbol" in universe_1m.columns else 0
            )
            paper_trading_symbols_resolved = list(symbols)
            regular_session_kst = session_snap.regular_session_kst

            sid = (self._strategy_id or "").lower().strip()
            if sid in ("scalp_momentum_v1", "scalp_macd_rsi_3m_v1", "scalp_rsi_flag_hf_v1"):
                universe_tf = universe_as_timeframe(universe_1m, 3)
                timeframe = "3m"
            else:
                universe_tf = universe_1m
                timeframe = "1m"

            failed_step = "kospi_series"
            now_m = time.monotonic()
            ttl_u = int(cfg.paper_kis_kospi_cache_ttl_sec)
            lookback = max(int(cfg.paper_kis_chart_lookback_days), 60)
            univ_key = f"kospi|{lookback}"
            kospi_cache_hit = False
            if (
                ttl_u > 0
                and self._kospi_df is not None
                and self._kospi_sig == univ_key
                and (now_m - self._kospi_ts) < float(ttl_u)
            ):
                kospi = self._kospi_df
                kospi_cache_hit = True
            else:
                kospi = build_kospi_index_series(
                    client,
                    lookback_calendar_days=lookback,
                    logger=logger,
                )
                self._kospi_sig = univ_key
                self._kospi_ts = time.monotonic()
                self._kospi_df = kospi

            sp500 = build_mock_sp500_proxy_from_kospi(kospi)

            failed_step = "intraday_quotes"
            quote_by_symbol = fetch_quotes_throttled(
                client,
                symbols,
                min_interval_sec=max(0.15, float(cfg.paper_intraday_chart_min_interval_sec)),
                logger=logger,
            )
            forced_flatten = infer_forced_flatten(cfg)

            failed_step = "intraday_jobs"
            jobs = self._build_intraday_jobs(client, state_store=state_store, strategy_id=self._strategy_id)
            sid_run = (self._strategy_id or "").lower().strip()
            exp_pct = float(cfg.paper_experimental_scalp_capital_pct) / 100.0
            if cfg.paper_experimental_scalp_enabled and sid_run in ("scalp_momentum_v2", "scalp_momentum_v3"):
                setattr(jobs.strategy, "_experimental_capital_scale", max(0.0, min(1.0, exp_pct)))
            else:
                setattr(jobs.strategy, "_experimental_capital_scale", 1.0)
            if cfg.paper_uses_intraday_risk_sized_quantity:
                eq_b = router_equity_krw
                bud = router_intraday_budget_krw
                if eq_b is None or bud is None:
                    cash_b = float(jobs.broker.get_cash())
                    mv_b = sum(
                        float(p.quantity) * float(p.average_price or 0.0) for p in jobs.broker.get_positions()
                    )
                    eq_b = cash_b + mv_b
                    legs_b = notionals_for_legs(
                        equity_krw=eq_b,
                        cash_krw=cash_b,
                        swing_pct=float(cfg.paper_swing_capital_pct),
                        intraday_pct=float(cfg.paper_intraday_capital_pct),
                    )
                    bud = float(legs_b["intraday_notional_krw"])
                setattr(jobs.strategy, "_router_equity_krw", float(eq_b))
                setattr(jobs.strategy, "_router_intraday_budget_krw", float(bud))
            report = jobs.run_intraday_cycle(
                universe_tf=universe_tf,
                kospi_index=kospi,
                sp500_index=sp500,
                timeframe=timeframe,
                quote_by_symbol=quote_by_symbol,
                forced_flatten=forced_flatten,
                paper_trading_symbols_resolved=paper_trading_symbols_resolved,
                intraday_bar_fetch_summary=intraday_bar_fetch_summary,
                intraday_universe_row_count=intraday_universe_row_count,
                regular_session_kst=regular_session_kst,
                intraday_session_snapshot=session_snap,
            )
            report = dict(report)
            report["paper_trading_symbols_resolved"] = paper_trading_symbols_resolved
            report["intraday_symbols_source"] = (
                "PAPER_INTRADAY_SYMBOLS"
                if (cfg.paper_intraday_symbols or "").strip()
                else "INTRADAY_FALLBACK"
            )
            report["intraday_universe_symbol_count"] = intraday_universe_symbol_count
            report["intraday_universe_row_count"] = intraday_universe_row_count
            report["intraday_bar_fetch_summary"] = intraday_bar_fetch_summary

            return {
                "ok": True,
                "report": report,
                "token_source": self.token_source_for_diagnostics(),
                "token_cache_source": self.token_source_for_diagnostics(),
                "token_error_code": None,
                "paper_loop_fresh_issue": self._token_issued_locally,
                "paper_loop_last_token_failure_at": self._last_token_failure_at_iso,
                "paper_loop_last_token_error_code": self._last_token_error_code,
                "paper_loop_last_token_http_status": self._last_token_http_status,
                "universe_cache_hit": False,
                "kospi_cache_hit": kospi_cache_hit,
                "request_budget_mode": "paper_intraday",
                "throttled_mode": int(cfg.kis_min_request_interval_ms) > 0,
                "paper_tick_interval_sec": int(cfg.paper_intraday_loop_interval_sec),
                "paper_intraday_mode": True,
            }
        except KISClientError as exc:
            ctx = getattr(exc, "kis_context", {}) or {}
            if ctx.get("rate_limit"):
                fk = "rate_limit"
            elif "business error" in str(exc).lower():
                fk = "kis_business_error"
            else:
                fk = "kis_client_error"
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": ctx,
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": fk,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": {},
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": type(exc).__name__,
            }

    def run_intraday_tick(self) -> dict[str, Any]:
        if self._paper_market in ("us", "usa"):
            return self._run_us_equity_tick()
        cfg = get_settings()
        if (
            bool(cfg.paper_multi_strategy_mode)
            and bool(cfg.paper_intraday_enabled)
            and _is_intraday_scalp_strategy(self._strategy_id)
        ):
            return self._run_multi_strategy_tick()
        if _is_final_betting_strategy(self._strategy_id):
            if not bool(paper_final_betting_enabled_fresh()):
                return {
                    "ok": False,
                    "error": "final_betting_v1 은 PAPER_FINAL_BETTING_ENABLED=true 일 때만 실행됩니다.",
                    "failed_step": "config",
                    "kis_context": {},
                    "token_source": self.token_source_for_diagnostics(),
                    "failure_kind": "config",
                }
            return self._run_close_betting_tick()
        if _is_intraday_scalp_strategy(self._strategy_id):
            if not bool(cfg.paper_intraday_enabled):
                return {
                    "ok": False,
                    "error": "scalp 전략은 PAPER_INTRADAY_ENABLED=true 일 때만 실행됩니다.",
                    "failed_step": "config",
                    "kis_context": {},
                    "token_source": self.token_source_for_diagnostics(),
                    "failure_kind": "config",
                }
            return self._run_intraday_scalp_tick()

        failed_step = "kis_client"
        try:
            try:
                client = self._kis_client()
            except RuntimeError as exc:
                err_s = str(exc)
                is_rl = err_s.startswith("TOKEN_RATE_LIMIT:") or "TOKEN_RATE_LIMIT" in err_s
                fk = "token_rate_limit" if is_rl else "token_failure"
                return {
                    "ok": False,
                    "error": err_s,
                    "failed_step": "kis_token",
                    "kis_context": {},
                    "token_source": self.token_source_for_diagnostics(),
                    "failure_kind": fk,
                    "token_error_code": "TOKEN_RATE_LIMIT" if is_rl else (self._last_token_error_code or "TOKEN_FAILURE"),
                    "paper_loop_fresh_issue": False,
                    "paper_loop_last_token_failure_at": self._last_token_failure_at_iso,
                    "paper_loop_last_token_http_status": self._last_token_http_status,
                }

            failed_step = "build_jobs"
            jobs = self._build_jobs(client)
            cfg = get_settings()
            symbols = [s.strip() for s in cfg.paper_trading_symbols.split(",") if s.strip()]
            if not symbols:
                return {
                    "ok": False,
                    "error": "paper_trading_symbols 비어 있음 (app 설정)",
                    "failed_step": "config",
                    "kis_context": {},
                    "token_source": self.token_source_for_diagnostics(),
                    "failure_kind": "config",
                }
            if cfg.paper_smoke_mode:
                symbols = symbols[:1]
                lookback = min(60, int(cfg.paper_kis_chart_lookback_days))
            else:
                lookback = max(int(cfg.paper_kis_chart_lookback_days), 60)

            now_m = time.monotonic()
            ttl_u = int(cfg.paper_kis_universe_cache_ttl_sec)
            univ_key = f"{','.join(symbols)}|{lookback}"
            failed_step = "kis_universe"
            universe_cache_hit = False
            if (
                ttl_u > 0
                and self._univ_df is not None
                and self._univ_sig == univ_key
                and (now_m - self._univ_ts) < float(ttl_u)
            ):
                universe = self._univ_df
                universe_cache_hit = True
            else:
                universe = build_kis_stock_universe(
                    client,
                    symbols,
                    lookback_calendar_days=lookback,
                    logger=logger,
                )
                self._univ_sig = univ_key
                self._univ_ts = time.monotonic()
                self._univ_df = universe

            failed_step = "kospi_series"
            ttl_k = int(cfg.paper_kis_kospi_cache_ttl_sec)
            kospi_key = str(lookback)
            kospi_cache_hit = False
            if (
                ttl_k > 0
                and self._kospi_df is not None
                and self._kospi_sig == kospi_key
                and (now_m - self._kospi_ts) < float(ttl_k)
            ):
                kospi = self._kospi_df
                kospi_cache_hit = True
            else:
                kospi = build_kospi_index_series(
                    client,
                    lookback_calendar_days=lookback,
                    logger=logger,
                )
                self._kospi_sig = kospi_key
                self._kospi_ts = time.monotonic()
                self._kospi_df = kospi
            failed_step = "daily_cycle"
            sp500 = build_mock_sp500_proxy_from_kospi(kospi)
            report = jobs.run_daily_cycle(universe=universe, kospi_index=kospi, sp500_index=sp500)

            if self._backend.screener_auto_refresh_with_runtime:
                try:
                    from backend.app.strategy.screener import get_screener_engine

                    snap = get_screener_engine().refresh()
                    report = dict(report)
                    report["screener"] = {
                        "regime": snap.regime,
                        "blocked": snap.blocked,
                        "candidate_count": len(snap.candidates),
                        "updated_at_utc": snap.updated_at_utc,
                    }
                except Exception as exc:
                    logger.warning("screener refresh failed: %s", exc)

            return {
                "ok": True,
                "report": report,
                "token_source": self.token_source_for_diagnostics(),
                "token_cache_source": self.token_source_for_diagnostics(),
                "token_error_code": None,
                "paper_loop_fresh_issue": self._token_issued_locally,
                "paper_loop_last_token_failure_at": self._last_token_failure_at_iso,
                "paper_loop_last_token_error_code": self._last_token_error_code,
                "paper_loop_last_token_http_status": self._last_token_http_status,
                "universe_cache_hit": universe_cache_hit,
                "kospi_cache_hit": kospi_cache_hit,
                "request_budget_mode": "paper_conserve",
                "throttled_mode": int(cfg.kis_min_request_interval_ms) > 0,
                "paper_tick_interval_sec": int(cfg.paper_trading_interval_sec),
                "paper_intraday_mode": False,
            }
        except KISClientError as exc:
            ctx = getattr(exc, "kis_context", {}) or {}
            if ctx.get("rate_limit"):
                fk = "rate_limit"
            elif "business error" in str(exc).lower():
                fk = "kis_business_error"
            else:
                fk = "kis_client_error"
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": ctx,
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": fk,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": {},
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": type(exc).__name__,
            }

    def _us_token_error_out(self, err_s: str) -> dict[str, Any]:
        is_rl = err_s.startswith("TOKEN_RATE_LIMIT:") or "TOKEN_RATE_LIMIT" in err_s
        fk = "token_rate_limit" if is_rl else "token_failure"
        return {
            "ok": False,
            "error": err_s,
            "failed_step": "kis_token",
            "kis_context": {},
            "token_source": self.token_source_for_diagnostics(),
            "failure_kind": fk,
            "token_error_code": "TOKEN_RATE_LIMIT" if is_rl else (self._last_token_error_code or "TOKEN_FAILURE"),
            "paper_loop_fresh_issue": False,
            "paper_loop_last_token_failure_at": self._last_token_failure_at_iso,
            "paper_loop_last_token_http_status": self._last_token_http_status,
        }

    def _run_us_equity_tick(self) -> dict[str, Any]:
        if _is_us_scalp_strategy(self._strategy_id):
            return self._run_us_scalp_intraday_tick()
        if _is_us_swing_strategy(self._strategy_id):
            return self._run_us_swing_daily_tick()
        return self._run_us_equity_probe_tick()

    def _run_us_equity_probe_tick(self) -> dict[str, Any]:
        """미국 Paper(알 수 없는 전략): 시세·분봉·세션 조회만 — 주문 루프 없음."""
        from backend.app.market.us_exchange_map import excd_for_price_chart
        from backend.app.services.us_symbol_search_service import search_us_symbols_via_kis

        failed_step = "kis_client"
        try:
            try:
                client = self._kis_client()
            except RuntimeError as exc:
                return self._us_token_error_out(str(exc))

            session_snap = analyze_us_equity_session()
            cfg = get_settings()
            symbols = [s.strip().upper() for s in (cfg.paper_us_symbols or "NVDA").split(",") if s.strip()][:5]
            if cfg.paper_smoke_mode:
                symbols = symbols[:1]

            quotes: dict[str, Any] = {}
            bars_summary: list[dict[str, Any]] = []
            failed_step = "us_quote"
            for i, sym in enumerate(symbols):
                hits = search_us_symbols_via_kis(client, sym, limit=1)
                if not hits:
                    quotes[sym] = None
                    continue
                excd = str(hits[0].get("excd") or "NAS")
                try:
                    quotes[sym] = client.get_overseas_price_quotation(excd=excd, symb=sym, auth="").get("output")
                except KISClientError as exc:
                    quotes[sym] = {"error": str(exc)}

                if i == 0:
                    failed_step = "us_minute_bars"
                    ov = str(hits[0].get("ovrs_excg_cd") or "NASD")
                    ex2 = excd_for_price_chart(ov)
                    try:
                        raw = client.get_overseas_time_itemchartprice(
                            auth="",
                            excd=ex2,
                            symb=sym,
                            nmin="1",
                            pinc="1",
                            next_flag="",
                            nrec="30",
                            fill="",
                            keyb="",
                        )
                        o1 = raw.get("output1")
                        n = len(o1) if isinstance(o1, list) else (1 if isinstance(o1, dict) else 0)
                        bars_summary.append({"symbol": sym, "excd": ex2, "bar_row_count": n})
                    except KISClientError as exc:
                        bars_summary.append({"symbol": sym, "error": str(exc)})

            broker = KisUsPaperBroker(
                kis_client=client,
                account_no=self._account_no,
                account_product_code=self._product_code,
                logger=logger,
            )
            cash_hint: float | None = None
            try:
                cash_hint = float(broker.get_cash())
            except Exception:
                cash_hint = None

            report: dict[str, Any] = {
                "market": "us",
                "us_session_state": session_snap.state,
                "fetch_allowed": session_snap.fetch_allowed,
                "fetch_block_reason": session_snap.fetch_block_reason,
                "order_allowed": session_snap.order_allowed,
                "order_block_reason": session_snap.order_block_reason,
                "us_local_time_et": session_snap.local_time_et_iso,
                "quotes": quotes,
                "minute_bar_summary": bars_summary,
                "cash_usd_hint": cash_hint,
                "accepted_orders": 0,
                "rejected_orders": 0,
                "generated_order_count": 0,
                "no_order_reason": (
                    "us_paper_quote_only_tick"
                    if session_snap.order_allowed
                    else (session_snap.order_block_reason or "us_orders_blocked")[:500]
                ),
                "krx_session_state": session_snap.state,
                "minute_bars_present": bool(bars_summary and not bars_summary[0].get("error")),
                "paper_trading_symbols_resolved": symbols,
                "intraday_symbols_source": "PAPER_US_SYMBOLS",
            }

            return {
                "ok": True,
                "report": report,
                "token_source": self.token_source_for_diagnostics(),
                "token_cache_source": self.token_source_for_diagnostics(),
                "token_error_code": None,
                "paper_loop_fresh_issue": self._token_issued_locally,
                "paper_loop_last_token_failure_at": self._last_token_failure_at_iso,
                "paper_loop_last_token_http_status": self._last_token_http_status,
                "universe_cache_hit": False,
                "kospi_cache_hit": False,
                "request_budget_mode": "paper_us",
                "throttled_mode": int(get_settings().kis_min_request_interval_ms) > 0,
                "paper_tick_interval_sec": int(get_settings().paper_trading_interval_sec),
                "paper_intraday_mode": False,
            }
        except KISClientError as exc:
            ctx = getattr(exc, "kis_context", {}) or {}
            fk = "rate_limit" if ctx.get("rate_limit") else "kis_client_error"
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": ctx,
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": fk,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": {},
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": type(exc).__name__,
            }

    def _run_us_scalp_intraday_tick(self) -> dict[str, Any]:
        """미국 Paper 단타 — 해외 분봉 + `IntradaySchedulerJobs` + `KisUsPaperBroker`."""
        from app.scheduler.kis_intraday import resample_minute_ohlc

        failed_step = "kis_client"
        try:
            try:
                client = self._kis_client()
            except RuntimeError as exc:
                return self._us_token_error_out(str(exc))

            cfg = get_settings()
            session_snap = analyze_us_equity_session()
            intraday_snap = us_equity_session_to_intraday_snapshot(session_snap)
            symbols = [s.strip().upper() for s in (cfg.paper_us_symbols or "NVDA").split(",") if s.strip()][:5]
            if cfg.paper_smoke_mode:
                symbols = symbols[:1]

            failed_step = "us_minute_universe"
            minute_df, bar_summary = fetch_us_minute_universe(client, symbols, nrec="120", nmin="1", logger_=logger)
            bar_m = max(1, min(int(cfg.paper_intraday_bar_minutes), 60))
            tf_df = resample_minute_ohlc(minute_df, bar_m) if not minute_df.empty else minute_df

            quote_by_symbol: dict[str, dict[str, Any]] = {}
            from backend.app.market.us_exchange_map import excd_for_price_chart
            from backend.app.services.us_symbol_search_service import search_us_symbols_via_kis

            for sym in symbols:
                hits = search_us_symbols_via_kis(client, sym, limit=1)
                if not hits:
                    quote_by_symbol[sym] = {}
                    continue
                excd = str(hits[0].get("excd") or "NAS")
                try:
                    quote_by_symbol[sym] = client.get_overseas_price_quotation(excd=excd, symb=sym, auth="").get(
                        "output"
                    ) or {}
                except KISClientError as exc:
                    quote_by_symbol[sym] = {"error": str(exc)}

            state_path = Path(cfg.paper_session_state_path).parent / f"paper_us_scalp_state_{self._user_tag}.json"
            state_store = IntradayPaperStateStore(state_path, logger=logger)

            failed_step = "us_intraday_cycle"
            kospi_df, sp500_df = minimal_macro_series()
            jobs = self._build_us_intraday_jobs(client, state_store=state_store)
            report = jobs.run_intraday_cycle(
                universe_tf=tf_df,
                kospi_index=kospi_df,
                sp500_index=sp500_df,
                timeframe=f"{bar_m}m",
                quote_by_symbol=quote_by_symbol,
                forced_flatten=False,
                paper_trading_symbols_resolved=list(symbols),
                intraday_bar_fetch_summary=bar_summary,
                intraday_universe_row_count=int(len(tf_df)),
                regular_session_kst=bool(intraday_snap.regular_session_kst),
                intraday_session_snapshot=intraday_snap,
            )
            report = dict(report)
            report["market"] = "us"
            report["us_session_state"] = session_snap.state
            report["strategy_profile"] = "us_scalp_momentum_v1"
            report["paper_trading_symbols_resolved"] = list(symbols)
            report["intraday_symbols_source"] = "PAPER_US_SYMBOLS(us_scalp)"

            return {
                "ok": True,
                "report": report,
                "token_source": self.token_source_for_diagnostics(),
                "token_cache_source": self.token_source_for_diagnostics(),
                "token_error_code": None,
                "paper_loop_fresh_issue": self._token_issued_locally,
                "paper_loop_last_token_failure_at": self._last_token_failure_at_iso,
                "paper_loop_last_token_http_status": self._last_token_http_status,
                "universe_cache_hit": False,
                "kospi_cache_hit": False,
                "request_budget_mode": "paper_us_scalp",
                "throttled_mode": int(cfg.kis_min_request_interval_ms) > 0,
                "paper_tick_interval_sec": int(cfg.paper_intraday_loop_interval_sec),
                "paper_intraday_mode": True,
            }
        except KISClientError as exc:
            ctx = getattr(exc, "kis_context", {}) or {}
            fk = "rate_limit" if ctx.get("rate_limit") else "kis_client_error"
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": ctx,
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": fk,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": {},
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": type(exc).__name__,
            }

    def _run_us_swing_daily_tick(self) -> dict[str, Any]:
        """미국 Paper 스윙 — 합성 일봉 유니버스 + `SchedulerJobs` + `KisUsPaperBroker`."""
        failed_step = "kis_client"
        try:
            try:
                client = self._kis_client()
            except RuntimeError as exc:
                return self._us_token_error_out(str(exc))

            cfg = get_settings()
            session_snap = analyze_us_equity_session()
            symbols = [s.strip().upper() for s in (cfg.paper_us_symbols or "NVDA").split(",") if s.strip()][:5]
            if cfg.paper_smoke_mode:
                symbols = symbols[:1]

            failed_step = "us_swing_universe"
            universe = build_us_swing_daily_universe(client, symbols)
            kospi_df, sp500_df = minimal_macro_series()

            failed_step = "us_daily_cycle"
            jobs = self._build_us_daily_jobs(client)
            report = jobs.run_daily_cycle(universe=universe, kospi_index=kospi_df, sp500_index=sp500_df)
            report = dict(report)
            report["market"] = "us"
            report["us_session_state"] = session_snap.state
            report["order_allowed"] = session_snap.order_allowed
            report["order_block_reason"] = session_snap.order_block_reason
            report["strategy_profile"] = "us_swing_relaxed_v1"
            report["paper_trading_symbols_resolved"] = list(symbols)

            return {
                "ok": True,
                "report": report,
                "token_source": self.token_source_for_diagnostics(),
                "token_cache_source": self.token_source_for_diagnostics(),
                "token_error_code": None,
                "paper_loop_fresh_issue": self._token_issued_locally,
                "paper_loop_last_token_failure_at": self._last_token_failure_at_iso,
                "paper_loop_last_token_http_status": self._last_token_http_status,
                "universe_cache_hit": False,
                "kospi_cache_hit": False,
                "request_budget_mode": "paper_us_swing",
                "throttled_mode": int(cfg.kis_min_request_interval_ms) > 0,
                "paper_tick_interval_sec": int(cfg.paper_trading_interval_sec),
                "paper_intraday_mode": False,
            }
        except KISClientError as exc:
            ctx = getattr(exc, "kis_context", {}) or {}
            fk = "rate_limit" if ctx.get("rate_limit") else "kis_client_error"
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": ctx,
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": fk,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "failed_step": failed_step,
                "kis_context": {},
                "token_source": self.token_source_for_diagnostics(),
                "failure_kind": type(exc).__name__,
            }

    def snapshot_positions(self) -> list[dict[str, Any]]:
        broker = self._paper_broker()
        return [
            {"symbol": p.symbol, "quantity": p.quantity, "average_price": p.average_price}
            for p in broker.get_positions()
        ]

    def _paper_broker(self) -> KisPaperBroker | KisUsPaperBroker:
        client = self._kis_client()
        if self._paper_market in ("us", "usa"):
            return KisUsPaperBroker(
                kis_client=client,
                account_no=self._account_no,
                account_product_code=self._product_code,
                logger=logger,
            )
        return KisPaperBroker(
            kis_client=client,
            account_no=self._account_no,
            account_product_code=self._product_code,
            logger=logger,
        )

    def fetch_open_orders_payload(self) -> dict[str, Any]:
        """KIS 모의 미체결(nccs). 실패 시 error 문자열, items 는 항상 리스트."""
        items: list[dict[str, Any]] = []
        err: str | None = None
        try:
            for o in self._paper_broker().get_open_orders():
                items.append(
                    {
                        "order_id": o.order_id,
                        "symbol": o.symbol,
                        "side": o.side,
                        "quantity": o.quantity,
                        "remaining_quantity": o.remaining_quantity,
                        "price": o.price,
                        "created_at": o.created_at.isoformat(),
                    }
                )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            logger.warning("fetch_open_orders_payload failed: %s", err)
        return {"items": items, "error": err}

    def fetch_recent_fills_payload(self, *, limit: int = 20) -> dict[str, Any]:
        """당일 체결(CCLD). 최신 순 최대 limit 건."""
        items: list[dict[str, Any]] = []
        err: str | None = None
        try:
            fills = self._paper_broker().get_fills()
            sorted_fills = sorted(
                fills,
                key=lambda f: f.filled_at.timestamp() if f.filled_at else 0.0,
                reverse=True,
            )
            for fl in sorted_fills[: max(0, limit)]:
                items.append(
                    {
                        "fill_id": fl.fill_id,
                        "order_id": fl.order_id,
                        "symbol": fl.symbol,
                        "side": fl.side,
                        "quantity": fl.quantity,
                        "price": fl.fill_price,
                        "filled_at": fl.filled_at.isoformat() if fl.filled_at else None,
                    }
                )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            logger.warning("fetch_recent_fills_payload failed: %s", err)
        return {"items": items, "error": err}
