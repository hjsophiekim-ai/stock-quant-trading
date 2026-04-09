# Desktop App (Electron)

Windows용 **설치형 클라이언트**입니다. API 키 등 비밀정보는 앱에 넣지 않고 **백엔드**에만 저장합니다.

## 백엔드 연결 방식

- **배포 권장**: 빌드할 때 `BACKEND_URL`에 **운영(또는 스테이징) HTTPS API**를 넣습니다. 사용자는 백엔드를 직접 실행하지 않습니다.
- **로컬 개발**: `npm start` + 루트에서 백엔드 `http://127.0.0.1:8000` 실행. 로그인 화면에서 연결 상태가 표시됩니다.

런타임 기본 URL은 `src/runtime-config.js` 이며, 로그인 화면 **고급: 서버 주소**로 `localStorage` 덮어쓰기가 가능합니다.

## 개발 실행

```powershell
cd apps\desktop
npm install
npm start
```

## Windows 설치 파일 빌드

**권장**: 저장소를 `C:\dev\...` 등 로컬 디스크에 두고, Google Drive 경로에서는 빌드하지 마세요. 빌드 전 `StockQuantDesktop.exe` / Electron 프로세스를 종료하세요.

```powershell
# 저장소 루트에서 (프리플라이트 포함)
cd <저장소-루트>
npm run desktop:install
npm run desktop:build:win
```

또는 이 폴더에서 직접:

```powershell
cd apps\desktop
npm install
npm run build:win:local
npx cross-env APP_ENV=production BACKEND_URL=https://api.example.com npm run build:win
```

결과: `dist/Stock Quant Desktop-Setup-<version>.exe` (기본 `0.1.0` 이면 `Stock Quant Desktop-Setup-0.1.0.exe`)

상세: [Docs/deployment_desktop.md](../../Docs/deployment_desktop.md)
