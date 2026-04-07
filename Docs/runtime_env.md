# Runtime Environment Guide

## 목적

개발/운영 환경에서 앱과 백엔드가 안전하게 설정값을 주입받도록 표준을 정의합니다.

## 원칙

- 비밀정보는 서버 `.env`에만 저장합니다.
- 모바일/데스크톱에는 서버 URL 등 비민감 설정만 주입합니다.
- `LIVE_TRADING=true` 단독으로는 실주문이 허용되지 않습니다.

## 모바일 (`apps/mobile`)

- 설정 파일: `app.config.ts`, `eas.json`
- 환경 변수:
  - `APP_ENV`
  - `EXPO_PUBLIC_BACKEND_URL`
- 주입 위치:
  - `src/config/env.ts` -> `BACKEND_URL`, `APP_ENV`

## 데스크톱 (`apps/desktop`)

- 설정 파일: `package.json`(electron-builder), `scripts/build-win.js`
- 환경 변수:
  - `APP_ENV`
  - `BACKEND_URL`
- 주입 위치:
  - 빌드 시 `scripts/build-win.js`가 `src/runtime-config.js` 생성
  - HTML 화면은 `window.RUNTIME_CONFIG.BACKEND_URL` 사용

## 백엔드 (`backend`)

- `.env` 기반 설정 관리 (`backend/app/core/config.py`)
- live/paper 모드와 안전 플래그를 서버에서 강제

## 개발 vs 운영 차이

- 개발
  - 로컬 서버 URL(`http://localhost:8000`)
  - 디버그/내부 테스트 중심
- 운영
  - HTTPS 서버 URL
  - 앱 서명/배포 스토어 정책 준수
  - 실거래는 다중 안전 조건 충족 시에만 허용
# Runtime Environment Guide

## 목적

개발/운영 환경에서 앱과 백엔드가 안전하게 설정값을 주입받도록 표준을 정의합니다.

## 원칙

- 비밀정보는 서버 `.env`에만 저장합니다.
- 모바일/데스크톱에는 서버 URL 등 비민감 설정만 주입합니다.
- `LIVE_TRADING=true` 단독으로는 실주문이 허용되지 않습니다.

## 모바일 (`apps/mobile`)

- 설정 파일: `app.config.ts`, `eas.json`
- 환경 변수:
  - `APP_ENV`
  - `EXPO_PUBLIC_BACKEND_URL`
- 주입 위치:
  - `src/config/env.ts` -> `BACKEND_URL`, `APP_ENV`

## 데스크톱 (`apps/desktop`)

- 설정 파일: `package.json`(electron-builder), `scripts/build-win.js`
- 환경 변수:
  - `APP_ENV`
  - `BACKEND_URL`
- 주입 위치:
  - 빌드 시 `scripts/build-win.js`가 `src/runtime-config.js` 생성
  - HTML 화면은 `window.RUNTIME_CONFIG.BACKEND_URL` 사용

## 백엔드 (`backend`)

- `.env` 기반 설정 관리 (`backend/app/core/config.py`)
- live/paper 모드와 안전 플래그를 서버에서 강제

## 개발 vs 운영 차이

- 개발
  - 로컬 서버 URL(`http://localhost:8000`)
  - 디버그/내부 테스트 중심
- 운영
  - HTTPS 서버 URL
  - 앱 서명/배포 스토어 정책 준수
  - 실거래는 다중 안전 조건 충족 시에만 허용
