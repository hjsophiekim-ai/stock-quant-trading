# System Design

## 1) 문서 목적

본 문서는 프로젝트를 설치형 플랫폼으로 확장한 전체 시스템 구조를 정의합니다.  
핵심은 **앱(모바일/데스크톱) + 백엔드 API + 트레이딩 코어**를 분리하고, 보안/리스크 통제를 서버 중심으로 강제하는 것입니다.
수익 목표는 존재하지만, **월 15%는 연구 목표일 뿐 보장 수익이 아닙니다.**

## 2) 상위 아키텍처

- `apps/mobile` (Expo React Native)
  - 사용자 인증
  - 포트폴리오/손익/거래내역 조회
  - 주문 요청(서버 경유)
- `apps/desktop` (Electron)
  - 운영 콘솔(상태 모니터링, 리스크 이벤트, 수동 제어)
  - 백엔드 API 대시보드
- `backend` (FastAPI)
  - JWT 인증
  - 한국투자 API 연동 중계
  - 모의투자/실거래 모드 관리
  - 리스크 엔진/전략 엔진 실행 오케스트레이션
- `shared`
  - 앱/서버 공통 타입, API 모델, 유틸
- `app` (기존 코어 엔진)
  - 전략/리스크/브로커/백테스트 로직
  - 단계적으로 `backend/app/services`로 통합 예정

## 3) 보안 설계 원칙

- 한국투자 App Key/Secret는 앱에 저장하지 않습니다.
- 브로커 비밀정보는 서버에서 암호화 저장합니다.
- 앱은 자체 로그인(JWT) 후 서버 API를 통해서만 브로커 접근합니다.
- 기본값은 `paper trading`입니다.
- `live trading`은 잠금 상태이며, 다중 확인 플래그가 없으면 실주문을 차단합니다.

### 3-1) 앱 직접 호출 금지 이유

- 모바일/데스크톱 앱은 키 노출 공격면이 커서 브로커 비밀 보호에 불리합니다.
- 리스크 엔진/kill switch를 우회한 주문 경로가 생기면 손실 통제가 무너질 수 있습니다.
- 서버 단일 진입점으로 감사 로그, 접근 통제, 오류 대응을 일관되게 유지할 수 있습니다.

### 3-2) 서버 암호화 저장 이유

- 사용자별 계정 분리 저장이 가능해 다중 사용자 운영에 적합합니다.
- 키/계좌정보를 암호화하여 저장해 평문 노출 위험을 낮춥니다.
- 토큰 발급, 연결 검증, 주문 가능 여부 검증을 서버에서만 실행할 수 있습니다.

## 4) 트레이딩 실행 흐름

1. 앱 로그인(JWT 발급)
2. 앱이 백엔드에 전략 실행/조회 요청
3. 백엔드가 시장 데이터 수집
4. 시장 국면 인식 엔진 실행
   - 입력: 코스피, S&P500, MA20/60/120 방향, 최근 수익률, ATR/변동성 지표
   - 출력: `bullish_trend` | `bearish_trend` | `sideways` | `high_volatility_risk`
5. 후보 필터 + ranking engine으로 상위 종목 선정
6. 전략 신호 생성
7. 리스크 엔진 승인(손절/손실제한/cooldown/rolling loss)
8. 브로커 라우팅
   - 기본: paper
   - live: 이중 확인 플래그 + 모드 검증 통과 시에만
9. 체결/포지션/손익 저장 및 API 응답

## 4-1) 사용자/관리자 운영 관점

- 사용자 관점:
  1. 로그인
  2. 대시보드/성과 확인
  3. 브로커 설정(서버 저장)
  4. paper trading 실행/중지/모니터링
- 관리자 관점:
  1. 런타임 상태/리스크 경고 확인
  2. live 잠금 해제 조건 점검
  3. 손실 제한 초과 시 즉시 중단/복구 절차 수행

## 5) 장애/안전 중단 경로

- 일일 손실 제한 초과 -> 당일 거래 중단
- 총 손실 제한 초과 -> 시스템 자동 shutdown 경로
- rolling loss limit 초과 -> cooldown 전환
- API 장애/응답 이상 -> 신규 주문 차단
- high volatility risk -> 신규 진입 차단, 포지션 관리만 허용

## 5-1) 시장 국면별 전략 라우팅

- `bullish_trend`
  - 공격적 추세 전략 허용
  - 분할 진입 허용(리스크 한도 내)
- `bearish_trend`
  - 손실 최소화 우선
  - 소규모 평균회귀형 대응만 제한 허용
  - 신규 진입 종목 수 축소, 종목당 최대 비중 축소
  - 손절폭 상한 축소, 보유기간 단축, 진입 신호 임계값 강화
- `sideways`
  - 평균회귀형 대응만 제한 허용
  - 신규 진입 규모/빈도 축소
- `high_volatility_risk`
  - 신규 진입 차단
  - 기존 포지션 축소/정리 목적 주문만 허용

## 5-2) 리스크 엔진 국면별 승인 코드

- `bearish_trend` 신규 매수 차단 사유
  - `BLOCK_REGIME_BEARISH_NEW_ENTRY_LIMIT`
  - `BLOCK_REGIME_BEARISH_MAX_POSITIONS`
  - `BLOCK_REGIME_BEARISH_POSITION_WEIGHT`
  - `BLOCK_REGIME_BEARISH_STOP_LOSS_TOO_WIDE`
- `bearish_trend` 제한 승인
  - `OK_REGIME_BEARISH_BUY_CONSERVATIVE`
- `high_volatility_risk`
  - 신규 매수 차단: `BLOCK_REGIME_HIGH_VOLATILITY_NEW_ENTRY`
  - 포지션 축소 매도 허용: `OK_SELL`

## 5-3) 손실 적응 방어 로직

- 최근 N회 거래 손익(`recent_trade_pnls`)과 연속 손실(`consecutive_losses`)을 지속 추적
- rolling loss limit 도입
  - 최근 `rolling_loss_window_trades` 기준 손익률이 `rolling_loss_limit_pct` 이하이면 신규 진입 중단
- adaptive defense 트리거
  - 연속 손실이 `adaptive_loss_streak_threshold` 이상이거나
  - rolling 손익이 `adaptive_performance_floor_pct` 이하
- adaptive defense 동작
  - 신규 진입 수 축소(`adaptive_new_entries_limit`)
  - 포지션 허용 비중 축소(`adaptive_position_weight_multiplier`)
  - 손절 허용폭 축소(`adaptive_stop_loss_tighten_multiplier`)
  - 진입 조건 강화(`adaptive_min_entry_score`)
  - 조건 악화 지속 시 거래 쿨다운(`adaptive_trading_cooldown_minutes`)
- kill switch 연동
  - global hard-stop(일일/총손실) 우선
  - adaptive 상태가 악화되면 `COOLDOWN` 전환 추천

## 6) 데이터 조회 기능(플랫폼 제공)

- 수익률 조회(일/월/누적)
- 손익 조회(실현/미실현)
- 포트폴리오 조회(보유/평가금액/비중)
- 거래내역 조회(주문/체결/리스크 이벤트)

## 7) Paper Trading 운영 API

- 목적: 앱에서 모의투자 실행/중지/상태 모니터링을 안전하게 수행
- 엔드포인트:
  - `POST /api/paper-trading/start`
  - `POST /api/paper-trading/stop`
  - `GET /api/paper-trading/status`
  - `GET /api/paper-trading/positions`
  - `GET /api/paper-trading/pnl`
  - `GET /api/paper-trading/logs`
- 원칙:
  - 항상 `paper` 모드로만 동작
  - `live` 경로와 완전 분리
  - 내부 브로커는 `PaperBroker` 사용
  - 앱은 모니터링/제어만 수행하고 실주문 경로는 노출하지 않음

## 8) Live Trading 다단계 안전장치

- 잠금 기본값: 항상 live 잠금 상태
- 해제 조건(모두 충족 필요):
  - ENV `LIVE_TRADING=true`
  - ENV `LIVE_TRADING_CONFIRM=true`
  - 앱 `live_trading_flag=true`
  - 앱 `secondary_confirm_flag=true`
  - 앱 `extra_approval_flag=true`
  - `TRADING_MODE=live`
- 제공 API:
  - `GET /api/live-trading/status`
  - `POST /api/live-trading/settings`
  - `GET /api/live-trading/settings-history`
  - `GET /api/live-trading/runtime-safety-validation`
  - `GET /api/live-trading/kill-switch-status`
- 계좌 손실 제한 초과 시:
  - 앱에 즉시 경고 배너 표시
  - live 주문 차단 상태 유지

## 9) 확장 계획

- 모바일 푸시 알림(리스크 이벤트, 체결 알림)
- 데스크톱 운영 자동화(스케줄/복구)
- 멀티 브로커 계정 지원
- 멀티 전략 포트폴리오 운영
