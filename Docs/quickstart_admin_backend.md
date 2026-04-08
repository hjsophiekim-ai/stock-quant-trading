# 관리자 Quick Start (Backend 운영)

이 문서는 운영자/관리자가  
모바일·데스크톱 앱이 공통으로 사용할 backend를 빠르게 올리고 점검하기 위한 안내입니다.

목표:
- 사용자가 Swagger를 열지 않아도 앱에서 바로 로그인/대시보드 사용
- desktop/mobile이 같은 backend URL 사용
- 기본은 paper, live는 잠금 유지

---

## 0) 운영 원칙 (중요)

- 민감정보(KIS 키/시크릿)는 **환경변수**로만 주입
- 기본 모드는 **paper**
- live 관련 플래그는 기본 `false` 유지
- 사용자는 앱만 사용, Swagger는 관리자 점검 용도

---

## 1) 가장 쉬운 실행 (Docker Compose)

저장소 루트에서:

```bash
docker compose up --build -d
```

기본 포트:
- `http://<server-ip>:8000`

헬스 확인:

```bash
curl http://<server-ip>:8000/api/health
```

---

## 2) 필수 환경변수

최소 필수:
- `APP_ENV=production`
- `APP_SECRET_KEY=<강한 랜덤 문자열>`
- `TRADING_MODE=paper`
- `LIVE_TRADING=false`
- `LIVE_TRADING_ENABLED=false`
- `LIVE_TRADING_CONFIRM=false`
- `LIVE_TRADING_EXTRA_CONFIRM=false`

KIS 관련:
- `KIS_APP_KEY`
- `KIS_APP_SECRET`
- `KIS_BASE_URL`
- `KIS_MOCK_BASE_URL`

권장:
- `DATABASE_URL` (운영 DB)
- `REDIS_URL` (선택)

---

## 3) 운영 점검 엔드포인트

### 필수 (헬스/상태)
- `GET /api/health`
- `GET /api/runtime-engine/status`
- `GET /api/paper-trading/status`
- `GET /api/risk/status`
- `GET /api/live-trading/status`

확인 포인트:
- health: `status=ok`
- live status: 기본 경고가 "잠금 상태"여야 정상
- paper/runtime: 에러 누적, risk_off 여부 모니터링

---

## 4) 앱 연결 방식

운영 URL 예시:
- `https://api.yourdomain.com`

데스크톱:
- 빌드시 `BACKEND_URL=https://api.yourdomain.com` 주입

모바일:
- EAS 빌드시 `EXPO_PUBLIC_BACKEND_URL=https://api.yourdomain.com` 주입

결과:
- 데스크톱/모바일 모두 같은 계정 상태, 같은 대시보드 데이터 사용

---

## 5) 사용자 첫 사용 흐름(운영자 안내용)

1. 앱 설치(데스크톱/안드로이드)
2. 로그인/회원가입
3. 브로커 설정 저장
4. 연결 테스트 성공
5. Paper 시작
6. 대시보드/성과 확인

---

## 6) 자주 발생하는 운영 오류와 해결

### A. 앱 로그인 실패 다수 발생
- 점검: `/api/health`, 인증 라우트 로그, DB 연결 상태
- 조치: APP_SECRET_KEY/DB 설정 재확인, 재배포

### B. 브로커 연결 테스트 실패 급증
- 점검: KIS 키 만료/오입력, KIS 장애 공지
- 조치: 키 재발급, 운영자 공지

### C. Paper 세션 risk_off 빈발
- 점검: `/api/paper-trading/status`의 failure_streak, 최근 logs
- 조치: 네트워크/API 오류 원인 제거 후 risk-reset 가이드

### D. live 주문이 열렸다는 문의
- 점검: `GET /api/live-trading/status`, 환경변수 4종
- 조치: 즉시 LIVE 플래그 false로 롤백, 운영 점검

---

## 7) 운영 체크리스트 (매일)

- [ ] `/api/health` 정상
- [ ] 인증/로그인 정상
- [ ] 브로커 테스트 성공률 정상
- [ ] paper 상태(running/stopped/risk_off) 모니터링
- [ ] live 잠금 유지 확인
- [ ] 오류 로그 백업/보관

