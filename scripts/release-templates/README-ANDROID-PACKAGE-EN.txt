Stock Quant — Android distribution package (English)
======================================================

This ZIP is for installing the Android app.

May include
-----------
• *.apk                    → Application package (if you built and added it)
• README-ANDROID-PACKAGE-KO/EN.txt → Guides
• ANDROID-APK-BUILD-HINT.txt → Short build steps when APK is missing

If there is NO .apk file
------------------------
APKs are normally built with Expo EAS (cloud). You need an Expo account and `eas login`.
Most automated environments cannot produce an APK without that login.

On a developer PC (use an ASCII path, e.g. C:\dev\stock-quant-trading):

  npm i -g eas-cli
  eas login
  cd apps\mobile
  npm install
  eas build:configure
  npm run build:android:apk

Download the APK from the Expo build page, then from repo root:

  .\scripts\package-android-install-zip.ps1 -ApkPath "C:\path\app.apk"

Or bundle into the combined Windows+Android ZIP:

  .\scripts\package-client-install-zip.ps1 -ApkPath "C:\path\app.apk"


[When you have an APK] Install on phone
---------------------------------------
1. Copy the APK to the phone (extract ZIP or share the file).
2. Settings → Security → allow install from unknown sources (wording varies).
3. Open the APK and install.
4. Launch the app and sign in (same account as desktop is OK).
5. Broker Settings (paper) and Paper Trading flow matches the desktop app.


Default API: https://stock-quant-backend.onrender.com (may vary by build profile)

Troubleshooting: Docs/beginner_client_download_install_ko.md

Encoding: UTF-8 with BOM
