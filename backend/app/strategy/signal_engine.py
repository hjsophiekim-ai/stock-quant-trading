"""
실시간 호가 + 일봉 병합 기반 스윙 신호 엔진.

- 종목별 상태 머신(분할 진입·부분 익절·트레일링)
- 중복 신호 억제(TTL)
- `StandardEngineSignal.to_order_signal()` → 리스크 `OrderManager` 연동
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from app.strategy.indicators import add_basic_indicators
from backend.app.strategy.signal_models import (
    LiveQuoteView,
    SignalEngineSnapshot,
    StandardEngineSignal,
    SwingSignalEngineConfig,
    SymbolSignalDiagnosis,
    SymbolStrategyPhase,
    SymbolStrategyState,
)

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")


def parse_live_quote_from_kis(symbol: str, payload: dict) -> LiveQuoteView | None:
    """KIS inquire-price 응답(output)에서 실시간 호가 추출."""
    out = payload.get("output")
    if not isinstance(out, dict):
        return None

    def _f(*keys: str) -> float | None:
        for k in keys:
            raw = out.get(k)
            if raw is None or raw == "":
                continue
            try:
                v = float(raw)
                if v > 0:
                    return v
            except (TypeError, ValueError):
                continue
        return None

    last = _f("stck_prpr", "prpr", "antc_cnpr")
    if last is None:
        return None
    open_ = _f("stck_oprc", "oprc", "antc_oprc")
    high = _f("stck_hgpr", "hgpr")
    low = _f("stck_lwpr", "lwpr")
    prev = _f("prdy_vrss_prpr", "prdy_cls_vrss_prpr")
    return LiveQuoteView(
        symbol=symbol,
        last=last,
        open=open_,
        high=high,
        low=low,
        prev_close=prev,
        raw_keys={k: out.get(k) for k in list(out.keys())[:12]},
    )


def merge_daily_with_live(symbol_df: pd.DataFrame, live: LiveQuoteView) -> pd.DataFrame:
    """당일 봉을 실시간 호가로 갱신하거나 새 행 추가."""
    df = symbol_df.sort_values("date").copy()
    if df.empty or live.last <= 0:
        return df
    today = pd.Timestamp.now(tz=_KST).normalize()
    last_ts = df["date"].iloc[-1]
    if isinstance(last_ts, pd.Timestamp):
        if last_ts.tzinfo is None:
            last_ts = last_ts.tz_localize(_KST)
        else:
            last_ts = last_ts.tz_convert(_KST)
    same_day = last_ts.normalize() == today
    last = df.iloc[-1]
    open_px = live.open if live.open and live.open > 0 else float(last["open"])
    high_px = max(float(last["high"]), live.last)
    if live.high and live.high > 0:
        high_px = max(high_px, live.high)
    low_px = min(float(last["low"]), live.last)
    if live.low and live.low > 0:
        low_px = min(low_px, live.low)
    sym = str(last["symbol"])
    if same_day:
        idx = df.index[-1]
        df.loc[idx, "close"] = live.last
        df.loc[idx, "open"] = open_px
        df.loc[idx, "high"] = high_px
        df.loc[idx, "low"] = low_px
        return df
    new_row = {
        "symbol": sym,
        "date": today,
        "open": open_px,
        "high": high_px,
        "low": low_px,
        "close": live.last,
        "volume": float(last["volume"]) if "volume" in last else 0.0,
    }
    return pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def _trailing_stop_triggered(
    *,
    close: float,
    atr: float,
    low_n: float,
    highest_price: float,
    mode: str,
    atr_multiplier: float,
) -> bool:
    if mode == "n_day_low":
        return close <= low_n
    if atr <= 0:
        return False
    trailing_stop = highest_price - (atr * atr_multiplier)
    return close <= trailing_stop


def _swing_high_before_last(merged: pd.DataFrame, lookback: int) -> float:
    if len(merged) < 2:
        return float(merged.iloc[-1]["high"])
    body = merged.iloc[-(lookback + 1) : -1]
    if body.empty:
        return float(merged.iloc[-2]["high"])
    return float(body["high"].max())


def _leg_quantities(cfg: SwingSignalEngineConfig) -> tuple[int, int]:
    q1 = max(int(cfg.order_quantity * 0.5), 1)
    q2 = max(cfg.order_quantity - q1, 1)
    return q1, q2


def _infer_legs_from_qty(qty: int, cfg: SwingSignalEngineConfig) -> int:
    if qty <= 0:
        return 0
    if qty >= cfg.order_quantity:
        return 2
    return 1


def _position_row(portfolio_df: pd.DataFrame, symbol: str) -> pd.Series | None:
    if portfolio_df.empty:
        return None
    m = portfolio_df[portfolio_df["symbol"] == symbol]
    if m.empty:
        return None
    return m.iloc[-1]


def evaluate_symbol(
    symbol: str,
    merged: pd.DataFrame,
    live: LiveQuoteView,
    *,
    cfg: SwingSignalEngineConfig,
    state: SymbolStrategyState,
    portfolio_df: pd.DataFrame,
    market_regime: str | None,
) -> tuple[list[StandardEngineSignal], SymbolSignalDiagnosis, SymbolStrategyState]:
    signals: list[StandardEngineSignal] = []
    narrative: list[str] = []
    checklist: dict[str, bool | float | str] = {}

    pos = _position_row(portfolio_df, symbol)
    qty = int(pos["quantity"]) if pos is not None else 0
    avg_price = float(pos["average_price"]) if pos is not None else 0.0
    hold_days = int(pos.get("hold_days", 0)) if pos is not None else 0
    broker_legs = _infer_legs_from_qty(qty, cfg)

    if qty <= 0:
        state = SymbolStrategyState(symbol=symbol)
    else:
        state.symbol = symbol
        if broker_legs >= 2:
            state.phase = SymbolStrategyPhase.HOLDING
            state.entry_legs_done = 2
        elif broker_legs == 1:
            state.phase = SymbolStrategyPhase.SCALE_IN
            state.entry_legs_done = max(state.entry_legs_done, 1)
        if state.highest_price_since_entry is None and avg_price > 0:
            state.highest_price_since_entry = max(avg_price, live.last)
        elif state.highest_price_since_entry is not None:
            state.highest_price_since_entry = max(state.highest_price_since_entry, live.last)

    if len(merged) < 65:
        narrative.append("데이터 65거래일 미만으로 지표·신호 생략")
        diag = SymbolSignalDiagnosis(
            symbol=symbol,
            phase=state.phase.value,
            would_enter=False,
            would_exit=False,
            checklist={"data_ok": False},
            narrative=narrative,
        )
        return signals, diag, state

    enriched = add_basic_indicators(merged)
    enriched["atr14"] = _atr(enriched, 14)
    enriched["low_n"] = enriched["low"].rolling(cfg.trailing_n_day_low_window, min_periods=1).min()
    cur = enriched.iloc[-1]

    ma20 = float(cur["ma20"]) if pd.notna(cur["ma20"]) else float("nan")
    ma60 = float(cur["ma60"]) if pd.notna(cur["ma60"]) else float("nan")
    rsi = float(cur["rsi14"]) if pd.notna(cur["rsi14"]) else 50.0
    ret_3d = float(cur["ret_3d_pct"]) if pd.notna(cur["ret_3d_pct"]) else 0.0
    close = float(cur["close"])
    atr14 = float(cur["atr14"]) if pd.notna(cur["atr14"]) else 0.0
    low_n = float(cur["low_n"]) if pd.notna(cur["low_n"]) else float(cur["low"])
    bullish_day = bool(live.open and live.open > 0 and live.last > live.open)

    ma_ok = bool(pd.notna(ma20) and pd.notna(ma60) and ma20 > ma60)
    ret_ok = bool(cfg.ret_3d_min <= ret_3d <= cfg.ret_3d_max)
    rsi_ok = bool(rsi < cfg.rsi_max)
    ref_high = _swing_high_before_last(merged, cfg.swing_high_lookback)
    dd_from_high_pct = ((close / ref_high) - 1.0) * 100.0 if ref_high > 0 else 0.0
    leg1_ok = bool(dd_from_high_pct <= cfg.first_leg_drawdown_pct)
    leg2_ok = bool(dd_from_high_pct <= cfg.second_leg_drawdown_pct)

    regime_s = str(market_regime or "") or "unknown"
    regime_blocks = regime_s in cfg.block_new_entries_regimes

    checklist = {
        "ma20_gt_ma60": ma_ok,
        "ret_3d_pct": round(ret_3d, 4),
        "ret_3d_in_band": ret_ok,
        "rsi": round(rsi, 4),
        "rsi_ok": rsi_ok,
        "bullish_day": bullish_day,
        "dd_from_high_pct": round(dd_from_high_pct, 4),
        "leg1_depth_ok": leg1_ok,
        "leg2_depth_ok": leg2_ok,
        "ref_high": round(ref_high, 4),
        "regime": regime_s,
        "regime_blocks_entry": regime_blocks,
        "position_qty": qty,
    }

    def explain_entry_gate() -> bool:
        ok = True
        if not ma_ok:
            ok = False
            narrative.append("추세: MA20≤MA60 → 신규 분할 진입 보류")
        else:
            narrative.append("추세: MA20>MA60 충족")
        if not ret_ok:
            ok = False
            narrative.append(f"3일수익률 {ret_3d:.2f}% 가 [-6,-3]% 밖 → 진입 보류")
        else:
            narrative.append(f"3일수익률 {ret_3d:.2f}% 구간 충족")
        if not rsi_ok:
            ok = False
            narrative.append(f"RSI {rsi:.1f} ≥ {cfg.rsi_max} → 진입 보류")
        else:
            narrative.append(f"RSI {rsi:.1f} < {cfg.rsi_max}")
        if not bullish_day:
            ok = False
            narrative.append("당일 양봉 전환 아님(종가≤시가) → 진입 보류")
        else:
            narrative.append("당일 양봉 전환 충족")
        if regime_blocks:
            ok = False
            narrative.append(f"국면 {regime_s}: 신규 진입 차단")
        return ok

    # ---------- 청산 (보유 시) ----------
    if qty > 0 and avg_price > 0:
        pnl_pct = ((close / avg_price) - 1.0) * 100.0
        narrative.append(f"보유 {qty}주, 평단 {avg_price:.2f}, 평가손익 {pnl_pct:.2f}%")
        checklist["pnl_pct"] = round(pnl_pct, 4)

        if pnl_pct <= -abs(cfg.stop_loss_pct):
            signals.append(
                StandardEngineSignal(
                    symbol=symbol,
                    side="sell",
                    quantity=qty,
                    limit_price=live.last,
                    stop_loss_pct=None,
                    strategy_id=cfg.strategy_id,
                    kind="exit_stop_loss",
                    reasons=[f"손절 -{cfg.stop_loss_pct}% (현재 {pnl_pct:.2f}%)"],
                    metadata={"pnl_pct": pnl_pct},
                )
            )
            narrative.append("→ 손절 청산 신호")
            diag = SymbolSignalDiagnosis(
                symbol=symbol,
                phase=state.phase.value,
                would_enter=False,
                would_exit=True,
                checklist=checklist,
                narrative=narrative,
            )
            return signals, diag, state

        if not state.first_take_profit_done and pnl_pct >= cfg.first_take_profit_pct:
            sell_q = max(int(qty * 0.5), 1)
            signals.append(
                StandardEngineSignal(
                    symbol=symbol,
                    side="sell",
                    quantity=sell_q,
                    limit_price=live.last,
                    stop_loss_pct=None,
                    strategy_id=cfg.strategy_id,
                    kind="exit_take_profit_partial",
                    reasons=[f"+{cfg.first_take_profit_pct}% 1차 부분 익절 (현재 {pnl_pct:.2f}%)"],
                    metadata={"pnl_pct": pnl_pct},
                )
            )
            state.first_take_profit_done = True
            state.phase = SymbolStrategyPhase.REDUCED
            state.touch()
            narrative.append("→ 1차 익절(50% 근처) 신호")
            diag = SymbolSignalDiagnosis(
                symbol=symbol,
                phase=state.phase.value,
                would_enter=False,
                would_exit=True,
                checklist=checklist,
                narrative=narrative,
            )
            return signals, diag, state

        if state.first_take_profit_done:
            hi = float(state.highest_price_since_entry or avg_price)
            if _trailing_stop_triggered(
                close=close,
                atr=atr14,
                low_n=low_n,
                highest_price=hi,
                mode=cfg.trailing_mode,
                atr_multiplier=cfg.trailing_atr_multiplier,
            ):
                signals.append(
                    StandardEngineSignal(
                        symbol=symbol,
                        side="sell",
                        quantity=qty,
                        limit_price=live.last,
                        stop_loss_pct=None,
                        strategy_id=cfg.strategy_id,
                        kind="exit_trailing",
                        reasons=["1차 익절 후 트레일링 스탑 충족"],
                        metadata={"highest": hi, "atr14": atr14, "low_n": low_n},
                    )
                )
                narrative.append("→ 트레일링 청산 신호")
                diag = SymbolSignalDiagnosis(
                    symbol=symbol,
                    phase=state.phase.value,
                    would_enter=False,
                    would_exit=True,
                    checklist=checklist,
                    narrative=narrative,
                )
                return signals, diag, state

        if pnl_pct >= cfg.second_take_profit_pct:
            signals.append(
                StandardEngineSignal(
                    symbol=symbol,
                    side="sell",
                    quantity=qty,
                    limit_price=live.last,
                    stop_loss_pct=None,
                    strategy_id=cfg.strategy_id,
                    kind="exit_take_profit_full",
                    reasons=[f"+{cfg.second_take_profit_pct}% 전량 익절 (현재 {pnl_pct:.2f}%)"],
                    metadata={"pnl_pct": pnl_pct},
                )
            )
            narrative.append("→ 2차 전량 익절 신호")
            diag = SymbolSignalDiagnosis(
                symbol=symbol,
                phase=state.phase.value,
                would_enter=False,
                would_exit=True,
                checklist=checklist,
                narrative=narrative,
            )
            return signals, diag, state

        if hold_days >= cfg.time_exit_days and pnl_pct <= 0.0:
            signals.append(
                StandardEngineSignal(
                    symbol=symbol,
                    side="sell",
                    quantity=qty,
                    limit_price=live.last,
                    stop_loss_pct=None,
                    strategy_id=cfg.strategy_id,
                    kind="exit_time",
                    reasons=[f"{cfg.time_exit_days}일 시간청산(손익≤0, 현재 {pnl_pct:.2f}%)"],
                    metadata={"hold_days": hold_days},
                )
            )
            narrative.append("→ 시간 청산 신호")
            diag = SymbolSignalDiagnosis(
                symbol=symbol,
                phase=state.phase.value,
                would_enter=False,
                would_exit=True,
                checklist=checklist,
                narrative=narrative,
            )
            return signals, diag, state

        # 부분 보유: 청산 없으면 2차 분할만 추가 검토
        if broker_legs == 1 and qty < cfg.order_quantity:
            narrative.append("청산 조건 없음 → 분할 잔량(2차) 진입 가능 여부 확인")
            gate2 = explain_entry_gate()
            q1, q2 = _leg_quantities(cfg)
            if gate2 and leg2_ok:
                signals.append(
                    StandardEngineSignal(
                        symbol=symbol,
                        side="buy",
                        quantity=min(q2, cfg.order_quantity - qty),
                        limit_price=live.last,
                        stop_loss_pct=cfg.stop_loss_pct,
                        strategy_id=cfg.strategy_id,
                        kind="entry_leg2",
                        reasons=[
                            f"2차 분할(-{abs(cfg.second_leg_drawdown_pct)}% 고점대비 {dd_from_high_pct:.2f}%)",
                            f"잔여 목표수량 충전",
                        ],
                        metadata={"leg": 2, "dd_pct": dd_from_high_pct},
                    )
                )
                state.phase = SymbolStrategyPhase.HOLDING
                state.entry_legs_done = 2
                state.touch()
                narrative.append("→ 2차 분할 매수 신호")
            elif not gate2:
                narrative.append("2차 진입: 추세/RSI/양봉/국면 게이트 미충족")
            else:
                narrative.append(
                    f"2차 진입 대기: 고점 대비 {dd_from_high_pct:.2f}% (필요 ≤{cfg.second_leg_drawdown_pct}%)"
                )
            diag = SymbolSignalDiagnosis(
                symbol=symbol,
                phase=state.phase.value,
                would_enter=bool(signals),
                would_exit=False,
                checklist=checklist,
                narrative=narrative,
            )
            return signals, diag, state

        narrative.append("청산 조건 미충족 → 홀딩(분할 완료)")
        diag = SymbolSignalDiagnosis(
            symbol=symbol,
            phase=state.phase.value,
            would_enter=False,
            would_exit=False,
            checklist=checklist,
            narrative=narrative,
        )
        return signals, diag, state

    # ---------- 분할 진입 (무포지션 → 1차) ----------
    gate = explain_entry_gate()
    q1, _q2 = _leg_quantities(cfg)

    if not gate:
        diag = SymbolSignalDiagnosis(
            symbol=symbol,
            phase=state.phase.value,
            would_enter=False,
            would_exit=False,
            checklist=checklist,
            narrative=narrative,
        )
        return signals, diag, state

    if broker_legs == 0 and leg1_ok:
        signals.append(
            StandardEngineSignal(
                symbol=symbol,
                side="buy",
                quantity=q1,
                limit_price=live.last,
                stop_loss_pct=cfg.stop_loss_pct,
                strategy_id=cfg.strategy_id,
                kind="entry_leg1",
                reasons=[
                    f"1차 분할(-{abs(cfg.first_leg_drawdown_pct)}% 고점대비 {dd_from_high_pct:.2f}%)",
                    f"RSI={rsi:.1f}, 3일={ret_3d:.2f}%",
                ],
                metadata={"leg": 1, "dd_pct": dd_from_high_pct},
            )
        )
        state.phase = SymbolStrategyPhase.SCALE_IN
        state.entry_legs_done = 1
        state.touch()
        narrative.append("→ 1차 분할 매수 신호")
    else:
        narrative.append(
            f"1차 진입 대기: 고점 대비 {dd_from_high_pct:.2f}% (필요 ≤{cfg.first_leg_drawdown_pct}%)"
        )

    diag = SymbolSignalDiagnosis(
        symbol=symbol,
        phase=state.phase.value,
        would_enter=bool(signals),
        would_exit=False,
        checklist=checklist,
        narrative=narrative,
    )
    return signals, diag, state


class DuplicateSignalSuppressor:
    """동일 (종목, kind) 신호를 TTL 안에 재발화하지 않음."""

    def __init__(self, ttl_sec: float = 120.0) -> None:
        self.ttl_sec = ttl_sec
        self._last: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def should_emit(self, symbol: str, kind: str) -> bool:
        key = (symbol, kind)
        now = time.monotonic()
        with self._lock:
            prev = self._last.get(key)
            if prev is not None and (now - prev) < self.ttl_sec:
                return False
            self._last[key] = now
            return True

    def reset_symbol(self, symbol: str) -> None:
        with self._lock:
            for k in list(self._last):
                if k[0] == symbol:
                    del self._last[k]


_engine_lock = threading.Lock()
_engine: SwingSignalEngine | None = None


class SwingSignalEngine:
    def __init__(
        self,
        *,
        cfg: SwingSignalEngineConfig | None = None,
        suppress_ttl_sec: float = 120.0,
    ) -> None:
        self.cfg = cfg or SwingSignalEngineConfig()
        self.suppressor = DuplicateSignalSuppressor(ttl_sec=suppress_ttl_sec)
        self._states: dict[str, SymbolStrategyState] = {}
        self._lock = threading.Lock()
        self._last_snapshot: SignalEngineSnapshot | None = None

    def state_for(self, symbol: str) -> SymbolStrategyState:
        with self._lock:
            if symbol not in self._states:
                self._states[symbol] = SymbolStrategyState(symbol=symbol)
            return self._states[symbol]

    def _set_state(self, symbol: str, st: SymbolStrategyState) -> None:
        with self._lock:
            self._states[symbol] = st

    def get_snapshot(self) -> SignalEngineSnapshot | None:
        with self._lock:
            return self._last_snapshot

    def evaluate(
        self,
        prices_df: pd.DataFrame,
        quotes: dict[str, LiveQuoteView],
        portfolio_df: pd.DataFrame,
        *,
        market_regime: str | None = None,
    ) -> SignalEngineSnapshot:
        suppressed: list[dict[str, Any]] = []
        all_signals: list[StandardEngineSignal] = []
        diagnoses: list[SymbolSignalDiagnosis] = []
        if prices_df.empty:
            snap = SignalEngineSnapshot(
                evaluated_at_utc=datetime.now(timezone.utc).isoformat(),
                market_regime=str(market_regime) if market_regime else None,
                signals=[],
                suppressed=[],
                per_symbol=[],
                states={},
            )
            with self._lock:
                self._last_snapshot = snap
            return snap

        symbols = prices_df["symbol"].drop_duplicates().tolist()
        states_out: dict[str, dict[str, Any]] = {}

        for symbol in symbols:
            sym = str(symbol)
            g = prices_df[prices_df["symbol"] == sym]
            live = quotes.get(sym)
            if live is None or live.last <= 0:
                narrative = [f"{sym}: 실시간 호가 없음 — 일봉 종가만으로는 실시간 신호 생략"]
                diagnoses.append(
                    SymbolSignalDiagnosis(
                        symbol=sym,
                        phase="unknown",
                        would_enter=False,
                        would_exit=False,
                        checklist={"quote_ok": False},
                        narrative=narrative,
                    )
                )
                continue

            merged = merge_daily_with_live(g, live)
            st = self.state_for(sym)
            sigs, diag, new_st = evaluate_symbol(
                sym,
                merged,
                live,
                cfg=self.cfg,
                state=st,
                portfolio_df=portfolio_df,
                market_regime=market_regime,
            )
            self._set_state(sym, new_st)
            diagnoses.append(diag)
            states_out[sym] = {
                "phase": new_st.phase.value,
                "entry_legs_done": new_st.entry_legs_done,
                "first_take_profit_done": new_st.first_take_profit_done,
                "highest_price_since_entry": new_st.highest_price_since_entry,
            }

            for s in sigs:
                if not self.suppressor.should_emit(s.symbol, s.kind):
                    suppressed.append({"symbol": s.symbol, "kind": s.kind, "reason": "duplicate_ttl"})
                    logger.info(
                        "signal suppressed duplicate symbol=%s kind=%s",
                        s.symbol,
                        s.kind,
                    )
                    continue
                all_signals.append(s)
                logger.info(
                    "signal emit symbol=%s kind=%s side=%s qty=%s reasons=%s",
                    s.symbol,
                    s.kind,
                    s.side,
                    s.quantity,
                    "; ".join(s.reasons),
                )

        snap = SignalEngineSnapshot(
            evaluated_at_utc=datetime.now(timezone.utc).isoformat(),
            market_regime=str(market_regime) if market_regime else None,
            signals=all_signals,
            suppressed=suppressed,
            per_symbol=diagnoses,
            states=states_out,
        )
        with self._lock:
            self._last_snapshot = snap
        return snap


def get_swing_signal_engine() -> SwingSignalEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            from backend.app.core.config import get_backend_settings

            b = get_backend_settings()
            _engine = SwingSignalEngine(
                suppress_ttl_sec=float(b.signal_suppress_ttl_sec),
                cfg=SwingSignalEngineConfig(order_quantity=b.signal_engine_order_quantity),
            )
        return _engine


def dispatch_engine_signals_to_risk(
    signals: list[StandardEngineSignal],
    order_manager: Any,
    snapshot: Any,
) -> list[Any]:
    """
    리스크·주문 파이프라인 연결점: `OrderManager.process_signal(OrderSignal, RiskSnapshot)`.

    `order_manager`는 `app.orders.order_manager.OrderManager` 인스턴스,
    `snapshot`는 `app.risk.rules.RiskSnapshot`.
    """
    out: list[Any] = []
    for es in signals:
        out.append(order_manager.process_signal(es.to_order_signal(), snapshot))
    return out


def snapshot_to_jsonable(snap: SignalEngineSnapshot) -> dict:
    return {
        "evaluated_at_utc": snap.evaluated_at_utc,
        "market_regime": snap.market_regime,
        "signals": [
            {
                "signal_id": s.signal_id,
                "symbol": s.symbol,
                "side": s.side,
                "quantity": s.quantity,
                "limit_price": s.limit_price,
                "stop_loss_pct": s.stop_loss_pct,
                "strategy_id": s.strategy_id,
                "kind": s.kind,
                "reasons": s.reasons,
                "metadata": s.metadata,
            }
            for s in snap.signals
        ],
        "suppressed": snap.suppressed,
        "per_symbol": [
            {
                "symbol": d.symbol,
                "phase": d.phase,
                "would_enter": d.would_enter,
                "would_exit": d.would_exit,
                "checklist": d.checklist,
                "narrative": d.narrative,
            }
            for d in snap.per_symbol
        ],
        "states": snap.states,
    }
