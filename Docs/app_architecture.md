# App Architecture

## 개요

플랫폼은 `mobile`, `desktop`, `backend`, `shared`의 4계층으로 구성됩니다.
성과 목표는 존재하지만, **월 15%는 연구 목표이며 보장 수익이 아닙니다.**

- 앱 계층: UX, 인증 세션, API 호출
- 서버 계층: 인증/권한, 브로커 연동, 전략/리스크 실행
- 공유 계층: 타입/모델 동기화
- 트레이딩 코어: 전략/리스크/주문 실행 로직

## 1) Mobile (Expo React Native)

- 역할
  - 사용자 로그인
  - 자산/손익/거래내역 조회
  - 주문 요청 전송
  - 모의투자 실행/중지/모니터링
- 보안
  - 브로커 비밀정보 저장 금지
  - JWT 토큰 기반 API 접근

## 2) Desktop (Electron)

- 역할
  - 운영 대시보드
  - 실시간 상태/리스크 이벤트 모니터링
  - 운영자 수동 제어(중단/재개/점검)
  - 관리자용 live safety 설정/이력 확인
- 보안
  - 앱 내부에 브로커 키 저장 금지
  - 서버 권한 기반 제어

## 3) Backend (FastAPI)

- 핵심 기능
  - 사용자 인증(JWT)
  - 한국투자 API 계정 관리
  - 모의투자/실거래 모드 관리
  - 전략 엔진 + 리스크 엔진 + 주문 엔진 오케스트레이션
  - 포트폴리오/성과 API 제공
- 보안
  - 브로커 키/시크릿 암호화 저장
  - 실거래 다중 안전 플래그 확인
  - 손실 제한 초과 시 자동 종료 경로

## 4) Shared

- 공통 타입(`shared/types`)
- 공통 API 모델(`shared/api-models`)
- 성과 분석 모델(`shared/models/performance.ts`)
- 공통 유틸(`shared/utils`)

## 앱/서버 데이터 흐름

1. 앱 로그인 -> JWT 발급
2. 앱이 JWT로 백엔드 API 호출
3. 백엔드가 사용자 권한 확인 후 요청 처리
4. 트레이딩 요청 시:
   - 시장 데이터 조회
   - 시장 국면 인식
   - 후보 랭킹
   - 전략 신호 생성
   - 리스크 승인
   - 브로커 실행(기본 paper)
5. 결과를 DB 저장 후 앱에 응답

## 왜 앱에서 직접 한투 API를 호출하지 않는가

- 앱 배포물은 키 유출 위험이 높아 민감정보 보관 위치로 부적합합니다.
- 서버 경유 구조여야 사용자/관리자 권한, 주문 차단, 리스크 가드를 일괄 적용할 수 있습니다.
- 감사 로그와 운영 이력을 서버에서 일관되게 남길 수 있습니다.

## 왜 서버 암호화 저장이 필요한가

- 사용자별 브로커 계정을 분리하고, 평문 저장 없이 암호화 저장이 가능합니다.
- 토큰 발급/연결 테스트/주문 허용 여부 판단을 서버 단에서 통합 수행할 수 있습니다.
- 보안 사고 발생 시 회전/폐기/차단 절차를 중앙에서 수행할 수 있습니다.

## 모드 정책

- 기본: `paper trading`
- `live trading`:
  - `TRADING_MODE=live`
  - `LIVE_TRADING=true`
  - `LIVE_TRADING_CONFIRM=true`
  - 앱 다중 승인 플래그(secondary/extra) 충족
  - 계좌 정보 유효성 검증
  - 위 조건 중 하나라도 실패 시 주문 차단

## 성과 분석 화면/데이터 구조

- Mobile (`apps/mobile`)
  - 카드형 KPI(일/주/월/누적 수익률, 실현/미실현, MDD, 승률, 손익비)
  - mock 차트 + 종목/전략/국면 리스트
  - `Perf` 탭에서 조회
- Desktop (`apps/desktop`)
  - 성과 분석 전용 화면(`performance.html`)
  - 날짜/전략/종목 필터 제공
  - KPI + 차트 + 종목/전략/국면/거래 테이블
- Backend (`backend`)
  - `GET /api/performance/metrics`
  - `GET /api/performance/pnl-history`
  - `GET /api/performance/trade-history`
  - `GET /api/performance/symbol-performance`
  - `GET /api/performance/strategy-performance`
  - `GET /api/performance/regime-performance`
  - 현재는 mock 응답이며, 이후 DB/백테스트 집계로 전환
