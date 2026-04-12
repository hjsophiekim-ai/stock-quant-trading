# Builds desktop NSIS installer in %TEMP% (Google Drive paths break npm/node_modules),
# then creates two ZIPs under release/:
#   - Stock-Quant-Desktop-Windows-<version>.zip  (Setup.exe + double-click install.bat + readme)
#   - Stock-Quant-Android-<version>.zip          (.apk if -ApkPath, else EAS build hints)
#
# Usage (repo root):
#   .\scripts\build-release-zips.ps1
#   .\scripts\build-release-zips.ps1 -BackendUrl "https://api.example.com"
#   .\scripts\build-release-zips.ps1 -DesktopExePath "C:\path\Stock Quant Desktop-Setup-0.1.0.exe" -ApkPath "C:\path\app.apk"

param(
  [string]$BackendUrl = "https://stock-quant-backend.onrender.com",
  [string]$AppEnv = "production",
  [string]$DesktopExePath = "",
  [string]$ApkPath = ""
)

$ErrorActionPreference = "Stop"

function Write-Utf8BomFile {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Content
  )
  $enc = New-Object System.Text.UTF8Encoding $true
  $normalized = $Content -replace "`r`n|`n|`r", "`r`n"
  [System.IO.File]::WriteAllText($Path, $normalized, $enc)
}

function Read-TemplateText {
  param([Parameter(Mandatory = $true)][string]$Name)
  $p = Join-Path $PSScriptRoot "release-templates\$Name"
  if (-not (Test-Path -LiteralPath $p)) { return "" }
  return [System.IO.File]::ReadAllText($p, [System.Text.UTF8Encoding]::new($false))
}

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

$releaseDir = Join-Path $root "release"
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null

$desktopPkg = Get-Content -Raw (Join-Path $root "apps\desktop\package.json") | ConvertFrom-Json
$version = $desktopPkg.version
$mobilePkg = Get-Content -Raw (Join-Path $root "apps\mobile\package.json") | ConvertFrom-Json
if ($mobilePkg.version -ne $version) {
  Write-Warning "[release] apps/desktop version ($version) and apps/mobile version ($($mobilePkg.version)) differ — using desktop version in ZIP names."
}

$npmCache = Join-Path $env:TEMP "npm-cache-sq-release"
New-Item -ItemType Directory -Force -Path $npmCache | Out-Null

$setupExe = $null
if ($DesktopExePath -and (Test-Path -LiteralPath $DesktopExePath)) {
  $setupExe = Get-Item -LiteralPath $DesktopExePath
  Write-Host "[release] using existing installer: $($setupExe.FullName)" -ForegroundColor Cyan
} else {
  $work = Join-Path $env:TEMP ("sq-desktop-release-" + [Guid]::NewGuid().ToString("n").Substring(0, 12))
  Write-Host "[release] building desktop in $work (avoids Google Drive npm issues)..." -ForegroundColor Cyan
  try {
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    robocopy (Join-Path $root "apps\desktop") $work /E /XD node_modules dist .git /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit $LASTEXITCODE" }
    Push-Location $work
    npm install --cache $npmCache
    $env:BACKEND_URL = $BackendUrl
    $env:APP_ENV = $AppEnv
    npm run build:win
    $candidates = @(Get-ChildItem -Path (Join-Path $work "dist") -Filter "*Setup*.exe" -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike "*uninstall*" })
    if ($candidates.Count -lt 1) { throw "No *Setup*.exe found under dist after build." }
    # 임시 작업 폴더 삭제 전에 저장소 dist로 복사 (finally에서 $work 가 지워지면 exe 경로가 무효화됨)
    $distLocalEarly = Join-Path $root "apps\desktop\dist"
    New-Item -ItemType Directory -Force -Path $distLocalEarly | Out-Null
    $copiedSetup = Join-Path $distLocalEarly $candidates[0].Name
    Copy-Item -LiteralPath $candidates[0].FullName -Destination $copiedSetup -Force
    $setupExe = Get-Item -LiteralPath $copiedSetup
    Write-Host "[release] saved installer to $($setupExe.FullName)" -ForegroundColor Cyan
  } finally {
    Pop-Location
    if ($work -and (Test-Path $work)) {
      Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
    }
  }
}

$deskStage = Join-Path $releaseDir "desktop-zip-staging"
if (Test-Path $deskStage) { Remove-Item -Recurse -Force $deskStage }
New-Item -ItemType Directory -Force -Path $deskStage | Out-Null

Copy-Item -LiteralPath $setupExe.FullName -Destination $deskStage
$exeName = $setupExe.Name

$installBat = @"
@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "" "$exeName"
"@
Write-Utf8BomFile -Path (Join-Path $deskStage "INSTALL-DESKTOP.bat") -Content $installBat

$deskReadme = @"
Stock Quant Desktop — Windows 설치 패키지
버전: $version
빌드 시 백엔드 URL: $BackendUrl  (APP_ENV=$AppEnv)

설치 방법
1) 이 ZIP을 임의 폴더에 압축 해제합니다.
2) 다음 중 하나를 더블클릭합니다.
   - INSTALL-DESKTOP.bat  (설치 마법사 실행)
   - $exeName  (동일)

자세한 안내: README-KO.txt

참고: 이 설치 파일은 Electron 클라이언트만 포함합니다. API 서버(FastAPI 백엔드)는 별도로 실행하거나,
운영 중인 서버 URL로 다시 빌드한 설치 파일을 사용하세요.
"@
Write-Utf8BomFile -Path (Join-Path $deskStage "README-KO.txt") -Content $deskReadme

$deskZip = Join-Path $releaseDir "Stock-Quant-Desktop-Windows-$version.zip"
if (Test-Path $deskZip) { Remove-Item -Force $deskZip }
Compress-Archive -Path (Join-Path $deskStage "*") -DestinationPath $deskZip -Force
Write-Host "[release] created $deskZip" -ForegroundColor Green

$distLocal = Join-Path $root "apps\desktop\dist"
try {
  New-Item -ItemType Directory -Force -Path $distLocal | Out-Null
  $distResolved = (Resolve-Path -LiteralPath $distLocal).Path
  if ($setupExe.DirectoryName -ne $distResolved) {
    Copy-Item -LiteralPath $setupExe.FullName -Destination $distLocal -Force
    Write-Host "[release] copied installer to $distLocal" -ForegroundColor DarkGray
  }
} catch {
  Write-Warning "[release] could not copy installer to apps/desktop/dist (sync folder?): $($_.Exception.Message)"
}

$apkStage = Join-Path $releaseDir "android-zip-staging"
if (Test-Path $apkStage) { Remove-Item -Recurse -Force $apkStage }
New-Item -ItemType Directory -Force -Path $apkStage | Out-Null

$hasApk = $false
if ($ApkPath -and (Test-Path -LiteralPath $ApkPath)) {
  Copy-Item -LiteralPath $ApkPath -Destination $apkStage
  $hasApk = $true
  Write-Host "[release] included APK $(Split-Path $ApkPath -Leaf)" -ForegroundColor Cyan
} else {
  Write-Host "[release] no -ApkPath — Android ZIP will contain build instructions only (this PC has no Android SDK / no EAS token)." -ForegroundColor Yellow
}

$hint = Read-TemplateText "ANDROID-APK-BUILD-HINT.txt"
if (-not $hint) { $hint = "See apps/mobile eas.json and npm run build:android:apk (EAS login required)." }
Write-Utf8BomFile -Path (Join-Path $apkStage "ANDROID-APK-BUILD-HINT.txt") -Content $hint

$koBody = Read-TemplateText "README-ANDROID-PACKAGE-KO.txt"
$enBody = Read-TemplateText "README-ANDROID-PACKAGE-EN.txt"
if (-not $koBody) { $koBody = "Template missing." }
if (-not $enBody) { $enBody = "Template missing." }

$apkBanner = @"
=== Stock Quant Android ($version) ===
Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
$(if ($hasApk) { 'APK included — transfer to phone and open to install (allow unknown sources if prompted).' } else { 'APK not included on this machine — follow ANDROID-APK-BUILD-HINT.txt (EAS or Android Studio).' })

"@
Write-Utf8BomFile -Path (Join-Path $apkStage "README-ANDROID-PACKAGE-KO.txt") -Content ($apkBanner + $koBody)
Write-Utf8BomFile -Path (Join-Path $apkStage "README-ANDROID-PACKAGE-EN.txt") -Content ($apkBanner + $enBody)

if ($hasApk) {
  $apkReadmeKo = @"
Stock Quant Trader — Android
버전: $version

설치 방법
1) ZIP 압축을 풉니다.
2) .apk 파일을 휴대폰으로 옮깁니다 (USB, 메일, 클라우드 등).
3) 휴대폰에서 APK를 탭해 설치합니다. (출처를 알 수 없는 앱 허용이 필요할 수 있습니다.)
"@
} else {
  $apkReadmeKo = @"
Stock Quant Trader — Android
버전: $version

이 PC에서는 APK 파일을 만들 수 없었습니다 (Android SDK 또는 EAS 로그인 필요).
ANDROID-APK-BUILD-HINT.txt 와 README-ANDROID-PACKAGE-*.txt 를 참고해 APK를 만든 뒤,
다시 실행하세요:

  .\scripts\build-release-zips.ps1 -ApkPath "C:\다운로드\your.apk"

또는 apps/mobile 에서:
  npm run build:android:apk
"@
}
Write-Utf8BomFile -Path (Join-Path $apkStage "README-PHONE-KO.txt") -Content $apkReadmeKo

$apkZip = Join-Path $releaseDir "Stock-Quant-Android-$version.zip"
if (Test-Path $apkZip) { Remove-Item -Force $apkZip }
Compress-Archive -Path (Join-Path $apkStage "*") -DestinationPath $apkZip -Force
Write-Host "[release] created $apkZip" -ForegroundColor Green

Write-Host ""
Write-Host "Done. Output files:" -ForegroundColor Green
Write-Host "  $deskZip"
Write-Host "  $apkZip"
