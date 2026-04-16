# 클라이언트 설치 ZIP 최근 빌드 기록

이 파일은 **Git에 포함되는 빌드 메타데이터**입니다. 실제 ZIP 바이너리는 `.gitignore`된 `release/` 폴더에만 있으며 저장소에는 올라가지 않습니다.

| 항목 | 값 |
|------|-----|
| 빌드 일시 (KST) | 2026-04-16 |
| 스크립트 | `scripts/build-release-zips.ps1` (또는 `npm run release:build:zips`) |
| 데스크톱 버전 | `apps/desktop/package.json` → 0.1.0 |
| Windows 패키지 | `release/Stock-Quant-Desktop-Windows-0.1.0.zip` (NSIS 설치 `.exe` + `INSTALL-DESKTOP.bat` + `README-KO.txt`) |
| Android 패키지 | `release/Stock-Quant-Android-0.1.0.zip` (이 PC 빌드 시 APK 미포함 → `ANDROID-APK-BUILD-HINT.txt` 및 안내 문서만 포함) |
| 빌드 시 백엔드 URL | `https://stock-quant-backend.onrender.com` (스크립트 기본값, `-BackendUrl`로 변경 가능) |

## APK를 ZIP에 넣으려면

```powershell
.\scripts\build-release-zips.ps1 -ApkPath "C:\path\to\app.apk"
```

## 이전 ZIP 폐기

동일 스크립트는 같은 버전 이름의 기존 ZIP을 덮어쓰기 전에 제거합니다. 수동으로 `release/Stock-Quant-*.zip`을 지운 뒤 위 스크립트를 다시 실행해도 됩니다.
