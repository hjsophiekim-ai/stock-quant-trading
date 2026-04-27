"""
모의투자(paper) 충분 검증 후에만 실거래(live) 잠금 해제를 허용하기 위한 자동 체크리스트.

- 데이터가 없으면 '통과'가 아니라 '측정 불가'로 실패 처리(보수적).
- LIVE_UNLOCK_BYPASS=true 인 경우에만 운영자 테스트용으로 게이트 생략.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.app.risk.audit import read_jsonl_tail


def _read_jsonl_all(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


@dataclass
class ChecklistItem:
    check_id: str
    label_ko: str
    passed: bool
    observed: str | float | int | None
    threshold: str
    detail_ko: str


@dataclass
class PaperReadinessResult:
    ok: bool
    bypassed: bool
    items: list[ChecklistItem] = field(default_factory=list)
    user_message_ko: str = ""
    technical_summary: str = ""


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _pnl_rows_in_window(
    portfolio_dir: Path,
    *,
    lookback_days: int,
) -> list[dict[str, Any]]:
    p = portfolio_dir / "pnl_history.jsonl"
    rows = _read_jsonl_all(p)
    if not rows:
        return []
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    out: list[dict[str, Any]] = []
    for r in rows:
        dt = _parse_ts(str(r.get("ts_utc") or ""))
        if dt is None:
            continue
        if start <= dt <= end:
            out.append(r)
    out.sort(key=lambda x: str(x.get("ts_utc") or ""))
    return out


def _period_return_pct(equities: list[float]) -> float | None:
    if len(equities) < 2:
        return None
    a, b = equities[0], equities[-1]
    if a <= 0 or b <= 0:
        return None
    return ((b / a) - 1.0) * 100.0


def _max_drawdown_pct(equities: list[float]) -> float:
    if not equities:
        return 0.0
    peak = equities[0]
    worst = 0.0
    for e in equities:
        if e > peak:
            peak = e
        if peak > 0:
            dd = ((e / peak) - 1.0) * 100.0
            if dd < worst:
                worst = dd
    return float(worst)


def _max_consecutive_negative_daily_pnl(rows: list[dict[str, Any]]) -> int:
    streak = 0
    best = 0
    for r in rows:
        try:
            d = float(r.get("daily_pnl_pct") or 0.0)
        except (TypeError, ValueError):
            d = 0.0
        if d < 0:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best


_TECH_PAT = re.compile(r"kis|api|timeout|network|http|token|연결|실패|error|exception", re.I)


def _technical_rejection(decision: dict[str, Any]) -> bool:
    if decision.get("approved"):
        return False
    reason = str(decision.get("reason") or "")
    code = str(decision.get("reason_code") or "")
    blob = f"{reason} {code}"
    return bool(_TECH_PAT.search(blob))


def _order_audit_issue_rate(audit_path: str | Path, *, max_lines: int = 800) -> tuple[float | None, int, int]:
    rows = read_jsonl_tail(audit_path, max_lines=max_lines)
    technical = 0
    total = 0
    for r in rows:
        d = r.get("decision")
        if not isinstance(d, dict):
            continue
        total += 1
        if _technical_rejection(d):
            technical += 1
    if total == 0:
        return None, 0, 0
    return technical / float(total), technical, total


def _read_sync_failures(portfolio_dir: Path) -> int:
    p = portfolio_dir / "sync_failures.json"
    if not p.is_file():
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 999
    return int(data.get("consecutive_failures") or 0)


def paper_readiness_data_health(settings: Any) -> dict[str, Any]:
    cfg = settings
    root = Path(cfg.portfolio_data_dir)
    lookback = int(getattr(cfg, "live_unlock_lookback_days", 30) or 30)
    min_samples = int(getattr(cfg, "live_unlock_min_pnl_samples", 10) or 10)

    pnl_path = root / "pnl_history.jsonl"
    pnl_rows = _pnl_rows_in_window(root, lookback_days=lookback)
    last_pnl = pnl_rows[-1] if pnl_rows else None
    last_pnl_ts = str(last_pnl.get("ts_utc") or "") if isinstance(last_pnl, dict) else ""

    audit_path = Path(cfg.risk_order_audit_jsonl)
    audit_tail = read_jsonl_tail(audit_path, max_lines=200)
    last_audit = audit_tail[-1] if audit_tail else None
    last_audit_ts = str(last_audit.get("ts_utc") or "") if isinstance(last_audit, dict) else ""

    sync_path = root / "sync_failures.json"
    sync_failures = _read_sync_failures(root)
    sync_ok = sync_failures <= int(getattr(cfg, "live_unlock_max_sync_failure_streak", 0) or 0)

    equity_ok_n = 0
    for r in pnl_rows:
        try:
            if float(r.get("equity") or 0.0) > 0:
                equity_ok_n += 1
        except (TypeError, ValueError):
            continue

    return {
        "pnl_history_path": str(pnl_path),
        "pnl_rows_found": int(len(pnl_rows)),
        "pnl_equity_rows_found": int(equity_ok_n),
        "pnl_min_samples_required": int(min_samples),
        "last_pnl_sample_ts": last_pnl_ts or None,
        "pnl_data_ok": bool(len(pnl_rows) >= min_samples and equity_ok_n >= min_samples),
        "risk_order_audit_path": str(audit_path),
        "audit_rows_found_tail": int(len(audit_tail)),
        "last_audit_sample_ts": last_audit_ts or None,
        "audit_data_ok": bool(len(audit_tail) > 0),
        "sync_failures_path": str(sync_path),
        "sync_failures_found": int(sync_failures),
        "sync_data_ok": bool(sync_ok),
        "overall_data_ok": bool(
            (len(pnl_rows) >= min_samples and equity_ok_n >= min_samples) and (len(audit_tail) > 0) and sync_ok
        ),
    }


def evaluate_paper_readiness(settings: Any) -> PaperReadinessResult:
    cfg = settings
    if not cfg.live_unlock_enabled:
        return PaperReadinessResult(
            ok=True,
            bypassed=True,
            user_message_ko="실거래 전 자동 검증이 비활성화되어 있습니다(운영 설정).",
            technical_summary="LIVE_UNLOCK_ENABLED=false",
        )

    if cfg.live_unlock_bypass:
        return PaperReadinessResult(
            ok=True,
            bypassed=True,
            user_message_ko="운영자 테스트 모드: 모의 검증 게이트를 건너뜁니다.",
            technical_summary="LIVE_UNLOCK_BYPASS=true",
        )

    root = Path(cfg.portfolio_data_dir)
    lookback = cfg.live_unlock_lookback_days
    min_samples = cfg.live_unlock_min_pnl_samples

    rows = _pnl_rows_in_window(root, lookback_days=lookback)
    equities = [float(r.get("equity") or 0.0) for r in rows if float(r.get("equity") or 0.0) > 0]

    items: list[ChecklistItem] = []

    # 1) 표본 수
    sample_ok = len(rows) >= min_samples and len(equities) >= min_samples
    items.append(
        ChecklistItem(
            check_id="pnl_sample_size",
            label_ko="모의 구간 데이터 충분성",
            passed=sample_ok,
            observed=len(rows),
            threshold=f"≥ {min_samples}개 시점",
            detail_ko=f"최근 {lookback}일 안에 기록된 손익·자산 스냅샷이 부족하면 실거래 전 검증을 할 수 없습니다.",
        )
    )

    ret = _period_return_pct(equities) if sample_ok else None
    ret_ok = ret is not None and ret >= cfg.live_unlock_min_period_return_pct
    items.append(
        ChecklistItem(
            check_id="paper_period_return",
            label_ko="모의 기간 누적 수익률",
            passed=ret_ok,
            observed=round(ret, 4) if ret is not None else None,
            threshold=f"≥ {cfg.live_unlock_min_period_return_pct:.2f}%",
            detail_ko="최근 모의 구간에서 계좌 자산이 기준 이상으로 유지되었는지 봅니다(과도한 손실 구간이면 실거래 전에 중단 권장).",
        )
    )

    mdd = _max_drawdown_pct(equities) if sample_ok else 0.0
    mdd_ok = sample_ok and mdd >= -abs(cfg.live_unlock_max_mdd_pct)
    items.append(
        ChecklistItem(
            check_id="max_drawdown",
            label_ko="최대 낙폭(MDD)",
            passed=mdd_ok,
            observed=round(mdd, 4),
            threshold=f"≥ { -abs(cfg.live_unlock_max_mdd_pct):.2f}% (더 깊은 낙폭이면 불합격)",
            detail_ko="한 번에 얼마나 깊게 빠졌는지 봅니다. 낙폭이 크면 실거래에서도 비슷한 하락을 겪을 수 있습니다.",
        )
    )

    streak = _max_consecutive_negative_daily_pnl(rows)
    streak_ok = sample_ok and streak <= cfg.live_unlock_max_consecutive_loss_days
    items.append(
        ChecklistItem(
            check_id="consecutive_loss_days",
            label_ko="연속 손실일(일중 손익 기준)",
            passed=streak_ok,
            observed=streak,
            threshold=f"≤ {cfg.live_unlock_max_consecutive_loss_days}일",
            detail_ko="연속으로 마이너스가 나온 날이 많으면 전략·시장 환경을 다시 점검하는 편이 안전합니다.",
        )
    )

    rate, tech_n, tot_n = _order_audit_issue_rate(cfg.risk_order_audit_jsonl)
    if rate is None:
        audit_ok = False
        obs: str | float = "데이터 없음"
        detail = "주문 감사 로그가 없으면 체결·API 안정성을 확인할 수 없습니다. 모의 주문을 충분히 돌린 뒤 다시 시도하세요."
    else:
        audit_ok = rate <= cfg.live_unlock_max_order_issue_rate
        obs = round(rate * 100.0, 4)
        detail = f"최근 감사 {tot_n}건 중 기술적 거절·연결 이슈 추정 {tech_n}건입니다."
    items.append(
        ChecklistItem(
            check_id="order_issue_rate",
            label_ko="주문·연결 이상 비율(감사 로그)",
            passed=audit_ok,
            observed=obs,
            threshold=f"≤ {cfg.live_unlock_max_order_issue_rate * 100:.2f}%",
            detail_ko=detail,
        )
    )

    sync_streak = _read_sync_failures(root)
    sync_ok = sync_streak <= cfg.live_unlock_max_sync_failure_streak
    items.append(
        ChecklistItem(
            check_id="kis_sync_stability",
            label_ko="한국투자 연동(포트폴리오 동기화) 안정성",
            passed=sync_ok,
            observed=sync_streak,
            threshold=f"연속 실패 ≤ {cfg.live_unlock_max_sync_failure_streak}회",
            detail_ko="모의 서버와의 잔고·체결 동기화가 연속으로 실패하면 실거래 전에 환경을 점검해야 합니다.",
        )
    )

    ok = all(x.passed for x in items)
    if ok:
        msg = "모의투자 구간 자동 검증을 통과했습니다. 그래도 실거래는 소액·손절 규칙을 꼭 지키세요."
    else:
        failed = [x.label_ko for x in items if not x.passed]
        msg = (
            "실거래 잠금 해제 조건을 아직 충족하지 못했습니다. "
            f"다음 항목을 확인해 주세요: {', '.join(failed)}. "
            "모의투자를 더 돌리거나 설정(임계값)을 검토한 뒤 다시 시도하세요."
        )

    return PaperReadinessResult(
        ok=ok,
        bypassed=False,
        items=items,
        user_message_ko=msg,
        technical_summary="; ".join(f"{i.check_id}={'ok' if i.passed else 'fail'}" for i in items),
    )


def paper_readiness_to_dict(result: PaperReadinessResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "bypassed": result.bypassed,
        "user_message_ko": result.user_message_ko,
        "items": [
            {
                "check_id": i.check_id,
                "label_ko": i.label_ko,
                "passed": i.passed,
                "observed": i.observed,
                "threshold": i.threshold,
                "detail_ko": i.detail_ko,
            }
            for i in result.items
        ],
    }
