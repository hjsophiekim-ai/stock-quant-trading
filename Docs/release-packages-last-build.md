# 클라이언트 설치 ZIP 최근 빌드 기록

이 파일은 **Git에 포함되는 빌드 메타데이터**입니다. 실제 ZIP 바이너리는 `.gitignore`된 `release/` 폴더에만 있으며 저장소에는 올라가지 않습니다.

| 항목 | 값 |
|------|-----|
| 빌드 일시 (로컬) | 2026-04-18 |
| 저장소 커밋 (데스크톱 빌드 스탬프에 포함) | `667b3ca38d9fad8da660eb2841670b69128ff6a2` |
| 스크립트 | `scripts/build-release-zips.ps1` (또는 `npm run release:build:zips`) |
| 데스크톱 버전 | `apps/desktop/package.json` → 0.1.0 |
| Windows (전용 ZIP) | `release/Stock-Quant-Desktop-Windows-0.1.0.zip` — NSIS 설치 `.exe` + `INSTALL-DESKTOP.bat` + `README-KO.txt` |
| Windows (번들 ZIP) | `release/stock-quant-client-install.zip` — 위 설치 `.exe` + `README-CLIENT-INSTALL-*.txt` + `client_install_download.md` |
| Android (전용 ZIP) | `release/Stock-Quant-Android-0.1.0.zip` — 이 빌드는 **APK 미포함** (`ANDROID-APK-BUILD-HINT.txt` 및 안내 문서) |
| Android (번들 ZIP) | `release/stock-quant-android-install.zip` — 동일, APK 없을 때 빌드 안내만 |

| 빌드 시 백엔드 URL | `https://stock-quant-backend.onrender.com` (스크립트 기본값, `-BackendUrl`로 변경 가능) |

**참고:** ZIP에는 **Electron 데스크톱/모바일 클라이언트**만 포함됩니다. Python 백엔드(FastAPI)나 서버 배포는 별도입니다. 백엔드 변경(예: 미국 모의투자 수정)은 **서버를 해당 커밋으로 배포**해야 반영됩니다.

## APK를 ZIP에 넣으려면

```powershell
.\scripts\build-release-zips.ps1 -ApkPath "C:\path\to\app.apk"
```

## 이전 ZIP 폐기

동일 스크립트는 같은 버전 이름의 기존 ZIP을 덮어쓰기 전에 제거합니다. 수동으로 `release/Stock-Quant-*.zip`을 지운 뒤 위 스크립트를 다시 실행해도 됩니다.
