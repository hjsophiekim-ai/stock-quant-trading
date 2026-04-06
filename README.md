# Stock Quant Trading

초보자도 따라올 수 있도록 설계한 **안전 우선형 퀀트 트레이딩 프로젝트**입니다.

## 프로젝트 한 줄 목표

**수익률 극대화를 추구하되 손실 최소화를 최우선 제약으로 둔다.**

## 핵심 전략

- 우량주 스윙: 재무/유동성이 안정적인 종목 위주로 중기 스윙
- 추세 필터: 상승 추세일 때만 진입하고, 약세 구간은 관망
- 분할매매: 한 번에 몰빵하지 않고 나눠서 진입/청산

## 안전 원칙

- 기본 운용 환경은 **모의투자**입니다.
- **실거래는 잠금(기본 비활성화)** 상태를 유지합니다.
- 리스크 엔진이 아래 규칙을 강제합니다.
  - 종목별 손절(Stop Loss)
  - 일일 손실 제한(Daily Loss Limit)
  - 총 손실 제한(Max Drawdown / Total Loss Limit)

## 문서 안내

- `docs/system_design.md`: 시스템 전체 구성과 데이터 흐름
- `docs/architecture.md`: 모듈 구조와 책임 분리
- `docs/trading_rules.md`: 전략/진입/청산/리스크 규칙
- `docs/api_plan.md`: 한국투자증권 연동 단계별 API 계획
- `docs/paper_trading_flow.md`: 모의투자 실행 시나리오
- `AGENTS.md`: 개발 에이전트/작업 규칙

## 한국투자증권 연동 로드맵(순서 고정)

1. 토큰 발급
2. 조회 API
3. 모의주문
4. 실거래(잠금 해제 조건 충족 시)

## 현재 연동 상태 (실제 API 준비)

- `app/auth/kis_auth.py`
  - `/oauth2/tokenP` 기반 토큰 발급/캐시/만료 체크/리프레시 흐름 구현
- `app/clients/kis_client.py`
  - 공통 GET/POST 래퍼 + 헤더 + Bearer 토큰 연동 + retry/timeout 처리
  - 조회 API 우선 구현: 잔고 조회, 현재가 조회, 보유종목 조회(잔고 API 기반)
- 실거래 잠금
  - `LIVE_TRADING=true`가 아니면 실주문 금지 정책 유지

## 빠른 점검 순서

1. `.env`에 KIS 키/계좌 정보 입력
2. `scripts/check_kis_connection.py` 실행
3. `scripts/check_kis_quotes.py` 실행
4. 조회 응답 필드 확인 후 전략/리스크 입력 매핑
