Stock Quant — Android 배포 패키지 (한글)
=========================================

이 ZIP은 Android 설치를 위한 패키지입니다.

포함될 수 있는 것
-----------------
• *.apk                    → 앱 설치 파일 (빌드해서 넣은 경우)
• README-ANDROID-PACKAGE-KO.txt / EN.txt → 안내
• ANDROID-APK-BUILD-HINT.txt → APK가 없을 때 빌드 절차 요약

이 폴더에 .apk 가 없다면
-------------------------
APK는 Expo EAS 클라우드 빌드로 만들며, Expo 계정 로그인이 필요합니다.
이 환경(CI/자동화)에서는 로그인 없이 APK를 만들 수 없는 경우가 많습니다.

다음을 개발자 PC(영문 경로 권장, 예: C:\dev\stock-quant-trading)에서 실행하세요:

  npm i -g eas-cli
  eas login
  cd apps\mobile
  npm install
  eas build:configure
  npm run build:android:apk

빌드가 끝나면 Expo가 준 다운로드 링크에서 APK를 받은 뒤:

  저장소 루트에서
  .\scripts\package-android-install-zip.ps1 -ApkPath "받은파일.apk"

또는 Windows+Android 통합 ZIP:

  .\scripts\package-client-install-zip.ps1 -ApkPath "받은파일.apk"


[APK가 있을 때] 설치 방법
--------------------------
1. 휴대폰에서 ZIP을 풀거나 APK만 전달받습니다.
2. 설정 → 보안 → 출처를 알 수 없는 앱 설치 허용 (기기마다 메뉴 이름이 다릅니다).
3. APK 파일을 눌러 설치합니다.
4. 앱 실행 → 로그인 (PC와 동일 계정 가능).
5. Broker Settings 에서 모의 계정 등록, Paper Trading 시작 등은 PC와 동일 흐름입니다.


[로그인·서버]
-------------
기본 API: https://stock-quant-backend.onrender.com (프로필에 따라 다를 수 있음)


문제 발생 시: Docs/beginner_client_download_install_ko.md

인코딩: UTF-8 (BOM)
