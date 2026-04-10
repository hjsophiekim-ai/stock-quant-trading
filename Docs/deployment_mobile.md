# Mobile Deployment Guide (Android)

초보자 기준으로 Android APK/AAB 빌드와 설치 후 점검 절차를 정리합니다.

## 1) 현재 저장소 기준 점검 결과

- `apps/mobile/package.json`
  - `build:android:apk` -> `eas build --platform android --profile preview-apk`
  - `build:android:aab` -> `eas build --platform android --profile production`
- Expo build 설정
  - `apps/mobile/eas.json`에 `preview-apk`(APK), `production`(AAB) 프로필 존재
- backend base url 주입 방식
  - `apps/mobile/app.config.ts`에서 `EXPO_PUBLIC_BACKEND_URL` -> `extra.backendUrl`로 주입
  - `apps/mobile/src/config/env.ts`에서 `BACKEND_URL`로 읽어 앱 전체에서 사용
- production UX
  - `APP_ENV=production`일 때 온보딩 없이 로그인 화면부터 시작 (`apps/mobile/src/App.tsx`)
- 로그인/대시보드 연결
  - 로그인 API: `POST {BACKEND_URL}/api/auth/login`
  - 성공 시 대시보드 API 호출: `/api/dashboard/summary`, `/api/trading/recent-trades`

## 2) 배포 모델

- 앱은 로그인 후 백엔드 API만 사용합니다.
- KIS 키/시크릿은 앱에 넣지 않고 서버에만 저장합니다.
- 일반 사용자 배포는 클라우드 백엔드 URL 고정 방식이 권장됩니다.

## 3) 사전 준비 (처음 한 번)

1. Node.js LTS 설치
2. Expo 계정 생성
3. EAS CLI 설치/로그인

```bash
npm i -g eas-cli
eas login
```

## 4) Android 빌드 절차

```bash
cd apps/mobile
npm install
```

### A. 내부 테스트용 APK

```bash
npm run build:android:apk
```

- 프로필: `preview-apk`
- 결과물: EAS 빌드 완료 후 제공되는 다운로드 링크의 `.apk`

### B. 운영 배포용 AAB (Play Console)

```bash
npm run build:android:aab
```

- 프로필: `production`
- 결과물: EAS 빌드 완료 후 제공되는 `.aab`

## 5) BACKEND_URL 주입 (중요)

기본적으로 `eas.json` 프로필의 `EXPO_PUBLIC_BACKEND_URL`이 사용됩니다.

- preview-apk: `https://staging-api.stock-quant.example.com`
- production: `https://api.stock-quant.example.com`

빌드 시 직접 덮어쓰기 예시:

```bash
EXPO_PUBLIC_BACKEND_URL=https://api.mycompany.com npx eas build --platform android --profile production
```

비밀정보(API 키/토큰)는 앱 환경변수에 넣지 않습니다.

## 6) 설치 후 로그인/대시보드 연결 확인

1. APK 설치 후 앱 실행
2. production 빌드는 로그인 화면이 먼저 보이는지 확인
3. 로그인 또는 회원가입 실행
4. 로그인 성공 후 대시보드 진입 확인
5. 대시보드에 데이터가 보이면 백엔드 연결 정상

연결 실패 시 우선 점검:
- `https://<backend-domain>/api/health` 응답 확인
- `https://<backend-domain>/api/auth/login` 호출 가능한지 확인
- 모바일 네트워크에서 해당 도메인 접속 가능한지 확인

## 7) 운영 체크리스트

- [ ] backend `/api/health` 정상
- [ ] auth(`/api/auth/*`) 정상
- [ ] 대시보드(`/api/dashboard/summary`) 정상
- [ ] 브로커 정보는 서버 암호화 저장
- [ ] live 잠금 플래그 기본 차단 유지
