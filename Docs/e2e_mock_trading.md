# E2E Mock Trading API Flow (Swagger)

이 문서는 아래 흐름을 **Swagger에서 순서대로** 점검하는 용도입니다.

1. 회원가입  
2. 로그인  
3. 브로커 등록  
4. 연결 테스트  
5. 자동 종목선정  
6. 전략 신호 생성  
7. 리스크 승인  
8. KIS mock 주문 호출  
9. 주문 상태 추적  
10. 포지션/잔고/손익 반영  
11. dashboard/performance 반영 확인

> 기본 전제: `TRADING_MODE=paper`, `LIVE_TRADING* = false`

---

## 사전 준비

- backend 실행: `http://127.0.0.1:8000`
- Swagger: `http://127.0.0.1:8000/docs`
- `.env` 또는 앱 저장 브로커 정보가 모의계정으로 준비됨

---

## API Contract (핵심 경로)

### Auth
- `POST /api/auth/register`
  - req: `{ "email", "password", "display_name", "role":"user" }`
  - res: 사용자 정보
- `POST /api/auth/login`
  - req: `{ "email", "password" }`
  - res: `{ "access_token", "refresh_token", "user" }`

### Broker
- `POST /api/broker-accounts/me` (JWT)
  - req: `{ kis_app_key, kis_app_secret, kis_account_no, kis_account_product_code, trading_mode:"paper" }`
  - res: 저장된 마스킹 계정 정보
- `POST /api/broker-accounts/me/test-connection` (JWT)
  - res: `{ ok, message, error_code, trading_mode, kis_api_base }`

### Screening / Signal
- `POST /api/screening/refresh`
  - res: 후보 종목·국면·필터 로그
- `POST /api/strategy-signals/evaluate`
  - res: 신호 목록·종목별 진단·국면 사유

### Order / Tracking
- `POST /api/order-engine/execute-signal`
  - req: `{ symbol, side, quantity, limit_price?, strategy_id?, market_regime?, ... }`
  - 내부에서 리스크 승인 -> KIS mock 주문 호출
- `GET /api/order-engine/tracked`
  - res: 내부 추적 주문 목록
- `POST /api/order-engine/sync`
  - res: 미체결 동기화 반영 건수

### Portfolio / Dashboard / Performance
- `POST /api/portfolio/sync`
  - 잔고/체결 동기화 및 손익 스냅샷 갱신
- `GET /api/portfolio/summary`
  - res: equity/cash/realized/unrealized/positions
- `GET /api/dashboard/summary`
  - res: 시스템/브로커/paper/runtime/portfolio 집계
- `GET /api/performance/metrics`
  - res: 수익률/손익/승률/payoff 등 (실데이터 집계)

---

## Step 1~11 실행 순서 (Swagger)

## Step 1. 회원가입
- `POST /api/auth/register`
- 성공 기준: 200 + user id/email 응답

## Step 2. 로그인
- `POST /api/auth/login`
- 성공 기준: `access_token` 발급
- 이후 Swagger `Authorize`에 `Bearer <token>` 입력

## Step 3. 브로커 등록
- `POST /api/broker-accounts/me` (JWT)
- `trading_mode` 반드시 `"paper"`
- 성공 기준: 200 + 마스킹 계정 정보

## Step 4. 연결 테스트
- `POST /api/broker-accounts/me/test-connection` (JWT)
- 성공 기준: `ok=true`

## Step 5. 자동 종목선정 실행
- `POST /api/screening/refresh`
- 성공 기준: `status=ok` 또는 `status=blocked`(고변동 차단도 정상 시나리오)
- `candidates` 또는 `block_reason` 확인

## Step 6. 전략 신호 생성
- `POST /api/strategy-signals/evaluate`
- 성공 기준: `status=ok`, `signals` 및 `per_symbol` 진단 생성

## Step 7. 리스크 승인
- 자동 경로: `POST /api/paper-trading/start` 후 루프 내부에서 자동 수행
- 수동 경로: `POST /api/order-engine/execute-signal` 호출 시 내부 `RiskRules.approve_order()` 수행
- 확인: 응답 `status=REJECTED_RISK` 또는 `SUBMITTED/FAILED`

## Step 8. KIS mock 주문 호출
- 자동 경로: Step7 자동 경로와 동일
- 수동 경로: `POST /api/order-engine/execute-signal`
- 성공 기준: 응답 `accepted=true` + `order_id` 존재

## Step 9. 주문 상태 추적
- `GET /api/order-engine/tracked`
- 필요 시 `POST /api/order-engine/sync` (미체결/체결 반영)
- 성공 기준: `items`에 내부 주문 상태(created/submitted/filled/...)

## Step 10. 포지션/잔고/손익 반영
- `POST /api/portfolio/sync`
- `GET /api/portfolio/summary`
- 성공 기준: `equity`, `cash`, `positions`, `realized_pnl`, `unrealized_pnl` 갱신

## Step 11. dashboard/performance 반영
- `GET /api/dashboard/summary`
- `GET /api/performance/metrics`
- 성공 기준: dashboard 상태 + performance 지표가 최신 sync 데이터 기반으로 응답

---

## 중간 mock/demo 여부 (명시)

- 완전 실데이터 경로:
  - auth/broker/paper/order tracking/portfolio sync/dashboard 주요 값
- 부분 mock/추정 경로:
  - 국면 입력 일부는 KOSPI 파생 프록시 사용
  - `regime-performance`는 최신 국면 + 손익 결합 추정치

---

## 자동 루프로 한 번에 확인 (선택)

- `POST /api/paper-trading/start` (JWT, strategy_id)
- `GET /api/paper-trading/status`, `/positions`, `/pnl`, `/logs`
- 이후 `POST /api/portfolio/sync` -> `GET /api/dashboard/summary` / `GET /api/performance/metrics`

---

## 빠른 점검 스크립트

```bash
python scripts/check_kis_mock_autotrade_pipeline.py --email you@example.com --password '***' --start-paper
```

