# 클라이언트 설치 파일 받는 방법 (Windows · Android)

저장소만으로는 **자동 다운로드 URL이 생기지 않습니다.** 아래 중 하나로 패키지를 올리면 PC·폰에서 받을 수 있습니다.

## 1) GitHub Releases (권장)

1. GitHub 저장소 → **Releases** → **Draft a new release**
2. 태그 예: `client-v0.1.0`
3. `stock-quant-client-install.zip` (또는 분리한 `.exe` / `.apk`)을 **Assets**에 드래그 업로드
4. 게시(Publish) 후 릴리스 페이지의 **Assets**에서 다운로드

동일 저장소라면: `https://github.com/<계정>/<저장소>/releases`

## 2) Google Drive / OneDrive / Dropbox

1. `stock-quant-client-install.zip` 업로드
2. 링크 공유: **링크가 있는 모든 사용자** (또는 본인만 아는 대상)
3. 폰/PC 브라우저에서 링크로 다운로드

## 3) 직접 전달

USB, 메신저, 이메일(용량 제한 주의)로 `zip` 또는 `exe`/`apk` 파일을 복사합니다.

---

## zip 안에 무엇이 들어가나

| 파일 | 설명 |
|------|------|
| `Stock Quant Desktop-Setup-*.exe` | Windows 설치 프로그램 (NSIS). 실행 후 설치 마법사 따름. |
| `StockQuantTrader-*.apk` | (선택) 내부 테스트용 Android APK. 있을 때만 zip에 넣습니다. |
| `README-CLIENT-INSTALL-KO.txt` | 한글 요약 안내 |

**Android APK**는 EAS/로컬 빌드로 별도 생성한 뒤 zip에 넣거나, Releases에 따로 올리면 됩니다.  
빌드 명령: `Docs/deployment_mobile.md` 의 `build:android:apk` 참고.

---

## 설치 후 바로 테스트

1. **Windows**: 설치 실행 → 앱 기동 → 로그인 → 대시보드 상단 **「모의 투자 테스트」** 안내 순서대로 진행  
2. **Android**: 알 수 없는 출처 허용(기기 설정) → APK 설치 → 동일 흐름  
3. 백엔드는 빌드 기본값(`https://stock-quant-backend.onrender.com`)을 사용합니다. 로컬 서버를 쓰려면 데스크톱은 `build:win:local`로 다시 빌드하거나 로그인 화면 고급 설정에서 URL을 바꿉니다.

---

## zip 만드는 방법 (개발자 PC)

PowerShell, 저장소 **루트**에서:

```powershell
npm run desktop:build:win
.\scripts\package-client-install-zip.ps1
```

산출물: `release/stock-quant-client-install.zip`

APK를 같이 넣으려면 빌드 후 `release/client-install-staging/` 폴더에 `.apk` 파일을 복사한 뒤 스크립트를 다시 실행하거나, 스크립트의 `-ApkPath` 옵션을 사용합니다.
