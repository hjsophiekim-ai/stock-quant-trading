# Dashboard/Performance 데이터 출처

이 문서는 대시보드/성과 API의 각 값이 어떤 내부 상태에서 계산되는지 정리합니다.

## 1) Dashboard Summary

- API: `GET /api/dashboard/summary`
- 출처 필드:
  - `value_sources`: 항목별 계산 원천
  - `data_quality`: 추정/제약 여부

주요 원천:
- `portfolio_snapshot.*`: `portfolio_data` 마지막 동기화 스냅샷
- `runtime_engine.status()`: 런타임 엔진 상태
- `build_public_risk_status()`: 리스크 집계 상태
- `screener/signal snapshot`: 종목 후보/국면 스냅샷
- `fills.jsonl`: 최근 체결 이력

## 2) Performance Metrics

- API: `GET /api/performance/metrics`
- 출처 필드:
  - `value_sources`: 항목별 계산 원천
  - `data_quality`: 추정/제약 여부

주요 원천:
- 수익률/실현·미실현: 포트폴리오 동기화 스냅샷
- MDD/주간·월간 수익률: `pnl_history.jsonl` 이력 기반 계산
- 승률/손익비: `fills.jsonl` 체결 리플레이 기반 추정

## 3) 현재 제약(TODO)

- `open_orders`는 서버 런타임 계정 기준이며 앱 사용자별 1:1 미체결 동기화는 미완료
- `recent_fills`/손익 카드는 서버 `portfolio_data` 기준(멀티 사용자 분리 저장 TODO)
- 체결 리플레이 기반 승률/손익비는 수수료·세금·정밀 FIFO를 완전 반영하지 않음
