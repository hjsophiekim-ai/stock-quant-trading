Stock Quant — 클라이언트 설치 안내 (한글)
==========================================

이 ZIP에 포함될 수 있는 파일
----------------------------
• Stock Quant Desktop-Setup-*.exe  → Windows 설치 프로그램
• *.apk                           → Android 앱 (빌드해 넣은 경우에만)
• README-CLIENT-INSTALL-KO.txt    → 이 파일 (한글)
• README-CLIENT-INSTALL-EN.txt    → 영문 안내
• client_install_download.md      → 배포·다운로드 방법 (Markdown)

APK가 보이지 않으면: 이 패키지에 Android APK는 아직 포함되지 않은 것입니다.
아래 「Android APK 만들기」를 참고하거나, release/stock-quant-android-install.zip 을 함께 받으세요.


[Windows] 설치 방법
-------------------
1. ZIP 압축을 풉니다.
2. Stock Quant Desktop-Setup-*.exe 를 더블 클릭합니다.
3. 설치 마법사 안내에 따라 진행합니다.
4. 바탕화면 또는 시작 메뉴에서 "Stock Quant Desktop" 을 실행합니다.


[로그인]
--------
1. 앱이 열리면 로그인 화면이 나옵니다.
2. 계정이 없으면 회원가입(Register) 후 로그인합니다.
3. 기본 서버 주소는 빌드 시 박힌 값입니다 (보통 https://stock-quant-backend.onrender.com).
4. 서버를 바꿀 때만 로그인 화면의 「고급: 서버 주소」를 사용합니다.
5. 상단 「서버 연결」이 정상인지 확인합니다 (/api/health).


[Broker Settings] 한국투자 모의 계정
-------------------------------------
1. 사이드 메뉴에서 Broker Settings 로 이동합니다.
2. 한국투자 Open API 키와 모의투자 계좌 정보를 입력·저장합니다.
3. 「연결 테스트」로 토큰 발급이 성공하는지 확인합니다.


[Paper Trading] 모의 자동매매
-----------------------------
1. Paper Trading 화면으로 이동합니다.
2. 조건이 충족되면 「시작」으로 모의 세션을 시작합니다.
3. 대시보드로 돌아와 갱신되면서 런타임·포지션·체결 등이 보이는지 확인합니다.


[대시보드에서 확인할 것]
------------------------
• 리스크 배너, 현재 모드(paper 등)
• 런타임 엔진 상태, 하트비트
• 시장 국면·스크리너 후보
• 보유 포지션, 미체결, 최근 체결
• Performance 화면에서 손익·지표


[문제가 생기면]
---------------
• PC 방화벽·백신이 설치/연결을 막는지 확인합니다.
• 브라우저에서 https://stock-quant-backend.onrender.com/api/health 가 열리는지 확인합니다.
• Windows 빌드는 한글/클라우드 동기화 폴더가 아닌 C:\dev\stock-quant-trading 같은 경로에서 다시 빌드하는 것이 안전합니다.
• 자세한 문서: 저장소의 Docs/beginner_client_download_install_ko.md


[Android APK 만들기] (개발자 PC)
---------------------------------
1. npm i -g eas-cli 후 eas login (Expo 계정)
2. cd apps/mobile && npm install
3. 최초 1회: eas build:configure
4. npm run build:android:apk
5. 받은 APK를 패키지에 넣으려면 저장소 루트에서:
   .\scripts\package-client-install-zip.ps1 -ApkPath "C:\경로\앱.apk"
   또는 Android 전용 zip: .\scripts\package-android-install-zip.ps1 -ApkPath "..."


※ README 인코딩: UTF-8 (BOM). Windows 메모장에서도 한글이 깨지지 않아야 합니다.
