# 초보자용: 설치 파일 받기 · 설치하기 · 테스트 시작

이 문서는 **Windows PC**와 **Android 폰**에서 Stock Quant 클라이언트를 쓰기 위한 최소 안내입니다.

---

## 1. 설치 zip 파일이 어디 있나요?

**개발 PC에서 빌드한 경우** (권장 경로 `C:\dev\stock-quant-trading`):

| 경로 | 설명 |
|------|------|
| `C:\dev\stock-quant-trading\release\stock-quant-client-install.zip` | Windows 설치 파일 + README(KO/EN, UTF-8 BOM) + (선택) APK |
| `C:\dev\stock-quant-trading\release\stock-quant-android-install.zip` | Android 전용: 안내 문서 + (선택) APK; APK 없으면 빌드 절차 설명 |

저장소를 Google Drive 등 **한글/동기화 경로**에만 두고 빌드하면 `electron-builder`가 실패할 수 있으므로, **반드시 `C:\dev\stock-quant-trading` 같은 영문 로컬 경로**에서 빌드하세요.

```powershell
cd C:\dev\stock-quant-trading
git pull
npm run desktop:install
npm run desktop:build:win
npm run release:zip:clients
npm run release:zip:android
```

ZIP 안의 `README-*.txt` 는 **UTF-8 BOM**으로 생성되어 Windows 메모장에서 한글·영문이 깨지지 않습니다.

**다른 PC/폰에서 받으려면** zip을 직접 옮겨야 합니다.

- **GitHub Releases**: 저장소 → Releases → Assets에 `stock-quant-client-install.zip` 업로드 후 다운로드  
  (방법은 [client_install_download.md](client_install_download.md) 참고)
- **Google Drive / OneDrive**: zip 업로드 후 「링크가 있는 사용자」로 공유 → 링크로 다운로드

> **zip 안에 무엇이 들어가나 (현재 기본)**  
> - `Stock Quant Desktop-Setup-0.1.0.exe` — Windows 설치 프로그램  
> - `README-CLIENT-INSTALL-KO.txt`, `client_install_download.md` — 안내  
> **Android `.apk`는 같은 zip에 자동으로 들어가지 않습니다.** 아래 「Android APK 만들기」를 따른 뒤, 스크립트로 합치세요.

---

## 2. Windows — 다운로드 후 설치

1. PC에서 `stock-quant-client-install.zip` **압축 풀기** (마우스 우클릭 → 모두 추출).
2. **`Stock Quant Desktop-Setup-0.1.0.exe`** 더블클릭.
3. 설치 마법사 안내에 따라 진행 (설치 경로 선택 가능).
4. 설치 후 **Stock Quant Desktop** 실행.
5. **로그인**(또는 회원가입). 서버는 빌드 시 기본값 **`https://stock-quant-backend.onrender.com`** 입니다.  
   바꾸려면 로그인 화면 **「고급: 서버 주소」**를 사용합니다.
6. 대시보드 상단 **「모의 투자 테스트」** 순서대로: 브로커(모의) 등록 → Paper Trading 시작 → 대시보드에서 상태 확인.

---

## 3. Android APK 만들기 (EAS · Expo 계정 필요)

APK는 **Expo EAS 클라우드 빌드**로 만드는 것이 이 프로젝트의 기본 경로입니다.  
**Expo에 로그인하지 않은 상태**에서는 `eas build`를 실행할 수 없습니다.

### 준비

1. [expo.dev](https://expo.dev) 계정 생성  
2. PC에 로그인:

```bash
npm i -g eas-cli
eas login
```

3. 프로젝트 연결(최초 1회, `apps/mobile`에서):

```bash
cd C:\dev\stock-quant-trading\apps\mobile
npm install
eas build:configure
```

### APK 빌드 (내부 테스트용 프로필)

```bash
cd C:\dev\stock-quant-trading\apps\mobile
npm run build:android:apk
```

또는:

```bash
npx eas build --platform android --profile preview-apk
```

빌드가 끝나면 Expo 대시보드 또는 터미널에 **다운로드 URL**이 나옵니다. APK를 PC에 저장합니다.

### zip에 APK까지 넣기

```powershell
cd C:\dev\stock-quant-trading
.\scripts\package-client-install-zip.ps1 -ApkPath "C:\경로\다운로드한앱.apk"
```

다시 만들어진 `release\stock-quant-client-install.zip` 안에 **exe + apk**가 함께 들어갑니다.

---

## 4. Android — 다운로드 후 설치

1. 폰에서 APK 파일을 받습니다 (Drive 링크, 메신저, USB 등).
2. **설정 → 보안**(기기마다 이름 다름)에서 **출처를 알 수 없는 앱** 설치 허용(이 앱/파일 관리자에만 허용해도 됨).
3. APK 파일을 탭해 **설치**.
4. 앱 실행 → **로그인**. 백엔드는 프로필에 따라 Render 기본 URL이 주입됩니다.

---

## 5. 자주 묻는 것

**Q. zip에 exe만 있고 apk가 없어요.**  
A. 정상입니다. APK는 EAS 로그인 후 별도 빌드하고, `-ApkPath`로 zip에 넣습니다.

**Q. Windows 설치 파일이 안 만들어져요.**  
A. 저장소를 `C:\dev\stock-quant-trading`으로 복제(clone)한 뒤, 그 폴더에서 `npm run desktop:build:win` 을 다시 실행하세요.

**Q. 서버에 연결이 안 돼요.**  
A. 브라우저에서 `https://stock-quant-backend.onrender.com/api/health` 가 열리는지 확인하세요. 앱 로그인 화면의 「서버 연결」도 같은 주소를 씁니다.

---

## 6. 한 줄 요약

| 하고 싶은 것 | 할 일 |
|--------------|--------|
| PC에 설치 | zip 풀기 → `Stock Quant Desktop-Setup-*.exe` 실행 |
| 폰에 설치 | EAS로 APK 빌드 → 허용 후 APK 설치 (또는 zip에 APK 포함 후 공유) |
| zip 다시 만들기 | `C:\dev\stock-quant-trading`에서 `npm run desktop:build:win` 후 `npm run release:zip:clients` |
| 남에게 배포 | GitHub Releases 또는 클라우드에 zip 올리고 링크 공유 |
