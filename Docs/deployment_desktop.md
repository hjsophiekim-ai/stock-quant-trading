# Desktop Deployment Guide

## 대상

- Electron 기반 데스크톱 앱 (`apps/desktop`)
- Windows 설치파일(NSIS `.exe`) 빌드

## 초보자용 빠른 빌드

1. 사전 준비
   - Windows 10/11
   - Node.js LTS 설치
   - PowerShell 또는 CMD
2. 의존성 설치
   - `cd apps/desktop`
   - `npm install`
3. 설치파일 빌드
   - 로컬 백엔드 기준: `npm run build:win:local`
   - 사용자 지정 백엔드:  
     - PowerShell:
       - `$env:APP_ENV="production"`
       - `$env:BACKEND_URL="http://127.0.0.1:8000"`
       - `npm run build:win`
4. 산출물 확인
   - `apps/desktop/dist/*.exe`

## 빌드 리소스 구조

- 아이콘 경로: `apps/desktop/build/icons/icon.ico`
- `scripts/build-win.js`가 빌드 전 다음을 수행:
  - `src/runtime-config.js` 생성 (`BACKEND_URL`, `APP_ENV` 주입)
  - 아이콘이 없으면 placeholder `icon.ico` 자동 생성

## 설치 후 앱이 Backend URL을 찾는 방식

1. 빌드 시점에 `BACKEND_URL` 환경변수를 읽음
2. 해당 값을 `src/runtime-config.js`에 저장
3. 앱 화면(`login.html` 등)이 `window.RUNTIME_CONFIG.BACKEND_URL`을 사용해 API 호출

즉, 설치 후 URL을 바꾸려면 **재빌드**하거나, 배포 패키지의 `runtime-config.js`를 교체하는 운영 절차를 사용해야 합니다.

## 운영 시 주의사항

- 데스크톱 앱에는 비밀정보(앱키/시크릿)를 포함하지 않습니다.
- `runtime-config.js`에는 서버 URL 같은 비민감 값만 넣습니다.
- live trading 잠금/해제는 서버 안전검증을 통과해야만 반영됩니다.
