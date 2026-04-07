# Stock Quant Trading Platform (Monorepo)

설치형 자동매매 플랫폼 구조로 확장한 모노레포입니다.  
핵심 목표는 **수익률 개선**이지만, 시스템 최우선 제약은 **손실 최소화**입니다.
또한 **월 15%는 연구용 목표이며, 보장 수익이 아닙니다.**

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

### 왜 앱에서 직접 한투 API를 호출하지 않나요?

- 앱 바이너리는 역분석/탈취 위험이 있어 API 키 보호가 어렵습니다.
- 사용자 기기마다 네트워크/보안 상태가 달라 감사 추적 일관성이 떨어집니다.
- 주문 전 리스크 검증(손절, 일일/총손실 제한, kill switch)을 서버에서 강제해야 안전합니다.

### 왜 서버 저장/암호화 구조가 필요한가요?

- 사용자별 브로커 계정을 분리 저장해 다중 사용자 운영을 지원합니다.
- 계정 정보는 서버에서 암호화 저장하여 유출 위험을 낮춥니다.
- 토큰 발급/연결 테스트를 서버에서만 수행해 민감정보 노출 경로를 줄입니다.

## 브로커 계정 관리

- 사용자는 앱의 Broker Settings 화면에서 KIS 연동 정보를 입력/수정합니다.
- 서버는 사용자별 브로커 계정을 암호화 저장하고 CRUD를 제공합니다.
- 앱에서 "토큰 발급 테스트"를 실행하면 서버가 한국투자 토큰 API를 호출해 연결 상태를 갱신합니다.

## 설치형 앱 운영 흐름 (요약)

- 사용자 흐름: 로그인 -> 대시보드 -> 브로커 설정/모의투자 -> 성과 확인
- 관리자 흐름: 상태 모니터링 -> live 잠금 정책 점검 -> 위험 경고 대응 -> 필요 시 중단
- 모드 정책:
  - `paper trading`: 기본 모드, 실행/검증/학습용
  - `live trading`: 명시적 다중 승인 전까지 잠금

## 앱 첫 실행 (초보자)

모바일/데스크톱 공통으로 아래 순서대로 진행하면 바로 확인 가능합니다.

1. Login 화면에서 `Register (First Run)`으로 계정 생성
2. Login 성공 후 Dashboard 진입
3. Broker Settings에서 KIS 정보 저장
4. `Test Token Issuance` 버튼으로 연결 테스트
5. Paper Trading 화면에서 Start/Stop 동작 확인
6. Performance 화면에서 수익률/포지션/거래내역 확인

화면 목록:
- 로그인
- 브로커 설정
- 연결 테스트
- paper trading 시작/중지
- 대시보드
- 성과(수익률/포지션/거래내역)

Mock/실제 연동 구분:
- 실제 API 호출: auth, broker CRUD/test/status, paper start/stop/status, dashboard/performance 조회
- 현재 mock 성격: 일부 dashboard/performance/paper API 응답은 DB 실데이터가 아닌 시뮬레이션 payload

## 주요 문서

- `docs/system_design.md` : 전체 시스템 설계(앱+서버+트레이딩 코어)
- `docs/app_architecture.md` : 앱/서버/공유모듈 아키텍처 상세
- `docs/trading_rules.md` : 전략/리스크/국면별 운영 규칙
- `docs/live_trading_checklist.md` : 실거래 전 필수 체크리스트
- `docs/backtest_method.md` : 과최적화 방지 검증 방법론
- `docs/deployment_mobile.md` : 모바일 빌드/배포 가이드
- `docs/deployment_desktop.md` : 데스크톱(Windows) 빌드/배포 가이드
- `docs/runtime_env.md` : 환경별 설정 주입/보안 원칙

## 한국투자 API 연동 순서

1. 토큰 발급
2. 조회 API 검증
3. 모의주문 검증
4. 실거래 전환(잠금 해제 조건 충족 시)

## 초보자용 빠른 시작

아래 순서대로 진행하면 clone 후 바로 실행할 수 있습니다.

1) 저장소 클론 후 루트 이동

- `git clone <repo-url>`
- `cd "Stock quant trading"`

2) Python 의존성 설치

- `python -m pip install -e .`

3) 환경/안전 점검

- `python scripts/check_env.py`
- `python scripts/check_runtime_safety.py`

4) 백엔드 실행

- Windows: `scripts\run_backend.bat`
- macOS/Linux: `bash scripts/run_backend.sh`
- 직접 실행: `python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload`

5) 모바일 실행 (선택)

- `scripts\run_mobile.bat`

6) 데스크톱 실행 (선택)

- `scripts\run_desktop.bat`

### 문제 해결 빠른 체크

- `python scripts/check_env.py`에서 blocker가 없어야 합니다.
- 백엔드 접속 확인: `http://127.0.0.1:8000/`
- 실거래 모드는 기본 잠금이며, 다중 확인 플래그 없이는 live 주문이 차단됩니다.

## 한국투자 API 연결 테스트

`.env` 설정 후 아래 순서로 점검합니다.

1) 토큰/계좌 연결 점검

- `python scripts/check_kis_connection.py`

2) 시세 조회 점검

- `python scripts/check_kis_quotes.py`

3) 백엔드 API 점검 (서버 실행 후)

- 사용자 저장 계정 테스트: `POST /api/broker-accounts/me/test-connection`
- 현재 저장 상태 조회: `GET /api/broker-accounts/me/status`
- 런타임(.env) 테스트: `POST /api/broker-accounts/runtime/test-connection`

실패 메시지는 원인별로 구분됩니다.
- 앱키/시크릿 누락
- 계좌번호 형식 오류
- base url 오류
- 토큰 발급 실패/조회 API 실패

## Windows 데스크톱 빌드 요약

Electron 앱을 Windows 설치파일로 만들려면:

1. `cd apps/desktop`
2. `npm install`
3. `npm run build:win:local`  
   (또는 `APP_ENV`, `BACKEND_URL` 지정 후 `npm run build:win`)
4. 결과물 확인: `apps/desktop/dist/*.exe`

Backend URL 주입 방식:
- 빌드 시 `scripts/build-win.js`가 `src/runtime-config.js`를 생성하고
- 앱은 `window.RUNTIME_CONFIG.BACKEND_URL`로 백엔드를 찾습니다.
