# App Architecture

## 개요

플랫폼은 `mobile`, `desktop`, `backend`, `shared`의 4계층으로 구성됩니다.

- 앱 계층: UX, 인증 세션, API 호출
- 서버 계층: 인증/권한, 브로커 연동, 전략/리스크 실행
- 공유 계층: 타입/모델 동기화
- 트레이딩 코어: 전략/리스크/주문 실행 로직

## 1) Mobile (Expo React Native)

- 역할
  - 사용자 로그인
  - 자산/손익/거래내역 조회
  - 주문 요청 전송
- 보안
  - 브로커 비밀정보 저장 금지
  - JWT 토큰 기반 API 접근

## 2) Desktop (Electron)

- 역할
  - 운영 대시보드
  - 실시간 상태/리스크 이벤트 모니터링
  - 운영자 수동 제어(중단/재개/점검)
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

## 모드 정책

- 기본: `paper trading`
- `live trading`:
  - `TRADING_MODE=live`
  - `LIVE_TRADING=true`
  - `LIVE_TRADING_CONFIRM=true`
  - 계좌 정보 유효성 검증
  - 위 조건 중 하나라도 실패 시 주문 차단
