# Stock Quant Trading Platform (Monorepo)

설치형 자동매매 플랫폼 구조로 확장한 모노레포입니다.  
핵심 목표는 **수익률 개선**이지만, 시스템 최우선 제약은 **손실 최소화**입니다.

## 플랫폼 구성

- `backend/` : FastAPI 기반 API 서버
- `apps/mobile/` : Expo React Native 모바일 앱
- `apps/desktop/` : Electron 데스크톱 앱
- `shared/` : 공통 타입/공통 API 모델/공통 유틸
- `app/` : 기존 트레이딩 코어 엔진(전략/리스크/브로커)  
  - 점진적으로 `backend` 서비스 계층으로 통합 예정

## 보안 원칙

- 한국투자 App Key/Secret를 모바일/데스크톱 앱에 저장하지 않습니다.
- 브로커 비밀정보는 서버에서 암호화 저장합니다.
- 앱은 자체 로그인(JWT) 후 서버를 통해서만 한국투자 API에 접근합니다.
- 기본값은 `paper trading`
- `live trading`은 잠금 상태이며 다중 확인 플래그 없이는 주문 불가

## 브로커 계정 관리

- 사용자는 앱의 Broker Settings 화면에서 KIS 연동 정보를 입력/수정합니다.
- 서버는 사용자별 브로커 계정을 암호화 저장하고 CRUD를 제공합니다.
- 앱에서 "토큰 발급 테스트"를 실행하면 서버가 한국투자 토큰 API를 호출해 연결 상태를 갱신합니다.

## 주요 문서

- `docs/system_design.md` : 전체 시스템 설계(앱+서버+트레이딩 코어)
- `docs/app_architecture.md` : 앱/서버/공유모듈 아키텍처 상세
- `docs/trading_rules.md` : 전략/리스크/국면별 운영 규칙
- `docs/live_trading_checklist.md` : 실거래 전 필수 체크리스트
- `docs/backtest_method.md` : 과최적화 방지 검증 방법론

## 한국투자 API 연동 순서

1. 토큰 발급
2. 조회 API 검증
3. 모의주문 검증
4. 실거래 전환(잠금 해제 조건 충족 시)
