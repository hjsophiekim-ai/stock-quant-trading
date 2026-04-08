# Backend Deployment on Render

이 문서는 `backend`를 Render Web Service에 즉시 배포할 수 있도록
설정값/명령/검증 절차를 초보자 기준으로 정리합니다.

## 배포 구성 요약

- 서비스: FastAPI (`backend.app.main:app`)
- 배포 방식: Render Blueprint (`render.yaml`)
- root directory: `.`
- build command: `pip install --upgrade pip && pip install -r requirements/backend.txt`
- start command: `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT`
- health check path: `/api/health`

중요:
- Render URL은 보통 `https://<service>.onrender.com` 형태입니다.
- 앱에서는 이 URL 뒤에 API 경로가 붙습니다 (예: `https://<service>.onrender.com/api/health`).

## 의존성(backend 전용)

- 권장 파일: `requirements/backend.txt`
- 호환 파일: `backend/requirements.txt` (`-r ../requirements/backend.txt` 참조)

Render에서는 루트 기준으로 `requirements/backend.txt`를 사용합니다.

## Production 환경변수

### 최소 기동용 (서버가 뜨는 데 필요한 값)

- `APP_ENV=production`
- `APP_SECRET_KEY=<강력한 랜덤 문자열>`

### 운영 필수 (브로커 연결/토큰 발급까지 쓰려면 필요)

- `KIS_APP_KEY=<한국투자 앱키>`
- `KIS_APP_SECRET=<한국투자 시크릿>`

### 안전 기본값(권장)

- `TRADING_MODE=paper`
- `LIVE_TRADING=false`
- `LIVE_TRADING_ENABLED=false`
- `LIVE_TRADING_CONFIRM=false`
- `LIVE_TRADING_EXTRA_CONFIRM=false`

### 선택

- `DATABASE_URL` (미지정 시 sqlite 기본값)
- `REDIS_URL` (사용 시 외부 Redis 제공 필요)
- `KIS_BASE_URL`, `KIS_MOCK_BASE_URL`
- `RUNTIME_*`, `SCREENER_*`, `SIGNAL_*`, `RISK_*`, `ORDER_*`, `PORTFOLIO_*`

## Render 입력값 (수동 생성 시)

- Language: `Python`
- Root Directory: `.`
- Build Command: `pip install --upgrade pip && pip install -r requirements/backend.txt`
- Start Command: `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/api/health`

## 초보자용 5분 배포 절차

1. GitHub에 현재 저장소 push (루트의 `render.yaml` 포함)
2. Render 로그인 -> `New +` -> `Blueprint`
3. GitHub 저장소 선택 -> `Create new Blueprint Instance`
4. 생성된 `stock-quant-backend` 서비스의 `Environment` 탭에서 아래 입력
   - `APP_SECRET_KEY` (필수)
   - `KIS_APP_KEY`, `KIS_APP_SECRET` (운영 시 필수)
5. Deploy가 끝나면 `https://<service>.onrender.com/api/health` 접속해 `status: ok` 확인

## 배포 순서

1. 저장소 루트의 `render.yaml`을 원격에 push
2. Render에서 `New + -> Blueprint`로 저장소 연결
3. 생성된 `stock-quant-backend` 서비스 확인
4. Environment에 필수 변수 입력(`APP_SECRET_KEY`, `KIS_APP_KEY`, `KIS_APP_SECRET`)
5. Deploy 로그에서 uvicorn 기동 확인
6. 서비스 URL 확보 (`https://<service>.onrender.com`)

## 배포 후 Health 확인

- `GET https://<service>.onrender.com/api/health`
- `GET https://<service>.onrender.com/api/ready`

정상 기준:

- `/api/health` 응답: `{"status":"ok","service":"backend-api"}`
- `/api/ready` 응답: `status=ready` 및 `checks` 주요 항목 `true`

## 모바일/데스크톱 공용 BACKEND_URL

배포 완료 후 Render URL을 공용 백엔드 주소로 사용합니다.

- 모바일: `EXPO_PUBLIC_BACKEND_URL=https://<service>.onrender.com`
- 데스크톱: `BACKEND_URL=https://<service>.onrender.com`

운영 빌드에서는 localhost 대신 위 URL을 기본값으로 주입하세요.

앱 URL 구조 예시:
- 모바일/데스크톱 설정값: `https://stock-quant-backend.onrender.com`
- 실제 호출 예: `https://stock-quant-backend.onrender.com/api/auth/login`
