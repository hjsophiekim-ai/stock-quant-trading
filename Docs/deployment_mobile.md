# Mobile Deployment Guide

## 대상

- Expo 기반 모바일 앱 (`apps/mobile`)
- Android/iOS 설치 패키지 생성 구조

## 사전 준비

- Node.js LTS
- Expo 계정
- EAS CLI (`npx eas --version`으로 확인)
- 앱 아이콘/스플래시 리소스
  - `apps/mobile/assets/icon.png`
  - `apps/mobile/assets/adaptive-icon.png`
  - `apps/mobile/assets/splash.png`

## 환경 설정

환경 파일 예시:

- `apps/mobile/.env.development.example`
- `apps/mobile/.env.production.example`

주입 변수:

- `APP_ENV`
- `EXPO_PUBLIC_BACKEND_URL`

> 비밀정보(API 키/토큰)는 모바일 앱 환경변수에 넣지 않습니다.

## 빌드 흐름

1. 개발 실행
   - `cd apps/mobile`
   - `npm install`
   - `npm run start`
2. Android preview 빌드
   - `npm run build:android:preview`
3. Android production 빌드
   - `npm run build:android:prod`
4. iOS preview 빌드
   - `npm run build:ios:preview`
5. iOS production 빌드
   - `npm run build:ios:prod`

## 운영 시 주의사항

- 앱은 서버 URL만 주입하고, 브로커 비밀정보는 저장하지 않습니다.
- 실거래 여부는 서버 안전장치(API/플래그)에서만 결정합니다.
