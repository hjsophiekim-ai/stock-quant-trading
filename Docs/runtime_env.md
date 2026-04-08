# Runtime Environment Guide

## 목적

개발/운영 환경에서 앱과 백엔드가 안전하게 설정값을 주입받도록 표준을 정의합니다.

## 공통 원칙

- 비밀정보는 **서버 환경변수**에서만 관리합니다.
- 모바일/데스크톱에는 서버 URL 등 비민감값만 주입합니다.
- `LIVE_TRADING=true` 단독으로는 실주문이 열리지 않습니다.

## 모바일 (`apps/mobile`)

- 설정 파일: `app.config.ts`, `eas.json`
- 환경 변수:
  - `APP_ENV`
  - `EXPO_PUBLIC_BACKEND_URL`
- 주입 위치:
  - `src/config/env.ts` -> `BACKEND_URL`, `APP_ENV`
- 운영 권장:
  - production 빌드 기본 URL을 클라우드 backend로 고정
  - 사용자가 localhost 입력하지 않도록 구성

## 데스크톱 (`apps/desktop`)

- 설정 파일: `package.json`(electron-builder), `scripts/build-win.js`
- 환경 변수:
  - `APP_ENV`
  - `BACKEND_URL`
- 주입 위치:
  - 빌드 시 `scripts/build-win.js`가 `src/runtime-config.js`에 주입
  - 실행 시 HTML이 `window.RUNTIME_CONFIG.BACKEND_URL` 사용
- 운영 권장:
  - 설치파일 생성 시 클라우드 URL 고정 주입

## 백엔드 (`backend`)

- 설정 소스: `.env` 또는 클라우드 환경 변수
- 로딩 코드: `backend/app/core/config.py` (`BackendSettings`)
- 핵심 변수:
  - `APP_ENV` (`local` / `staging` / `production`)
  - `APP_SECRET_KEY` (필수)
  - `DATABASE_URL`, `REDIS_URL`
  - `KIS_APP_KEY`, `KIS_APP_SECRET`
  - `TRADING_MODE` (기본 `paper`)
  - `LIVE_TRADING`, `LIVE_TRADING_ENABLED`, `LIVE_TRADING_CONFIRM`, `LIVE_TRADING_EXTRA_CONFIRM`

### live 주문이 열리는 조건

아래가 모두 true일 때만 live 주문 가능:

1. `TRADING_MODE=live`
2. `LIVE_TRADING=true`
3. `LIVE_TRADING_ENABLED=true`
4. `LIVE_TRADING_CONFIRM=true`
5. `LIVE_TRADING_EXTRA_CONFIRM=true`
6. 앱 내부 live 승인 플래그

즉, 운영 기본값(모두 false)에서는 live가 잠금 상태입니다.

## 개발 vs 운영

- 개발
  - 로컬 URL: `http://127.0.0.1:8000`
  - 스크립트 실행(`scripts/run_backend.*`) 또는 docker compose
  - 테스트/디버그 중심
- 운영(클라우드)
  - HTTPS URL: `https://api.yourdomain.com`
  - Docker + PaaS(Render/Railway/Fly.io/VPS) 배포
  - 환경 변수는 클라우드 콘솔에서 관리
  - 앱은 동일한 backend URL을 사용
