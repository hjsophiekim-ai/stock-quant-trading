# Mobile App (Expo React Native)

모바일 앱은 사용자 인증(JWT) 후 백엔드 API를 통해서만 데이터를 조회하고 주문 요청을 보냅니다.

- 브로커 키/시크릿은 모바일 앱에 저장하지 않습니다.
- 기본 모드는 paper trading입니다.
- live trading 요청은 서버의 안전 규칙을 통과해야 합니다.

## Android 빌드

```bash
cd apps/mobile
npm install
npm run build:android:apk   # 내부 배포용 APK
npm run build:android:aab   # Play 제출용 AAB
```

- 기본 백엔드 URL은 `app.config.ts`에서 클라우드 주소로 주입됩니다.
- 배포별 URL 변경은 `EXPO_PUBLIC_BACKEND_URL` 환경변수로 처리합니다.
