# Backend Deployment Guide (Cloud)

## 왜 클라우드에 둬야 하나?

- 모바일/데스크톱 앱은 **JWT + REST API** 만 사용하고, 한국투자 API 키·계좌 정보는 모두 **서버에만 암호화 저장**합니다.
- 여러 기기(PC·Android)에서 같은 계정으로 로그인해도, 주문/리스크/손익이 한 곳에서 일관되게 관리됩니다.
- 실거래 잠금, 일별 손실 제한, kill switch 등 안전장치를 **서버에서 강제**해야 실수·오류로 인한 손실을 줄일 수 있습니다.

## 컨테이너 구조

- `backend/Dockerfile` — FastAPI + Uvicorn 컨테이너
- `docker-compose.yml` — 단일 서비스(`backend`) 예시

로컬 테스트용:

```bash
docker compose up --build
```

이후:

- API: `http://localhost:8000/api/...`
- 앱 기본 URL:
  - 데스크톱: `BACKEND_URL=http://<host>:8000`
  - 모바일: `EXPO_PUBLIC_BACKEND_URL=https://api.yourdomain.com` (배포 시)

## 주요 환경 변수 (.env)

백엔드는 `.env` (또는 클라우드 환경 변수)에서 설정을 읽습니다 — **민감 정보는 여기만 사용**합니다.

- 코어
  - `APP_ENV` — `local` / `staging` / `production`
  - `APP_SECRET_KEY` — JWT·암호화용 시크릿 (필수)
- 데이터
  - `DATABASE_URL` — 기본 `sqlite:///./trading.db` (운영에서는 managed DB 권장)
  - `REDIS_URL` — 선택, 큐/캐시 용도
- 한국투자
  - `KIS_APP_KEY`, `KIS_APP_SECRET`
  - `KIS_BASE_URL`, `KIS_MOCK_BASE_URL` — 기본값은 한투 표준 URL
  - `TRADING_MODE` — `paper` / `live` (**기본 paper**)
- live 안전 플래그 (기본 잠금)
  - `LIVE_TRADING=false`
  - `LIVE_TRADING_ENABLED=false`
  - `LIVE_TRADING_CONFIRM=false`
  - `LIVE_TRADING_EXTRA_CONFIRM=false`

실거래를 열려면 위 네 개와 앱 내부 `live-trading` 플래그까지 모두 true 여야 하므로, 기본 배포에서는 **실제 live 주문 경로가 열리지 않습니다.**

## Health / Readiness / Status 엔드포인트

- Health (liveness)
  - `GET /api/health` → `{ "status": "ok", "service": "backend-api" }`
- Readiness
  - `GET /api/ready` → 핵심 설정(APP_SECRET_KEY)·`backend_data` 쓰기 가능 여부
- Runtime status
  - `GET /api/runtime-engine/status` — 전역 엔진 상태
  - `GET /api/paper-trading/status` — 사용자 Paper 세션 상태
  - `GET /api/risk/status` — 리스크 엔진 요약
  - `GET /api/live-trading/status` — live 잠금 플래그/경고 메시지
- Ready 판단 예시
  - health OK
  - DB/환경 점검 스크립트 (`python scripts/check_env.py`, `python scripts/check_runtime_safety.py`) 사전에 통과

Cloud provider에서 **헬스 체크 URL**로 `/api/health` 또는 `/api/ready` 를 사용하고, 대시보드·모니터링에는 `/api/runtime-engine/status`, `/api/paper-trading/status`, `/api/risk/status` 를 참고합니다.

## 클라우드 배포 후보별 개요

아래는 공통 컨셉입니다. 실제 콘솔/CLI는 각 서비스 문서를 참고하세요.

### 1) Render (웹 서비스)

- Dockerfile 기반 Web Service 로 생성
- 환경 변수:
  - `APP_ENV=production`
  - 나머지 `.env` 값들 (KIS 키 포함) Render 환경 변수로 설정
- 포트: 8000 (Render가 자동으로 외부 포트에 매핑)
- 앱에서는:
  - 데스크톱 `BACKEND_URL=https://<your-service>.onrender.com`
  - 모바일 `EXPO_PUBLIC_BACKEND_URL=https://<your-service>.onrender.com`

### 2) Railway / Fly.io / VPS

- 공통:
  - `docker-compose.yml` 참고해서 `backend` 단일 서비스만 옮기면 됩니다.
  - 포트 8000 → 외부 80/443으로 reverse proxy.
- Railway:
  - Dockerfile or Nixpacks로 배포, 환경 변수는 프로젝트 Settings 에서 관리.
- Fly.io:
  - `fly launch` → Dockerfile 사용, `fly secrets` 로 민감값 주입.
- VPS:
  - `docker compose up -d` 또는 `systemd` + `uvicorn` 직접 실행.

## 앱 연결 방식 (모바일 + 데스크톱)

- 데스크톱
  - 빌드 시 `BACKEND_URL=https://api.yourdomain.com` 으로 패키징.
  - 로그인 화면 상단 “서버 연결” 문구는 `GET /api/health` 결과를 보여 줍니다.
- 모바일
  - `app.config.ts` 의 기본 backend URL 을 `https://api.yourdomain.com` 으로 설정.
  - EAS 빌드 시 필요하면 `EXPO_PUBLIC_BACKEND_URL` 로 환경별 URL 분리.
- 둘 다:
  - 로그인 → JWT 발급 (`/api/auth/login`)
  - 브로커 설정 (`/api/broker-accounts/me/*`)
  - Paper 세션 (`/api/paper-trading/*`)
  - 포트폴리오/성과 (`/api/portfolio/*`, `/api/performance/*`, `/api/dashboard/summary`)

## 운영 시 확인 항목

모니터링/점검시 아래를 우선 확인합니다:

- 헬스
  - `/api/health` 200 여부
- Auth/브로커
  - `/api/auth/login`, `/api/auth/me`
  - `/api/broker-accounts/me/status`
- 리스크/런타임
  - `/api/risk/status`
  - `/api/runtime-engine/status`
  - `/api/paper-trading/status`
  - `/api/live-trading/status` (기본은 “LIVE 주문 잠금 상태”여야 안전)
- 엔드투엔드 API 점검
  - `python scripts/check_kis_mock_autotrade_pipeline.py --email <email> --password <pw> --start-paper`
  - 로그인/JWT, 브로커 상태, paper 상태, dashboard/performance/risk를 한 번에 점검

실거래를 열 계획이 없다면:

- 운영 환경 `.env` 에서 `TRADING_MODE=paper` 유지
- `LIVE_TRADING*` 플래그는 모두 false 로 유지
- live 관련 앱 화면은 “잠금 상태 / 연구용” 정도 표시만 유지

## 현재 TODO (실데이터 고도화)

- 스크리너/신호 엔진의 국면 입력 중 일부는 KOSPI 기반 파생 시계열(프록시)을 사용합니다.
  - 외부 지수 실데이터 소스 연동은 후속 TODO입니다.
- `performance/regime-performance` 는 최신 국면 + 동기화 손익 결합 추정치입니다.
  - 장기 국면별 성과 누적 시계열 저장은 후속 TODO입니다.

