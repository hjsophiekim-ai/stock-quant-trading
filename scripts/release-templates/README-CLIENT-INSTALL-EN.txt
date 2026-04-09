Stock Quant — Client install guide (English)
==============================================

What may be inside this ZIP
---------------------------
• Stock Quant Desktop-Setup-*.exe  → Windows installer (NSIS)
• *.apk                           → Android app (only if you added it)
• README-CLIENT-INSTALL-KO.txt    → Korean guide
• README-CLIENT-INSTALL-EN.txt    → This file (English)
• client_install_download.md      → How to publish/download (Markdown)

If you do NOT see an .apk file: Android APK was not bundled in this package.
See "Build Android APK" below, or use release/stock-quant-android-install.zip if provided.


[Windows] Install
-----------------
1. Extract the ZIP.
2. Double-click Stock Quant Desktop-Setup-*.exe.
3. Follow the installer.
4. Launch "Stock Quant Desktop" from Desktop or Start Menu.


[Sign in]
---------
1. Use Login (or Register on first run).
2. Default API URL is baked into the build (usually https://stock-quant-backend.onrender.com).
3. Use "Advanced: server URL" only if you need a different backend.
4. Check "Server status" uses GET /api/health.


[Broker Settings] KIS paper account
-------------------------------------
1. Open Broker Settings from the sidebar.
2. Enter and save Korea Investment & Securities Open API keys and paper account.
3. Run "Test connection" until token issuance succeeds.


[Paper Trading]
---------------
1. Open Paper Trading.
2. When gates are OK, press Start for the paper session.
3. Return to Dashboard and confirm runtime, positions, and fills update.


[Dashboard checklist]
---------------------
• Risk banner, mode (e.g. paper)
• Runtime engine, heartbeat
• Market regime, screener candidates
• Positions, open orders, recent fills
• Performance screen for PnL


[Troubleshooting]
-----------------
• Check firewall/antivirus blocking the installer or app.
• Open https://stock-quant-backend.onrender.com/api/health in a browser.
• Rebuild Windows installer from an ASCII path such as C:\dev\stock-quant-trading (avoid cloud-sync folders).
• Docs: Docs/beginner_client_download_install_ko.md (Korean), Docs/deployment_mobile.md


[Build Android APK] (developer machine)
---------------------------------------
1. npm i -g eas-cli && eas login (Expo account)
2. cd apps/mobile && npm install
3. First time: eas build:configure
4. npm run build:android:apk
5. To bundle APK into the client ZIP (repo root):
   .\scripts\package-client-install-zip.ps1 -ApkPath "C:\path\app.apk"
   Android-only ZIP:
   .\scripts\package-android-install-zip.ps1 -ApkPath "C:\path\app.apk"


Encoding: UTF-8 with BOM — readable in Windows Notepad.
