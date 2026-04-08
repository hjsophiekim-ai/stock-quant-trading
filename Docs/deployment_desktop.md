# 데스크톱(Windows) 배포 가이드

## 제품 구조

| 구성 요소 | 역할 |
|-----------|------|
| **Electron 앱** (`apps/desktop`) | 설치형 클라이언트. JWT 로그인·대시보드·브로커 설정 등 UI만 담당. |
| **백엔드 API** (`backend/`) | FastAPI 서버. 한국투자 연동·암호화 저장·Paper 세션 등 **반드시 서버에서 실행**. |

이 저장소의 Windows 설치 패키지는 **내장 백엔드(파이썬 번들)를 포함하지 않습니다.**  
일반 사용자가 **로컬에서 `uvicorn`을 직접 실행하지 않아도** 쓰려면, 배포 시 **`BACKEND_URL`을 운영 중인 원격(또는 사내) API 서버**로 고정해 빌드하는 방식을 권장합니다.

- **권장(일반 사용자)**: 원격 백엔드 URL을 빌드 시 주입 → 사용자는 앱 설치 후 **로그인만** 하면 됨(서버는 운영자가 상시 구동).
- **개발·내부 테스트**: `build:win:local` 로 `http://127.0.0.1:8000` 을 넣은 설치 파일을 만들고, PC에서 백엔드를 별도로 띄움.

로그인 화면 **「고급: 서버 주소」**에서 `localStorage` 기준으로 URL을 덮어쓸 수 있어, 현장 지원·스테이징 서버 전환이 가능합니다.

## 앱이 백엔드 주소를 읽는 순서

1. **빌드 시** `scripts/build-win.js`가 `src/runtime-config.js`를 임시로 덮어쓰며 `BACKEND_URL`, `APP_ENV`를 기록합니다. 패킹이 끝나면 **워크스페이스의 `runtime-config.js`는 원래(개발용) 내용으로 복원**됩니다.
2. **실행 시** 각 HTML은 `runtime-config.js`를 로드해 `window.RUNTIME_CONFIG.BACKEND_URL`을 **기본값**으로 사용합니다.
3. 사용자가 로그인 화면에서 저장한 **`backend_url_override`** 가 있으면 그것이 **우선**합니다 (`auth-session.js` 의 `effectiveBackendUrl()`).

설치형 빌드는 `APP_ENV=production` 이며, **첫 화면은 온보딩 없이 로그인**(저장된 토큰이 있으면 대시보드)입니다. 개발 모드(`APP_ENV=development`)에서는 기존처럼 1회 온보딩을 거칠 수 있습니다.

로그인 화면 상단의 **「서버 연결」** 은 `GET {BACKEND_URL}/api/health` 로 도달 여부를 표시합니다.

## 빌드 전 준비

- Windows 10/11 x64
- [Node.js LTS](https://nodejs.org/) (권장 20.x)
- **`package.json` 구조**: `electron` 과 `electron-builder` 는 **반드시 `devDependencies`** 에만 둡니다. `dependencies` 에 `electron` 이 있으면 electron-builder 등이 빌드를 거절할 수 있습니다(`Package "electron" is only allowed in "devDependencies"`).
- **권장**: `node_modules` 는 **로컬 디스크**(예: `C:\dev\...`)에 두고 빌드하세요. Google Drive·OneDrive 동기화 폴더에서는 `npm install` / 압축 해제 시 `TAR_ENTRY_ERROR` 가 날 수 있습니다.

저장소 클론 후:

```powershell
cd apps\desktop
npm install
```

## 아이콘·NSIS 리소스

- 필수: `apps/desktop/build/icons/icon.ico`  
  - 없으면 빌드 스크립트가 **최소 플레이스홀더** `.ico` 를 생성합니다. 상용 배포 전에 **256×256 포함 멀티 해상도 아이콘**으로 교체하세요.
- 선택: `apps/desktop/build/installer/README.md` 참고 — 사이드바/헤더 BMP, 라이선스 페이지 등.

## 설치 파일 생성 명령

### A) 로컬 백엔드용 설치 패키지 (개발·자가 호스팅)

백엔드를 같은 PC에서 `127.0.0.1:8000` 으로 띄우는 사용자용:

```powershell
cd apps\desktop
npm run build:win:local
```

### B) 원격(운영) API URL이 고정된 설치 패키지 (일반 사용자 권장)

PowerShell (한 줄):

```powershell
cd apps\desktop
$env:APP_ENV="production"
$env:BACKEND_URL="https://api.yourcompany.com"
npm run build:win
```

또는 `npx cross-env` (npm 스크립트와 동일하게 동작):

```powershell
cd apps\desktop
npx cross-env APP_ENV=production BACKEND_URL=https://api.yourcompany.com npm run build:win
```

- **HTTPS** 권장. 인증서가 신뢰되지 않으면 Electron에서 연결이 실패할 수 있습니다.
- 로컬 URL로 빌드하면 스크립트가 **경고**를 출력합니다(실수 방지).

### 산출물

- **출력 디렉터리**: `apps/desktop/dist/` (`package.json` 의 `build.directories.output`)
- **NSIS 설치 파일**: `apps/desktop/dist/Stock Quant Desktop-Setup-0.1.0.exe` (버전은 `package.json` 의 `version` 과 동일; 제품명·공백은 `productName` 과 동일)
- 빌드 중간 산물(언팩 앱 등)도 같은 `dist` 아래에 생성될 수 있습니다.

## NSIS 설치 동작 요약

- 사용자가 설치 경로 선택 가능 (`oneClick: false`)
- **바탕화면 바로가기**·**시작 메뉴** 항목 생성
- 설치 완료 후 앱 실행 옵션 (`runAfterFinish: true`)

## 설치 후 사용자 실행 흐름

1. 바탕화면 또는 시작 메뉴의 **「Stock Quant Desktop」** 실행  
2. **로그인** 화면에서 서버 연결 상태 확인  
3. 회원가입(최초) 또는 로그인 → 대시보드  
4. 브로커 설정·Paper Trading 등은 기존 웹과 동일하게 백엔드 API 사용  

## 운영자 체크리스트 (원격 백엔드)

- [ ] 백엔드가 공인 URL에서 TLS로 서비스되는지  
- [ ] CORS: Electron `file://` 또는 `app://` 출처가 아닌 **fetch 대상은 순수 HTTPS URL** 이므로, 백엔드에서 해당 Origin/메서드가 허용되는지(필요 시 `CORSMiddleware` 설정)  
- [ ] `GET /api/health` 가 200으로 응답하는지 (앱 연결 표시용)  
- [ ] 사용자에게 **백엔드 URL을 안내**할 필요 없음 — 설치 파일에 이미 박혀 있음(변경이 필요하면 로그인 화면 고급 설정 또는 재배포)  

## 코드 서명(선택·권장)

배포 시 SmartScreen 경고를 줄이려면 Authenticode 서명을 적용합니다.

- 인증서 준비 후 `electron-builder` 의 `win.certificateFile` / `certificatePassword` 또는 CI 시 `CSC_LINK` / `CSC_KEY_PASSWORD` 환경 변수를 사용합니다.  
- 자세한 항목은 [electron-builder 코드 서명 문서](https://www.electron.build/code-signing)를 참고하세요.

## 로컬 백엔드를 “완전 자동”으로 넣고 싶다면 (미구현)

현재 공식 경로는 **원격 백엔드**입니다. 같은 설치 프로그램에 Python 런타임·가상환경·`uvicorn`을 묶으려면 별도 작업(용량·업데이트·방화벽·서비스 등록)이 필요합니다. 필요 시 `docs/product_architecture.md` 와 별도 이슈로 범위를 정의하는 것을 권장합니다.

## 문제 해결

| 증상 | 조치 |
|------|------|
| 설치 후 “서버 연결: 실패” | 운영 백엔드 가동·URL·TLS 확인. 로그인 화면 고급에서 올바른 URL 저장 후 재시도. |
| 빌드 후 `src/runtime-config.js` 가 바뀜 | 정상입니다. 스크립트가 **finally에서 복원**합니다. 복원 실패 시 `git checkout -- apps/desktop/src/runtime-config.js` |
| `npm run build:win:local` 실패 | `npm install` 재실행, Node LTS 사용, 관리자 권한 불필요(일반 사용자 권한으로 빌드 가능). |
| `Package "electron" is only allowed in devDependencies` | `apps/desktop/package.json` 에서 `electron` 을 `dependencies` 에서 제거하고 `devDependencies` 로 옮긴 뒤 `npm install` 재실행. |
| `TAR_ENTRY_ERROR` / Drive 동기화 폴더 | 프로젝트를 로컬 디스크로 복제하거나 `node_modules` 를 로컬 경로에 설치. |

## 관련 파일

- `apps/desktop/package.json` — `build` / `nsis` / `electron-builder` 설정  
- `apps/desktop/scripts/build-win.js` — URL 주입·아이콘 플레이스홀더·패킹  
- `apps/desktop/src/main.js` — production 시 로그인 우선 시작  
- `apps/desktop/src/runtime-config.js` — 개발 기본값(저장소에 커밋)  
- `apps/desktop/src/login.html` — 연결 확인·URL 오버라이드  
