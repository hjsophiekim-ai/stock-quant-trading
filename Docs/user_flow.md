# User Flow

## 문서 목적

설치형 앱 기준 사용자/관리자 화면 흐름을 정의합니다.

## 사용자 로그인 후 화면 흐름

1. 로그인 화면
   - 첫 실행 시 회원가입(Register) 후 로그인
   - 이메일/비밀번호 입력
   - JWT 발급
2. 메인 대시보드
   - 첫 실행 순서 안내 확인
   - 모드/시스템 상태/수익률/리스크 배너 확인
3. 브로커 설정 화면
   - 한투 계정 정보 입력(서버 저장)
   - 연결 테스트 실행
   - 연결 상태(status/message) 확인
4. Paper Trading 화면
   - 전략 선택
   - 시작/중지
   - 포지션/로그/수익률 확인
5. 성과 분석 화면
   - 일/주/월/누적 수익률
   - 실현/미실현, 최대낙폭, 승률, 손익비
   - 종목/전략/국면별 성과

## 관리자 관점 운영 흐름

1. 대시보드/운영 패널 모니터링
2. Live Settings 진입
   - 위험 경고 문구 확인
   - 다중 승인 플래그 검토/변경
   - 변경 이력 기록
3. Runtime Safety Validation 확인
   - 차단 사유(blocker) 해소 여부 점검
4. Kill Switch 상태 확인
   - 손실 제한 초과 시 live 차단 유지
5. 필요 시 live 재잠금/운영 중단

## paper trading vs live trading

- `paper trading`
  - 기본 모드
  - 전략 검증/UX 점검/운영 리허설 목적
  - 실주문 없음
- `live trading`
  - 명시적 다단계 승인 필요
  - 손실 제한/kill switch/승인 조건 불충족 시 즉시 차단
  - 실거래 전 체크리스트 통과가 선행되어야 함

## 모바일/데스크톱 공통 화면 목록

1. 로그인 화면
2. 브로커 설정 화면
3. 연결 테스트 버튼
4. paper trading 시작/중지 화면
5. 대시보드 화면
6. 수익률/포지션/거래내역 화면

## Mock vs 실제 API 구분

- 실제 API 연동 완료
  - Auth (`/api/auth/*`)
  - Broker account CRUD + connection test/status (`/api/broker-accounts/*`)
  - Paper trading start/stop/status/positions/pnl/logs (`/api/paper-trading/*`)
  - Dashboard summary (`/api/dashboard/summary`)
  - Performance metrics/history (`/api/performance/*`)
  - Recent trades (`/api/trading/recent-trades`)
- 현재 mock 성격 데이터 반환(API 내부 TODO)
  - dashboard/performance/paper 일부 응답은 DB 실데이터가 아닌 시뮬레이션 payload

## 정책 고지

- 시스템 목표는 수익률 개선이지만, 최우선 제약은 손실 최소화입니다.
- 월 15%는 연구 목표이며 보장 수익이 아닙니다.
