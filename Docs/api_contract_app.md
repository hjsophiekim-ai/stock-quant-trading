# API Contract for Mobile/Desktop Apps

앱(`apps/mobile`, `apps/desktop`)과 서버(`backend`) 간 API 스켈레톤 계약 문서입니다.  
목표는 앱/서버 타입 불일치를 줄이고, 이후 OpenAPI 기반 자동생성으로 전환하기 쉽게 구조화하는 것입니다.

## 1) 타입 파일 맵

- `shared/models/auth.ts`
- `shared/models/broker.ts`
- `shared/models/dashboard.ts`
- `shared/models/performance.ts`
- `shared/models/trading.ts`

모든 필드는 snake_case JSON 기준으로 정의하며, 서버 응답 키와 동일하게 유지합니다.

## 2) Auth API

Base: `/api/auth`

- `POST /register`
  - req: `RegisterRequest`
  - res: `AuthUser`
- `POST /login`
  - req: `LoginRequest`
  - res: `TokenPairResponse`
- `POST /refresh`
  - req: `RefreshTokenRequest`
  - res: `TokenPairResponse`
- `POST /logout`
  - req: `LogoutRequest`
  - res: `{ status: "ok" }`
- `GET /me`
  - res: `AuthUser`

## 3) Broker Account API

Base: `/api/broker-accounts`

- `GET /me`
  - res: `BrokerAccountResponse`
- `POST /me`
  - req: `BrokerAccountUpsertRequest`
  - res: `BrokerAccountResponse`
- `DELETE /me`
  - res: `{ status: "deleted" }`
- `POST /me/test-connection`
  - res: `BrokerConnectionTestResponse`

## 4) Dashboard API

Base: `/api/dashboard`

- `GET /summary`
  - res: `DashboardSummaryResponse`
  - `screener` / `selected_candidates`: 종목 스크리너 스냅샷. 후보에는 `score`, `reasons`(초보자용), `reasons_detail`, `block_reasons`(선정 시 빈 배열), `metrics`, `exclusions`(제외 종목·사유), `regime_screening_profile`(국면별 가중·임계값) 포함.

Base: `/api/screening`

- `GET /latest`, `POST /refresh` — 위와 동일 필드 + `exclusion_count`.

## 5) Paper Trading API

Base: `/api/paper-trading`

- `POST /start`
  - req: `StartPaperTradingRequest`
  - res: `{ ok: boolean } & PaperTradingStatusResponse`
- `POST /stop`
  - res: `{ ok: boolean } & PaperTradingStatusResponse`
- `GET /status`
  - res: `PaperTradingStatusResponse`
- `GET /positions`
  - res: `PaperTradingPositionsResponse`
- `GET /pnl`
  - res: `PaperTradingPnlResponse`
- `GET /logs`
  - res: `PaperTradingLogsResponse`

## 6) Performance API

Base: `/api/performance`

공통 query: `PerformanceFilterQuery`

- `GET /metrics` -> `PerformanceMetricsResponse`
  - 자산 수익률: `pnl_history.jsonl` equity 곡선(필터 구간). `cumulative_return_pct`와 `net_cumulative_return_pct`는 동일(자산 기준 별칭).
  - 체결: `fills.jsonl` **FIFO**; `gross_realized_pnl`, `total_fees`, `total_taxes`, `net_realized_pnl`; 컬럼 없으면 `KIS_BUY_FEE_RATE`, `KIS_SELL_FEE_RATE`, `KRX_SELL_TAX_RATE`(소수 비율).
  - `calculation_basis`, `assumptions`, `data_quality`, `display_labels_ko`, `fee_rates_applied` 등 메타 포함.
- `GET /dashboard/summary` 의 flat `today_return_pct` / `monthly_return_pct` / `cumulative_return_pct` 는 위와 동일 집계(`performance_aligned`).
- `GET /pnl-history` -> `PnlHistoryResponse`
- `GET /trade-history` -> `TradeHistoryResponse`
- `GET /symbol-performance` -> `SymbolPerformanceResponse`
- `GET /strategy-performance` -> `StrategyPerformanceResponse`
- `GET /regime-performance` -> `RegimePerformanceResponse`

## 7) Orders/Recent Trades API

Base: `/api/trading`

- `GET /mode`
  - res: `TradingModeResponse`
- `GET /orders`
  - res: `{ items: unknown[] }` (skeleton, 추후 구체화)
- `GET /recent-trades`
  - res: `RecentTradesResponse`

## 8) Risk Status API (Live Safety/Kill Switch)

Base: `/api/live-trading`

- `GET /status`
  - res: `LiveTradingStatusResponse` — `paper_readiness_ok`, `can_place_live_order`(환경·앱 승인·**모의 검증** 모두 충족 시만 true)
- `GET /paper-readiness`
  - res: 모의투자 자동 체크리스트(항목별 pass/관측값/임계값/설명 한글)
- `POST /settings`
  - req: `LiveTradingSettingsUpdateRequest`
  - res: `{ ok: boolean } & LiveTradingStatusResponse`
  - 앱에서 세 확인 플래그를 모두 켜 실거래 해제를 시도할 때, 모의 검증 미통과 시 **403** 및 `message_ko`(초보자용 문구)
- `GET /runtime-safety-validation`
  - res: `RuntimeSafetyValidationResponse` + `paper_readiness`
- `GET /kill-switch-status`
  - res: `KillSwitchStatusResponse`
- `GET /settings-history`
  - res: `{ items: Array<{ ts: string; actor: string; action: string; reason: string }> }` — 거절 시 `live_unlock_denied_paper_readiness` 등 기록

## 9) OpenAPI 자동생성 전환 가이드

- 필드명 규칙(snake_case)과 enum literal을 shared 모델에서 먼저 고정
- backend 라우트별 response_model을 순차 도입해 스키마 강제
- 이후 OpenAPI schema export -> TS codegen으로 `shared/models` 대체 또는 동기화
- CI에서 `shared/models`와 OpenAPI generated 타입 diff 검사 추가 권장
