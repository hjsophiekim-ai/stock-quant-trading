# Stock Quant Trading Platform (Monorepo)

설치형 자동매매 플랫폼 구조로 확장한 모노레포입니다.  
핵심 목표는 **수익률 개선**이지만, 시스템 최우선 제약은 **손실 최소화**입니다.
또한 **월 15%는 연구용 목표이며, 보장 수익이 아닙니다.**

## 플랫폼 구성

- `backend/` : FastAPI 기반 API 서버
- `apps/mobile/` : Expo React Native 모바일 앱
- `apps/desktop/` : Electron 데스크톱 앱
- `shared/` : 공통 타입/공통 API 모델/공통 유틸
- `app/` : 기존 트레이딩 코어 엔진(전략/리스크/브로커)  
  - 점진적으로 `backend` 서비스 계층으로 통합 예정

## 제품 상태 (설치형 관점)

### 지금 바로 사용 가능한 기능

- **로그인/인증**: `register` / `login` / `refresh` / `me`
- **브로커 계정 관리**: 저장/조회/삭제 + 연결 테스트
- **Paper 자동매매**: 시작/중지/상태/로그/포지션/손익 요약
- **대시보드 요약**: 런타임·리스크·브로커 상태·paper 세션 상태 집계
- **데스크톱 설치본**: Windows NSIS 설치 파일 생성 및 실행
- **모바일 설치본**: Android APK/AAB 빌드(EAS) 및 로그인/대시보드 진입

### mock/demo 성격이 남아 있는 기능 (명확 구분)

- **Performance API**: `portfolio_data` 스냅샷·체결 이력 기반 집계이며, 일부 지표(월 수익률·승률 등)는 추정치일 수 있음(`data_quality` 필드 참고).
- **대시보드 일부 카드**:
  - 사용자별 실계좌와 1:1 완전 동기화가 아닌 스냅샷/집계 혼합 구간 존재
  - README 및 대시보드 TODO 메시지에서 한계를 명시

### 설치 후 바로 쓰는 범위 vs TODO 범위

- 바로 가능:
  - 앱 설치 -> 로그인 -> 브로커 저장/연결 테스트 -> Paper 시작 -> 상태/로그/포지션 확인
- TODO:
  - 성과(Performance) 전 구간 실데이터화
  - 사용자별 포트폴리오 동기화 정합 완성
  - 다중 사용자 Paper 동시 실행 정책 고도화(현재 단일 세션 제약)

## 보안 원칙

- 한국투자 App Key/Secret를 모바일/데스크톱 앱에 저장하지 않습니다.
- 브로커 비밀정보는 서버에서 암호화 저장합니다.
- 앱은 자체 로그인(JWT) 후 서버를 통해서만 한국투자 API에 접근합니다.
- 기본값은 `paper trading`
- `live trading`은 잠금 상태이며 다중 확인 플래그 없이는 주문 불가

### 왜 앱에서 직접 한투 API를 호출하지 않나요?

- 앱 바이너리는 역분석/탈취 위험이 있어 API 키 보호가 어렵습니다.
- 사용자 기기마다 네트워크/보안 상태가 달라 감사 추적 일관성이 떨어집니다.
- 주문 전 리스크 검증(손절, 일일/총손실 제한, kill switch)을 서버에서 강제해야 안전합니다.

### 왜 서버 저장/암호화 구조가 필요한가요?

- 사용자별 브로커 계정을 분리 저장해 다중 사용자 운영을 지원합니다.
- 계정 정보는 서버에서 암호화 저장하여 유출 위험을 낮춥니다.
- 토큰 발급/연결 테스트를 서버에서만 수행해 민감정보 노출 경로를 줄입니다.

## 브로커 계정 관리

- 모바일·데스크톱 **브로커 설정** 화면에서 동일한 흐름으로 한국투자증권 정보를 입력합니다: App Key, App Secret, 계좌번호, 계좌상품코드, trading mode(기본 **paper**), **저장**, **연결 테스트**, 현재 연결 상태·마지막 테스트 시각 표시, **삭제**.
- `live` 모드 선택 시 앱에 **실거래 관련 강한 경고**가 표시됩니다(서버 주문은 별도 live 잠금 정책을 따릅니다).
- 서버는 사용자별로 키/계좌를 **암호화 저장**(SQLite `backend_data/broker_accounts.db`, Fernet)하고 `GET/POST/DELETE /api/broker-accounts/me`, `POST .../test-connection`, `GET .../status` 를 제공합니다.
- **모의 자동매매(Paper 세션)** 는 `POST /api/paper-trading/start` 로 시작합니다. JWT가 필요하고, 브로커 **trading_mode=paper**, **연결 테스트 성공**, **모의 API 호스트(openapivts)** 검증을 모두 통과한 경우에만 허용됩니다. `strategy_id: live` 는 거부됩니다. 서버에는 **동시에 한 명**의 Paper 세션만 허용되며(다른 사용자 세션 시 409), 연속 틱 실패가 한도를 넘으면 `risk_off` 가 되고 `POST /api/paper-trading/risk-reset`(세션 소유자) 또는 중지 후 재시작으로 복구합니다. 앱은 조건 미충족 시 시작 버튼을 비활성화합니다.
- Paper 세션은 **전역 `POST /api/runtime-engine/start`** 와 별개입니다(`.env` KIS 기반 엔진). 대시보드의 `portfolio/sync` 가 `.env` 키를 쓰는 경우, 앱에 저장한 모의 계정과 다르면 스냅샷이 어긋날 수 있으므로 운영 시 키·계정을 맞추는 것이 좋습니다.

## 설치형 앱 운영 흐름 (요약)

- 사용자 흐름: 로그인 -> 대시보드 -> 브로커 설정/모의투자 -> 성과 확인
- 관리자 흐름: 상태 모니터링 -> live 잠금 정책 점검 -> 위험 경고 대응 -> 필요 시 중단
- 모드 정책:
  - `paper trading`: 기본 모드, 실행/검증/학습용
  - `live trading`: 명시적 다중 승인 전까지 잠금

## 앱 첫 실행 (초보자)

모바일/데스크톱 공통으로 아래 순서대로 진행하면 바로 확인 가능합니다.

1. **로컬 개발**이면 백엔드를 먼저 실행합니다 (기본 주소 `http://127.0.0.1:8000` — 데스크톱/모바일 **개발 모드** 기본값). **스토어·설치 배포본**은 기본으로 `https://stock-quant-backend.onrender.com` 을 가리키며, 다른 서버를 쓰려면 빌드 시 `BACKEND_URL` / `EXPO_PUBLIC_BACKEND_URL` 로 지정합니다.
2. **첫 실행**이면 짧은 온보딩(설정 마법사) 후 로그인 화면으로 이동합니다.
3. Login 화면에서 `Register (First Run)` / `회원가입`으로 계정 생성 후 로그인합니다. **로그인 유지**를 켜면 다음 실행 시 자동 로그인을 시도합니다 (`/api/auth/me` · refresh).
4. 로그인 성공 후 **대시보드로 자동 진입**합니다.
5. 브로커 계정이 없으면 대시보드에 안내 배너가 뜹니다 → Broker Settings에서 KIS 정보 저장.
6. **저장** 후 **연결 테스트(토큰 발급)** 로 성공 상태를 만든 뒤,
7. Paper Trading 화면에서 **모의 자동매매 시작**(paper 모드·연결 성공 전에는 버튼 비활성) / **중지** / 필요 시 **risk 해제** 동작 확인. 화면은 약 15초마다 상태·포지션·로그를 갱신합니다.
8. Performance·대시보드에서 수익률/포지션/거래내역 확인. 대시보드 Paper 카드는 동일 Paper 세션 상태를 반영합니다(`portfolio/sync` 는 서버 `.env` 계정 기준이므로 계정을 통일하는 것이 안전합니다).

화면 목록:
- 온보딩(첫 실행)
- 로그인(실제 백엔드 연동, mock 로그인 아님)
- 대시보드(브로커 미등록 시 연결 유도)
- 브로커 설정 · 연결 테스트
- paper trading 시작/중지
- 성과(수익률/포지션/거래내역)

전체 사용자/API 흐름은 [docs/user_flow.md](docs/user_flow.md) 를 참고하세요.

Mock/실제 연동 구분:
- 실제 API 호출: auth, broker CRUD/test/status, Paper 세션 `POST /api/paper-trading/start|stop|risk-reset`, `GET .../status|positions|pnl|logs`, dashboard/performance 조회
- Paper 세션: 사용자 저장 **KIS 모의** 자격으로 틱 루프·모의 주문·(설정 시) 포트폴리오 동기화를 수행합니다. 일부 대시보드/성과 지표는 여전히 샘플 또는 `.env` 계정과의 정합 이슈가 있을 수 있습니다.

## 주요 문서

- `docs/product_architecture.md` : **일반 사용자 설치형 제품** 기준 아키텍처 (Win 설치본·Android·JWT·서버 번들)
- `docs/user_flow.md` : 실행→로그인→대시보드·자동 로그인·API 목록
- `Docs/today_run_checklist.md` : **오늘 바로 실행** (Windows·Python 3.11·`.env`·Swagger 순서)
- `Docs/quickstart_real_mock_trading.md` : 모의투자·백엔드·Swagger·체크리스트 (초보자)
- `docs/e2e_mock_trading.md` : Swagger 11단계 end-to-end 점검 가이드
- `docs/quickstart_user_desktop.md` : 일반 사용자용 Windows 빠른 시작
- `docs/quickstart_user_android.md` : 일반 사용자용 Android 빠른 시작
- `docs/quickstart_admin_backend.md` : 관리자용 backend 운영 빠른 시작
- `docs/system_design.md` : 전체 시스템 설계(앱+서버+트레이딩 코어)
- `docs/app_architecture.md` : 앱/서버/공유모듈 아키텍처 상세
- `docs/trading_rules.md` : 전략/리스크/국면별 운영 규칙
- `docs/live_trading_checklist.md` : 실거래 전 필수 체크리스트
- `docs/backtest_method.md` : 과최적화 방지 검증 방법론
- `docs/deployment_mobile.md` : 모바일 빌드/배포 가이드
- `docs/deployment_desktop.md` : 데스크톱(Windows) 빌드/배포 가이드
- `docs/deployment_backend.md` : backend 클라우드 배포 가이드 (Docker/health/ready)
- `docs/runtime_env.md` : 환경별 설정 주입/보안 원칙

## Render 배포 (Backend)

Render Web Service 기준으로 바로 배포할 수 있도록 루트에 `render.yaml`을 제공합니다.

- root directory: `.`
- build command: `pip install --upgrade pip && pip install -r requirements/backend.txt`
- start command: `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT`
- health check path: `/api/health`
- service URL 형식: `https://<service>.onrender.com`

초보자용 빠른 절차:
1. Render -> `New +` -> `Blueprint` -> 이 저장소 연결
2. 생성된 서비스 `Environment`에 `APP_SECRET_KEY` 입력
3. 브로커 연동까지 쓸 경우 `KIS_APP_KEY`, `KIS_APP_SECRET`도 입력
4. 배포 후 `https://<service>.onrender.com/api/health` 확인
5. 다른 Render 서비스나 자체 도메인을 쓸 때만 URL을 빌드에 넣기 (저장소 기본은 이미 `https://stock-quant-backend.onrender.com`):
   - 모바일: `EXPO_PUBLIC_BACKEND_URL=https://<service>.onrender.com`
   - 데스크톱: `BACKEND_URL=https://<service>.onrender.com`

상세 절차/환경변수/검증은 `docs/deployment_backend.md`를 참고하세요.

## 한국투자 API 연동 순서

1. 토큰 발급
2. 조회 API 검증
3. 모의주문 검증
4. 실거래 전환(잠금 해제 조건 충족 시)

## 초보자용 빠른 시작

**한국투자 모의계좌부터 Swagger·브로커 등록·paper·손익 확인까지** 하려면 아래 문서를 따르세요.

- **[Docs/today_run_checklist.md](Docs/today_run_checklist.md)** — 오늘 실행 최소 체크리스트(Swagger API 순서 포함)
- **[Docs/quickstart_real_mock_trading.md](Docs/quickstart_real_mock_trading.md)** — `.env.paper` → `.env`, 가상환경, 점검 스크립트, 10단계 체크리스트, 흔한 오류

요약 순서:

1) 저장소 클론 후 루트 이동

- `git clone <repo-url>`
- `cd "Stock quant trading"`

2) 환경 파일

- 루트의 `env.paper.example` 을 복사해 `.env.paper` 작성 후 **`.env` 로 복사**

3) 가상환경 + Python 의존성

- `python -m venv .venv` 후 활성화 (Windows: `.\.venv\Scripts\Activate.ps1`)
- **저장소 루트**에서 한 번에 설치 (권장):
  - 백엔드 + 트레이딩 코어(`app`, `backend`) 실행용:  
    `python -m pip install -U pip`  
    `python -m pip install -e .`
  - `pytest` 포함(테스트):  
    `python -m pip install -e ".[dev]"`
- `pip install -e .` 가 실패하면 `pyproject.toml` 의 `[build-system]`·`[tool.setuptools.packages.find]` 가 있는지 확인하세요. (구버전 pip/setuptools면 `python -m pip install -U pip setuptools wheel` 후 재시도)
- **대안 (평면 requirements만)**: `pip install -r requirements/backend.txt` 는 **서드파티 라이브러리만** 설치합니다. 이 경우에도 소스의 `app`/`backend` 를 import 하려면 저장소 루트를 `PYTHONPATH` 에 포함하거나, 반드시 `pip install -e .` 로 editable 설치하는 것이 안전합니다.

4) 환경/안전 점검

- `python scripts/check_env.py`
- `python scripts/check_runtime_safety.py`

5) 백엔드 실행

- Windows: `scripts\run_backend.bat`
- macOS/Linux: `bash scripts/run_backend.sh`
- 직접 실행: `python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload`

6) Paper 데모 스크립트 (백엔드 기동 후, 선택)

- `python scripts/start_paper_trading_demo.py`

7) 모바일 실행 (선택)

- `scripts\run_mobile.bat`

8) 데스크톱 실행 (선택)

- `scripts\run_desktop.bat`

### 문제 해결 빠른 체크

- `python scripts/check_env.py`에서 blocker가 없어야 합니다.
- 백엔드 접속 확인: `http://127.0.0.1:8000/`
- 실거래 모드는 기본 잠금이며, 다중 확인 플래그 없이는 live 주문이 차단됩니다.

## 한국투자 API 연결 테스트

`.env` 설정 후 아래 순서로 점검합니다.

1) 토큰/계좌 연결 점검

- `python scripts/check_kis_connection.py`

2) 시세 조회 점검

- `python scripts/check_kis_quotes.py`

3) 백엔드 API 점검 (서버 실행 후)

- 사용자 저장 계정 테스트: `POST /api/broker-accounts/me/test-connection`
- 현재 저장 상태 조회: `GET /api/broker-accounts/me/status`
- 런타임(.env) 테스트: `POST /api/broker-accounts/runtime/test-connection`

실패 메시지는 원인별로 구분됩니다.
- 앱키/시크릿 누락
- 계좌번호 형식 오류
- base url 오류
- 토큰 발급 실패/조회 API 실패

## Windows 데스크톱 설치 파일 (일반 사용자)

Electron 기반 **NSIS 설치 프로그램**(`Stock Quant Desktop-Setup-*.exe`)을 빌드할 수 있습니다. 설치 후 **바탕화면·시작 메뉴 바로가기**로 실행하며, **production 빌드는 로그인 화면부터** 시작합니다(온보딩 생략).

**백엔드는 앱에 포함되지 않습니다.** `BACKEND_URL` 없이 빌드하면 설치본 기본 API는 **`https://stock-quant-backend.onrender.com`** 입니다. 자체 서버를 쓰면 빌드 시 `BACKEND_URL`만 지정하면 됩니다.

**빌드 요약 (개발자)**

- **Google Drive 등 동기화 폴더에서는 빌드하지 마세요.** 저장소를 **`C:\dev\...` 또는 `C:\temp\...`** 로 복사한 뒤 진행합니다.
- 빌드 전 **`StockQuantDesktop.exe` / Electron** 프로세스를 종료하고, 잠긴 `apps\desktop\dist` 가 있으면 닫거나 삭제합니다.
- 저장소 **루트**에서: `npm run desktop:install` → `npm run desktop:build:win` (`apps\desktop\package.json` 경로를 자동 검증).
- 또는 `cd apps\desktop` 후 `npm install` → `npm run build:win`(Render 기본) / `npm run build:win:local`(로컬 백엔드용).

```powershell
# 예: 로컬 디스크에 복사한 저장소 루트에서 (설치본 → Render 기본)
npm run desktop:install
npm run desktop:build:win
# 로컬 백엔드(127.0.0.1:8000)용 설치 파일은 apps\desktop 에서:
# npm run build:win:local
```

산출물: **`apps/desktop/dist/Stock Quant Desktop-Setup-0.1.0.exe`** (기본 `version` 이 `0.1.0` 일 때; 버전은 `apps/desktop/package.json` 참고)

**PC·폰에 나눠 줄 zip 패키지**: 빌드 후 루트에서 `npm run release:zip:clients` → `release/stock-quant-client-install.zip`. APK는 EAS로 빌드한 뒤 스크립트에 `-ApkPath`로 넣거나 폴더에 복사 후 다시 압축하면 됩니다. **어디에 올려 받게 할지**는 [Docs/client_install_download.md](Docs/client_install_download.md) 참고(GitHub Releases, 클라우드 링크 등).

**사용자 최소 설정**: 설치 후 앱 실행 → 로그인(또는 회원가입). 서버 URL은 설치 파일에 포함된 기본값을 쓰며, 바꿀 때만 로그인 화면 **「고급: 서버 주소」**를 사용합니다. 상단 **서버 연결** 표시가 `GET /api/health` 기준으로 정상인지 보여 줍니다.

초보자용 단계·잠금 해제·실패 5가지: **[Docs/deployment_desktop.md](Docs/deployment_desktop.md)**

Backend URL 주입 요약:
- 빌드 시 `scripts/build-win.js`가 임시로 `src/runtime-config.js`에 `BACKEND_URL`·`APP_ENV`를 쓰고, 패킹 후 **원래 개발용 파일로 복원**합니다.
- 실행 시 `window.RUNTIME_CONFIG.BACKEND_URL` + (선택) 로그인 화면에서 저장한 `localStorage` 오버라이드.

## Android 설치 파일 (일반 사용자)

모바일 앱은 Expo/EAS 기반으로 배포하며, **앱에는 KIS 키를 저장하지 않고 로그인 후 백엔드 API만 사용**합니다.  
일반 사용자 배포는 **프로덕션 빌드에서 `https://stock-quant-backend.onrender.com` 이 기본**이며, 다른 API를 쓸 때만 환경변수로 덮어씁니다. 로컬 개발(`expo start`)은 기본이 `http://127.0.0.1:8000` 입니다.

빌드(개발자 PC):

```bash
cd apps/mobile
npm install
# 내부 테스트용 APK
npm run build:android:apk
# 운영 배포용 AAB (Google Play)
npm run build:android:aab
```

`apps/mobile/app.config.ts`에서 `APP_ENV`에 따라 위 기본값이 정해집니다. 다른 서버로 고정하려면:

```bash
EXPO_PUBLIC_BACKEND_URL=https://api.mycompany.com npx eas build --platform android --profile production
```

설치 후 사용자 흐름:
- 앱 실행 -> (production 빌드) 로그인 화면
- 회원가입/로그인 -> 대시보드 진입
- 하단 탭에서 브로커 설정 / Paper Trading / 성과 조회

상세 배포 가이드: **[docs/deployment_mobile.md](docs/deployment_mobile.md)**
