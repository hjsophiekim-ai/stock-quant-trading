# API Contract for Mobile/Desktop Apps

앱(`apps/mobile`, `apps/desktop`)과 서버(`backend`) 간 API 스켈레톤 계약 문서입니다.  
목표는 앱/서버 타입 불일치를 줄이고, 이후 OpenAPI 기반 자동생성으로 전환하기 쉽게 구조화하는 것입니다.

## 1) 타입 파일 맵

- `shared/models/auth.ts`
- `shared/models/broker.ts`
- `shared/models/dashboard.ts`
- `shared/models/performance.ts`
- `shared/models/trading.ts`
- `shared/models/stocks_local_search.ts`

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
  - res: `BrokerConnectionTestResponse` (토큰 발급 후 **잔고조회**까지 성공해야 `ok: true`)

## 3b) 종목 찾기 (역할 분리, 앱 내 목록)

Base: `/api/stocks` — 모두 `data/domestic_liquid_symbols.json` 또는 스크리너/신호 스냅샷 기준. **KIS 공식 실시간 검색 아님.**

| 목적 | 메서드 | 설명 |
|------|--------|------|
| ① 종목명 검색 | `GET /search-by-name?q=삼성&limit=40` | 한글 **이름** 부분 일치 |
| ② 심볼 검색 | `GET /search-by-symbol?q=005930&limit=40` | **6자리 코드** 접두·부분 일치 |
| ③ 전략 후보 | `GET /strategy-candidates?strategy_id=swing_v1` | 스크리너 `candidates` + 스윙 신호 `per_symbol` (검색과 다른 소스) |
| (레거시) | `GET /local-symbol-search?q=&limit=` | 이름·코드 **혼합** — 신규는 ①② 권장 |

## 4) Dashboard API

Base: `/api/dashboard`

- `GET /summary`
  - res: `DashboardSummaryResponse`

## 5) Paper Trading API

Base: `/api/paper-trading`

- `POST /start`
  - req: `StartPaperTradingRequest`
  - res: `{ ok: boolean } & PaperTradingStatusResponse`
- `POST /stop`
  - res: `{ ok: boolean } & PaperTradingStatusResponse`
- `GET /status`
  - optional `Authorization: Bearer` — when present, `manual_market_mode_override` reflects the **persisted** per-user Paper market-mode preference even if no session is running (after stop, `_user_id` is cleared; unauthenticated calls fall back to `auto` for that field).
  - res: `PaperTradingStatusResponse` (includes `manual_market_mode_override`, `market_mode` snapshot from last tick when available, `market_mode_summary` human string)
- `GET /positions`
  - res: `PaperTradingPositionsResponse`
- `GET /pnl`
  - res: `PaperTradingPnlResponse`
- `GET /logs`
  - res: `PaperTradingLogsResponse`
- `GET /market-mode` (Authorization: Bearer)
  - res: `{ ok: true, manual_market_mode_override, ... }` plus last tick `market_mode` fields when session owner is running.
- `POST /market-mode` (Authorization: Bearer)
  - req: `{ "manual_market_mode": "auto" | "aggressive" | "neutral" | "defensive" }`
  - res: `{ ok: true, manual_market_mode_override }` — persisted per user; next paper tick applies to strategy policy.
- `GET /dashboard-data` (Authorization: Bearer)
  - res: `{ ok: true, candidate_count, candidates, generated_order_count, generated_orders, no_order_reason, last_diagnostics, candidate_filter_breakdown, tick_report, manual_market_mode_override, market_mode, ... }`
  - `tick_report`: 위 틱 메타를 한 객체로 묶은 것(중복 허용·클라이언트 표시용).
  - `candidate_filter_breakdown`: `candidate_count===0` 이고 유니버스가 있을 때 swing 품질 필터 종목별 실패 사유.

## 6) Performance API

Base: `/api/performance`

공통 query: `PerformanceFilterQuery`

- `GET /metrics` -> `PerformanceMetricsResponse`
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

- `GET /status` (Authorization: Bearer)
  - res: `LiveTradingStatusResponse`
- `POST /settings` (Authorization: Bearer)
  - req: `LiveTradingSettingsUpdateRequest`
  - res: `{ ok: boolean } & LiveTradingStatusResponse`
- `GET /runtime-safety-validation` (Authorization: Bearer)
  - res: `RuntimeSafetyValidationResponse`
- `GET /kill-switch-status` (Authorization: Bearer)
  - res: `KillSwitchStatusResponse`
- `GET /settings-history` (Authorization: Bearer)
  - res: `{ items: Array<{ ts: string; actor: string; action: string; reason: string }> }`
- `POST /emergency-stop` (Authorization: Bearer)
  - req: `{ enabled: boolean, reason: string, actor?: string }`
  - res: `{ ok: boolean } & LiveTradingStatusResponse`

## 8b) Live Prep API (Manual Approval)

Base: `/api/live-prep`

실거래 자동 제출(무인 실행)은 기본 금지입니다. 이 API는 **후보/신호 산출 + 수동 승인 기반 제출**이 기본이며, 별도 `sell-only arm`은 final_betting 포지션의 매도 신호에 한해 제한적으로 사용합니다.

- `GET /status` (Authorization: Bearer)
  - res: `{ trading_mode, execution_mode, live_ready_for_submit, blockers, blocker_details }`
- `POST /final-betting/generate?limit=5` (Authorization: Bearer)
  - res: `{ ok: true, items: LiveCandidate[], shadow: object }`
- `POST /hf-shadow/generate?strategy_id=scalp_rsi_flag_hf_v1` (Authorization: Bearer)
  - res: `{ ok: true, order_allowed: false, generated_orders: object[] }` (신호/가상주문 출력)
- `GET /sell-only-arm/status` (Authorization: Bearer)
  - res: `{ ok: true, state: SellOnlyArmState | null }`
- `POST /sell-only-arm` (Authorization: Bearer)
  - req: `{ enabled: boolean, armed_for_kst_date?: string, actor?: string, reason?: string }`
  - res: `{ ok: true, state: SellOnlyArmState }`
- `POST /batch-liquidation/prepare` (Authorization: Bearer)
  - req: `{ use_market_order?: boolean, actor?: string, reason?: string }`
  - res: `{ ok: true, plan: LiquidationPlan }`
- `GET /batch-liquidation/plans?limit=10` (Authorization: Bearer)
  - res: `{ ok: true, plans: LiquidationPlan[], count: number }`
- `POST /batch-liquidation/{plan_id}/execute` (Authorization: Bearer)
  - req: `{ confirm: "LIQUIDATE_ALL", actor?: string, reason?: string }`
  - res: `{ ok: true, plan: LiquidationPlan, submitted: object[], skipped: object[] }`
- `GET /candidates?status_filter=&strategy_id=&symbol=&limit=200` (Authorization: Bearer)
  - res: `{ items: LiveCandidate[], count: number }`
- `POST /candidates/{candidate_id}/approve` (Authorization: Bearer)
  - req: `{ actor?: string, reason?: string }`
  - res: `{ ok: true, candidate: LiveCandidate }`
- `POST /candidates/{candidate_id}/reject` (Authorization: Bearer)
  - req: `{ actor?: string, reason?: string }`
  - res: `{ ok: true, candidate: LiveCandidate }`
- `POST /candidates/{candidate_id}/submit` (Authorization: Bearer)
  - req: `{ actor?: string, reason?: string }`
  - res: `{ ok: true, candidate: LiveCandidate, broker_result: object }`

## 8c) Live Exec API (Execution Console)

Base: `/api/live-exec`

Paper처럼 Live 세션을 시작/중지하고, Tick을 통해 **수동 실행(무인 자동 실행 금지)** 기반으로 후보/리포트를 갱신합니다.

- `GET /status?include_history=false` (Authorization: Bearer)
  - res: `{ ok, config, safety, session, session_running, supported_strategies, counts, blocked, history? }`
- `POST /start` (Authorization: Bearer)
  - req: `{ strategy_id, market, execution_mode, actor?: string, reason?: string }`
  - res: `{ ok: true, session: LiveExecSession }`
- `POST /stop` (Authorization: Bearer)
  - req: `{ actor?: string, reason?: string }`
  - res: `{ ok: true, stopped: boolean, session?: LiveExecSession }`
- `POST /tick` (Authorization: Bearer)
  - res: `{ ok: true, session: LiveExecSession, result: object, counts }`

## 9) OpenAPI 자동생성 전환 가이드

- 필드명 규칙(snake_case)과 enum literal을 shared 모델에서 먼저 고정
- backend 라우트별 response_model을 순차 도입해 스키마 강제
- 이후 OpenAPI schema export -> TS codegen으로 `shared/models` 대체 또는 동기화
- CI에서 `shared/models`와 OpenAPI generated 타입 diff 검사 추가 권장
