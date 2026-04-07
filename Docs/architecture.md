# 아키텍처 문서 (Architecture)

## 문서 목적

이 문서는 코드 구조를 어떻게 나눌지 정의합니다.  
핵심은 "역할 분리"와 "안전장치 우선"입니다.

## 권장 디렉터리 구조(예시)

```text
src/
  config/
  data/
  strategy/
  risk/
  execution/
  portfolio/
  monitoring/
  app/
tests/
docs/
```

## 모듈 책임

- `config`: 환경변수, 모드(`paper`/`live`), 리스크 한도
- `data`: 종목/시세 조회, 데이터 정합성 검증
- `strategy`: 우량주 필터, 추세 필터, 분할 진입/청산 계산
- `risk`: 손절, 일일 손실 제한, 총 손실 제한 검증
- `execution`: 주문 생성/전송, 모의/실거래 라우팅
- `portfolio`: 포지션/평가손익/누적손실 관리
- `monitoring`: 로그, 경고, 거래중지 이벤트 처리
- `app`: 실행 진입점, 스케줄링, 오케스트레이션

## 시장 국면 모듈 (Market Regime)

- 파일: `app/strategy/market_regime.py`
- 역할: 코스피/S&P500/변동성 데이터를 이용해 시장 상태를 4가지로 분류
  - `bullish_trend`
  - `bearish_trend`
  - `sideways`
  - `high_volatility_risk`
- 설계 원칙:
  - 순수 함수 중심(입력 DataFrame -> 결과 dataclass)
  - 판별 기준은 `MarketRegimeConfig`로 분리
  - 국면별 허용 행동은 `REGIME_ACTIONS` 매핑으로 분리

## 랭킹 엔진 (Ranking Engine)

- 파일: `app/strategy/ranking.py`
- 목적: 조건 통과 후보가 많을 때 기대값이 높은 종목을 우선 진입
- 점수 요소:
  - 상대강도(`relative_strength`)
  - 이동평균 정배열 강도(`ma_alignment`)
  - 거래량 증가율(`volume_growth`)
  - 변동성 품질(`volatility_quality`)
  - 시장 국면 적합성(`regime_fit`)
- 동작:
  - 후보군 점수 계산 후 최종 점수로 정렬
  - 상위 N개만 전략 엔진으로 전달
  - 점수/근거를 로그와 리포트에 기록
- 기본 가중치(`RankingWeights`):
  - `relative_strength`: 0.30
  - `ma_alignment`: 0.25
  - `volume_growth`: 0.15
  - `volatility_quality`: 0.15
  - `regime_fit`: 0.15
- 국면별 의도:
  - 상승장: `relative_strength`, `ma_alignment` 점수가 높은 종목 우선
  - 하락장: `regime_fit`에서 저변동/방어 성향 가점을 부여해 제한적 진입
  - 고변동성 위험장: 랭킹은 계산하되 리스크 엔진에서 신규 진입 차단

## 전략-국면 연결 방식

- 전략 엔진은 먼저 시장 국면을 판별한 뒤 허용 행동을 확인
- 국면별 정책 예시:
  - 상승장: 추세추종 진입 적극 허용
  - 하락장: 소규모 역추세 진입만 제한 허용, 손절 강화
  - 횡보장: 신규 진입 빈도 축소, 보수적 관리
  - 고변동성 위험: 신규 매수 차단, 리스크 축소 중심

## 동적 포지션 사이징 흐름

- 파일: `app/risk/position_sizing.py`
- 입력:
  - 시장 국면(`bullish_trend`, `bearish_trend`, `sideways`, `high_volatility_risk`)
  - 종목 변동성(ATR%)
  - 전략 신뢰도 점수(0~1)
  - 최근 전략 성과
  - 계좌 손익 상태(일일/누적)
  - 계좌 변동성(%)
  - 연속 손실 횟수
- 계산:
  - 1) 총 손실 제한 우선 확인(초과 시 신규 진입 0 강제)
  - 2) 국면별 기본 비중 프로파일(`RegimeSizingConfig`) 선택
  - 3) 멀티플라이어 계산
    - 국면 멀티플라이어
    - ATR 변동성 멀티플라이어
    - 전략 신뢰도 멀티플라이어
    - 최근 성과 멀티플라이어
    - 계좌 손익 상태 멀티플라이어
    - 연속 손실 디레버리징 멀티플라이어
    - 계좌 변동성 타깃 밴드 멀티플라이어
  - 4) 목표 비중 계산 후 국면별 최대 비중으로 상한 처리
  - 5) 추가 진입 허용 여부(국면별 엔트리 캡) 판정
  - 6) 기존 보유 비중 여유를 반영해 최종 주문 수량 계산
- 출력:
  - 권장 주문 수량
  - 최대 허용 비중
  - 추가 진입 허용 여부

## 핵심 의존 방향

- `strategy`는 신호를 만들지만 주문 권한은 없음
- `risk`가 최종 승인권을 가짐
- `execution`은 `risk` 승인 없이는 절대 주문하지 않음

## 상태 관리 포인트

- 계좌 상태: 현금, 보유 수량, 평균단가
- 리스크 상태: 당일 손익, 누적 손익, 거래 가능 여부
- 시스템 상태: API 연결, 최근 오류, 마지막 체결 시각

## 실거래 잠금 설계

- 설정값 `LIVE_TRADING_ENABLED=false` 기본값 고정
- 실거래 함수 진입 전 이중 체크(설정 + 런타임 가드)
- 잠금 해제 시에도 주문 금액 상한을 강제

## 앱 사용자 인증 구조

- 백엔드 파일:
  - `backend/app/models/user.py`: 사용자/토큰 스키마, 역할(`admin`/`user`), 사용자별 설정/브로커 계정 필드
  - `backend/app/auth/jwt_service.py`: access/refresh JWT 발급 및 검증
  - `backend/app/auth/user_auth.py`: 회원가입, 로그인, 토큰 갱신, 로그아웃, 현재 사용자 조회 서비스
  - `backend/app/api/auth_routes.py`: 인증 REST API 라우트
- 앱 파일:
  - `apps/mobile/src/store/authStore.ts`: 인증 상태 store
  - `apps/mobile/src/screens/LoginScreen.tsx`, `DashboardScreen.tsx`: 로그인/대시보드 화면
  - `apps/desktop/src/login.html`, `dashboard.html`: 데스크톱 로그인/대시보드 화면
- 보안 원칙:
  - 비밀번호는 해시만 저장(평문 저장 금지)
  - refresh 토큰은 회전(rotating)하며 로그아웃 시 폐기 처리
  - 민감 정보(비밀번호, 토큰 원문)는 로그에 출력하지 않음

## 브로커 계정(한투) 설정 구조

- 백엔드 파일:
  - `backend/app/models/broker_account.py`: 브로커 계정 입력/응답 모델
  - `backend/app/services/broker_secret_service.py`: 암호화 저장, 사용자별 CRUD, 연결 테스트
  - `backend/app/api/broker_routes.py`: 브로커 계정 API 엔드포인트
- 앱 파일:
  - `apps/mobile/src/screens/BrokerSettingsScreen.tsx`
  - `apps/desktop/src/broker-settings.html`
- 핵심 원칙:
  - 앱은 입력값을 장기 저장하지 않고 서버 API로 전달
  - 서버 DB에는 암호화된 값만 저장
  - 서버만 실제 한국투자 토큰 발급 API를 호출
  - 화면에는 연결 상태(`unknown/success/failed`)를 배지로 표시
