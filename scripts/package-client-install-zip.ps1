# Creates release/stock-quant-client-install.zip with Windows installer + readme.
# Run from repo root after: npm run desktop:build:win
# Optional: -ApkPath "C:\path\app.apk" to include Android APK

param(
  [string]$ApkPath = ""
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

$stage = Join-Path $root "release\client-install-staging"
$outZip = Join-Path $root "release\stock-quant-client-install.zip"

New-Item -ItemType Directory -Force -Path (Split-Path $stage) | Out-Null
if (Test-Path $stage) {
  Remove-Item -Recurse -Force $stage
}
New-Item -ItemType Directory -Force -Path $stage | Out-Null

$dist = Join-Path $root "apps\desktop\dist"
$exes = Get-ChildItem -Path $dist -Filter "*.exe" -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike "*elevate*" }

if (-not $exes -or $exes.Count -eq 0) {
  Write-Host "[package] No NSIS .exe found under apps\desktop\dist. Run first: npm run desktop:build:win" -ForegroundColor Yellow
  $readme = @"
Stock Quant — 클라이언트 설치 패키지
=====================================

이 zip을 받으셨지만 Windows 설치 파일(.exe)이 없습니다.

개발자 PC에서 저장소 루트에서 다음을 실행한 뒤 이 스크립트를 다시 실행하세요.

  npm run desktop:install
  npm run desktop:build:win
  .\scripts\package-client-install-zip.ps1

Android APK는 EAS 빌드 후 -ApkPath 로 지정하거나, 이 폴더에 .apk 를 넣고 스크립트를 수정해 복사하세요.

자세한 다운로드·배포: Docs/client_install_download.md
"@
  $readme | Out-File -FilePath (Join-Path $stage "README-CLIENT-INSTALL-KO.txt") -Encoding utf8
} else {
  foreach ($x in $exes) {
    Copy-Item -LiteralPath $x.FullName -Destination $stage
    Write-Host "[package] copied $($x.Name)"
  }
  $readme = @"
Stock Quant — 클라이언트 설치 요약
===================================

Windows
-------
1) Stock Quant Desktop-Setup-*.exe 실행
2) 설치 후 앱 실행 → 로그인
3) 대시보드 상단 「모의 투자 테스트」 순서: 브로커(모의) 등록 → Paper Trading 시작 → 대시보드에서 국면·후보·포지션·체결 확인
4) Performance 화면에서 손익·지표

Android (apk 파일이 이 zip에 포함된 경우)
------------------------------------------
1) 설정 → 보안 → 알 수 없는 앱 설치 허용 (기기마다 메뉴 이름 다름)
2) APK 탭하여 설치
3) 동일 계정으로 로그인 후 대시보드 탭에서 확인

백엔드 URL
----------
기본: https://stock-quant-backend.onrender.com (빌드 시 주입값)

다운로드를 인터넷에 올리는 방법: Docs/client_install_download.md
"@
  $readme | Out-File -FilePath (Join-Path $stage "README-CLIENT-INSTALL-KO.txt") -Encoding utf8
}

if ($ApkPath -and (Test-Path -LiteralPath $ApkPath)) {
  Copy-Item -LiteralPath $ApkPath -Destination $stage
  Write-Host "[package] copied APK $(Split-Path $ApkPath -Leaf)"
}

Copy-Item -LiteralPath (Join-Path $root "Docs\client_install_download.md") -Destination (Join-Path $stage "client_install_download.md") -ErrorAction SilentlyContinue

if (Test-Path $outZip) {
  Remove-Item -Force $outZip
}
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $outZip -Force
Write-Host "[package] created $outZip" -ForegroundColor Green
