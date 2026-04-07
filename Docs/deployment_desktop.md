# Desktop Deployment Guide

## 대상

- Electron 기반 데스크톱 앱 (`apps/desktop`)
- Windows 설치 파일(NSIS) 빌드 초안

## 사전 준비

- Node.js LTS
- Windows 빌드 환경
- 아이콘 파일
  - `apps/desktop/build/icons/icon.ico`

## 환경 설정

예시 파일:

- `apps/desktop/.env.development.example`
- `apps/desktop/.env.production.example`

주입 변수:

- `APP_ENV`
- `BACKEND_URL`

`build-win` 스크립트는 빌드 전에 `src/runtime-config.js`를 생성하여 URL/환경을 주입합니다.

## 실행/빌드 흐름

1. 개발 실행
   - `cd apps/desktop`
   - `npm install`
   - `npm run dev`
2. 패키지 테스트(설치 파일 없이)
   - `npm run pack`
3. Windows 설치 파일 빌드
   - `npm run build:win`
4. 산출물 확인
   - `apps/desktop/dist`

## 운영 시 주의사항

- 데스크톱 앱에는 비밀정보를 포함하지 않습니다.
- `runtime-config.js`에는 서버 URL 같은 비민감 값만 포함합니다.
- live trading 잠금/해제는 서버 검증을 통과해야만 반영됩니다.
