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
  - res: `LiveTradingStatusResponse`
- `POST /settings`
  - req: `LiveTradingSettingsUpdateRequest`
  - res: `{ ok: boolean } & LiveTradingStatusResponse`
- `GET /runtime-safety-validation`
  - res: `RuntimeSafetyValidationResponse`
- `GET /kill-switch-status`
  - res: `KillSwitchStatusResponse`
- `GET /settings-history`
  - res: `{ items: Array<{ ts: string; actor: string; action: string; reason: string }> }`

## 9) OpenAPI 자동생성 전환 가이드

- 필드명 규칙(snake_case)과 enum literal을 shared 모델에서 먼저 고정
- backend 라우트별 response_model을 순차 도입해 스키마 강제
- 이후 OpenAPI schema export -> TS codegen으로 `shared/models` 대체 또는 동기화
- CI에서 `shared/models`와 OpenAPI generated 타입 diff 검사 추가 권장
