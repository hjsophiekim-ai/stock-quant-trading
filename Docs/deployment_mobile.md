# Mobile Deployment Guide (Android)

## 배포 모델

- 앱은 **로그인 후 백엔드 API만 사용**합니다.
- KIS 키/시크릿은 앱에 저장하지 않고, 서버에만 암호화 저장합니다.
- 일반 사용자 배포는 **클라우드 백엔드 URL 고정** 방식입니다.
  - 기본값: `https://api.stock-quant.example.com`
  - 필요 시 EAS 빌드 환경변수 `EXPO_PUBLIC_BACKEND_URL`로 교체

## 파일 구조

- `apps/mobile/app.config.ts`  
  - `extra.backendUrl`, `extra.appEnv` 주입
- `apps/mobile/eas.json`  
  - `preview-apk`(APK), `production`(AAB) 프로필
- `apps/mobile/src/config/env.ts`  
  - 런타임에서 `Constants.expoConfig.extra` 사용
- `apps/mobile/src/App.tsx`  
  - production 빌드에서는 온보딩 없이 로그인부터 시작

## 사전 준비

1. Node.js LTS
2. Expo 계정
3. EAS CLI 로그인

```bash
npm i -g eas-cli
eas login
```

## Android 빌드

```bash
cd apps/mobile
npm install
```

### 1) 테스트용 APK (내부 배포)

```bash
npm run build:android:apk
```

- 프로필: `preview-apk`
- 산출물: `.apk` (링크를 통해 다운로드)

### 2) 운영용 AAB (Play Console 제출)

```bash
npm run build:android:aab
```

- 프로필: `production`
- 산출물: `.aab`

### 백엔드 URL을 빌드 때 바꾸는 방법

```bash
EXPO_PUBLIC_BACKEND_URL=https://api.mycompany.com npx eas build --platform android --profile production
```

> 비밀정보(API 키/토큰)는 앱 환경변수에 넣지 않습니다.

## 설치 후 첫 실행 UX

1. 앱 실행
2. production 빌드는 바로 **로그인 화면**
3. 로그인/회원가입 성공 시 **대시보드 진입**
4. 하단 탭으로 브로커 설정 / Paper / 성과 화면 이동

## 운영 체크리스트

- [ ] `/api/health` 정상
- [ ] `/api/auth/*` 정상
- [ ] CORS/보안 정책에서 모바일 앱 호출 허용
- [ ] 브로커 정보는 서버 암호화 저장 확인
- [ ] live 잠금 플래그 기본 차단 유지
