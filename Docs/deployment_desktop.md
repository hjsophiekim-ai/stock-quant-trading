# 데스크톱(Windows) 배포 가이드

## 제품 구조

| 구성 요소 | 역할 |
|-----------|------|
| **Electron 앱** (`apps/desktop`) | 설치형 클라이언트. JWT 로그인·대시보드·브로커 설정 등 UI만 담당. |
| **백엔드 API** (`backend/`) | FastAPI 서버. 한국투자 연동·암호화 저장·Paper 세션 등 **반드시 서버에서 실행**. |

이 저장소의 Windows 설치 패키지는 **내장 백엔드(파이썬 번들)를 포함하지 않습니다.**  
`npm run build:win`(또는 루트 `desktop:build:win`)에서 **`BACKEND_URL`을 지정하지 않으면** 설치본 기본 API는 **`https://stock-quant-backend.onrender.com`** 입니다.

- **권장(일반 사용자)**: 위 기본값으로 빌드하거나, 자체 서버가 있으면 빌드 시 `BACKEND_URL`만 지정 → 사용자는 앱 설치 후 **로그인만** 하면 됨.
- **개발·내부 테스트**: `build:win:local` 로 `http://127.0.0.1:8000` 을 넣은 설치 파일을 만들고, PC에서 백엔드를 별도로 띄움.

로그인 화면 **「고급: 서버 주소」**에서 `localStorage` 기준으로 URL을 덮어쓸 수 있어, 현장 지원·스테이징 서버 전환이 가능합니다.

## 앱이 백엔드 주소를 읽는 순서

1. **빌드 시** `scripts/build-win.js`가 `src/runtime-config.js`를 임시로 덮어쓰며 `BACKEND_URL`, `APP_ENV`를 기록합니다. 패킹이 끝나면 **워크스페이스의 `runtime-config.js`는 원래(개발용) 내용으로 복원**됩니다.
2. **실행 시** 각 HTML은 `runtime-config.js`를 로드해 `window.RUNTIME_CONFIG.BACKEND_URL`을 **기본값**으로 사용합니다.
3. 사용자가 로그인 화면에서 저장한 **`backend_url_override`** 가 있으면 그것이 **우선**합니다 (`auth-session.js` 의 `effectiveBackendUrl()`).

설치형 빌드는 `APP_ENV=production` 이며, **첫 화면은 온보딩 없이 로그인**(저장된 토큰이 있으면 대시보드)입니다. 개발 모드(`APP_ENV=development`)에서는 기존처럼 1회 온보딩을 거칠 수 있습니다.

로그인 화면 상단의 **「서버 연결」** 은 `GET {BACKEND_URL}/api/health` 로 도달 여부를 표시합니다.

---

## 초보자용: Windows 설치파일(.exe) 빌드 (저장소 기준)

### 1) 왜 Google Drive / 동기화 폴더에서 빌드하면 안 되나

- `npm install` 이 패키지 압축 해제 시 **`TAR_ENTRY_ERROR`**, **파일 잠금**, **불완전한 `node_modules`** 로 실패하기 쉽습니다.
- 이전 빌드의 **`dist\win-unpacked`**, **`StockQuantDesktop.exe`** 가 잠겨 있으면 폴더 삭제·덮어쓰기가 막혀 **복사본이 깨진 상태**로 남을 수 있습니다.

**권장**: 저장소 전체를 **`C:\dev\stock-quant-trading`** 또는 **`C:\temp\stock-quant-trading`** 처럼 **로컬 디스크**로 복사한 뒤, 그 경로에서만 `npm install` / `npm run build:win` 을 실행합니다.

### 2) 빌드 전 준비 (잠금·깨진 복사본 대비)

1. **실행 중인 앱·빌드 산출물 종료**
   - 작업 관리자에서 **`Stock Quant Desktop`**, **`StockQuantDesktop.exe`**, **`Electron`** 관련 프로세스가 있으면 종료합니다.
   - 이전에 `win-unpacked` 안에서 앱을 실행해 둔 경우 **반드시 종료**합니다 (파일 잠금 원인).

2. **잠긴 `dist` 정리 (선택)**
   - PowerShell (저장소 루트 또는 `apps\desktop`):
   - `Remove-Item -Recurse -Force .\apps\desktop\dist -ErrorAction SilentlyContinue`
   - 여전히 삭제가 안 되면 **PC 재부팅** 후 다시 시도하거나, 해당 폴더를 사용 중인 **탐색기 창을 닫습니다**.

3. **필수 파일 존재 확인 (저장소가 온전한지)**

```powershell
# 저장소 루트에서 (루트에 루트 package.json 이 있어야 함)
Test-Path .\apps\desktop\package.json
Test-Path .\apps\desktop\scripts\build-win.js
Test-Path .\apps\desktop\scripts\verify-package-json.js
Test-Path .\apps\desktop\build\icons\icon.png
```

위가 모두 **`True`** 여야 합니다. 하나라도 `False` 이면 **clone/복사가 잘렸거나 경로가 잘못된 것**입니다.

4. **`package.json` 을 못 찾는다고 나올 때**

- **루트에서** `npm run desktop:build:win` 을 쓰는 경우: 반드시 **git 저장소 최상위**(루트 `package.json` 이 있는 폴더)에서 실행합니다.
- 확인:

```powershell
Get-Location
Test-Path .\package.json
Test-Path .\apps\desktop\package.json
node .\scripts\preflight-desktop-build.js
```

마지막 명령이 `[preflight] OK ...\apps\desktop\package.json` 을 출력하면 경로가 맞습니다.

5. **의존성 설치**

```powershell
cd C:\dev\stock-quant-trading
npm run desktop:install
```

또는 `apps\desktop` 만 직접 쓸 때:

```powershell
cd C:\dev\stock-quant-trading\apps\desktop
npm install
```

### 3) 설치파일 빌드 명령 (둘 중 하나만 일관되게)

**방법 A — 저장소 루트에서 (권장, 프리플라이트 포함)**

```powershell
cd C:\dev\stock-quant-trading
npm run desktop:build:win
```

다른 운영 서버 URL로 덮어써 빌드할 때:

```powershell
cd C:\dev\stock-quant-trading
$env:APP_ENV="production"
$env:BACKEND_URL="https://api.example.com"
npm run desktop:build:win
```

(`BACKEND_URL`을 비우면 기본으로 `https://stock-quant-backend.onrender.com` 이 들어갑니다.)

**방법 B — `apps\desktop` 으로 들어가서**

```powershell
cd C:\dev\stock-quant-trading\apps\desktop
npm run build:win
```

로컬 백엔드(127.0.0.1:8000)용 테스트 설치파일:

```powershell
cd C:\dev\stock-quant-trading\apps\desktop
npm run build:win:local
```

### 4) 빌드 성공 여부·산출물 확인

빌드가 끝나면 다음이 있어야 합니다.

| 확인 | 명령 또는 경로 |
|------|----------------|
| 설치 프로그램 | **`apps/desktop/dist/Stock Quant Desktop-Setup-0.1.0.exe`** (`package.json` 의 `version` 이 `0.1.0` 일 때) |
| 부가 파일 | 같은 폴더에 `Stock Quant Desktop-Setup-0.1.0.exe.blockmap` 등 생성 가능 |
| 언팩 결과 | `apps/desktop/dist/win-unpacked\` (중간 산출물) |

PowerShell 예:

```powershell
Get-ChildItem .\apps\desktop\dist\*.exe
```

`artifactName` 이 `${productName}-Setup-${version}.${ext}` 이므로, **`version` 을 올리면 파일명의 `0.1.0` 부분만 바뀝니다.**

---

## 빌드 환경 요약

- Windows 10/11 x64
- [Node.js LTS](https://nodejs.org/) (권장 20.x 이상)
- **`package.json` 구조**: `electron` / `electron-builder` 는 **`devDependencies` 만** (`build:win` 시 `verify-package-json.js` 로 검사).
- **모노레포**: 루트 `package.json` 은 **npm workspaces 없음**. 데스크톱 빌드는 **`npm run desktop:*`** 또는 **`cd apps\desktop`** 만 사용.

## 아이콘·NSIS 리소스

- **아이콘**: `apps/desktop/build/icons/icon.png` (256×256 이상 권장). `build.win.icon` 으로 지정됩니다.
- NSIS 추가 비트맵·브랜딩: `apps/desktop/build/installer/README.md`

## 설치 파일 생성 명령 (경로 요약)

위 **「초보자용」** 절차와 동일합니다. 요약:

- 루트: `npm run desktop:build:win`
- `apps\desktop` 만: `npm run build:win` / `npm run build:win:local`

- **HTTPS** 권장. 로컬 URL로 빌드하면 스크립트가 **경고**를 출력합니다.

### 산출물 (고정)

- **출력 디렉터리**: `apps/desktop/dist/`
- **기본 설치 파일명**: **`Stock Quant Desktop-Setup-0.1.0.exe`** (저장소 기본 `version` 기준)

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

## 빌드 실패 시 가장 흔한 원인 5가지

| # | 원인 | 해결 |
|---|------|------|
| 1 | **저장소 루트가 아닌 곳**에서 `npm run desktop:build:win` 실행 → `apps/desktop/package.json` 없음 | `Get-Location` 과 `Test-Path .\apps\desktop\package.json` 확인. 루트로 이동하거나 `cd apps\desktop` 후 `npm run build:win`. `node scripts/preflight-desktop-build.js` 로 확인. |
| 2 | **Google Drive / OneDrive** 경로에서 `npm install` · 빌드 → 잠금·깨진 `node_modules` | 프로젝트를 **`C:\dev\...` 또는 `C:\temp\...`** 로 전체 복사 후 그 경로에서만 빌드. |
| 3 | **이전 빌드 프로세스**(`StockQuantDesktop.exe`, `Electron`) 또는 **탐색기가 `dist\win-unpacked` 사용 중** | 작업 관리자로 프로세스 종료, 탐색기 창 닫기, 필요 시 재부팅 후 `dist` 삭제. |
| 4 | **`electron` 이 `dependencies`에 있음** (또는 옛 `package-lock` 혼선) | `apps/desktop/package.json` 에서 `electron` 은 **devDependencies만**. `node_modules` 삭제 후 `npm install` 재실행. |
| 5 | **`build/icons/icon.png` 누락** 또는 NSIS 언어 설정 오류 | `icon.png` 가 저장소에 포함되어 있는지 확인. NSIS 언어는 **`ko_KR` / `en_US`** 형식(저장소 기본값). |

## 문제 해결 (기타)

| 증상 | 조치 |
|------|------|
| 설치 후 “서버 연결: 실패” | 운영 백엔드 가동·URL·TLS 확인. 로그인 화면 고급에서 올바른 URL 저장 후 재시도. |
| 빌드 후 `src/runtime-config.js` 가 바뀜 | 정상입니다. 스크립트가 **finally에서 복원**합니다. 복원 실패 시 `git checkout -- apps/desktop/src/runtime-config.js` |
| `Package "electron" is only allowed in devDependencies` | 위 표 #4 참고. |
| `Language name is unknown for korean` | `installerLanguages` 를 **`ko_KR`**, **`en_US`** 로 유지. |
| `app-builder.exe` / 아이콘 변환 실패 | `build/icons/icon.png` (256×256 이상) 유지. |
| `TAR_ENTRY_ERROR` | 위 표 #2 참고. |

## 관련 파일

- `package.json` (저장소 루트) — `desktop:preflight` / `desktop:install` / `desktop:build:win`  
- `scripts/preflight-desktop-build.js` — 루트에서 `apps/desktop` 경로 검증  
- `apps/desktop/package.json` — `build` / `nsis` / `electron-builder` 설정  
- `apps/desktop/scripts/build-win.js` — URL 주입·`cwd` 고정·패킹  
- `apps/desktop/scripts/verify-package-json.js` — electron 의존성 위치 검증  
- `apps/desktop/build/icons/icon.png` — Windows 아이콘 소스  
- `apps/desktop/src/main.js` — production 시 로그인 우선 시작  
- `apps/desktop/src/runtime-config.js` — 개발 기본값(저장소에 커밋)  
- `apps/desktop/src/login.html` — 연결 확인·URL 오버라이드  
