# Creates release/stock-quant-android-install.zip (Android-focused; optional APK).
# When APK is missing, readmes explain eas login and build steps.
# Optional: -ApkPath "C:\path\app.apk"

param(
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
  if (-not (Test-Path -LiteralPath $p)) {
    return ""
  }
  return [System.IO.File]::ReadAllText($p, [System.Text.UTF8Encoding]::new($false))
}

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

$stage = Join-Path $root "release\android-install-staging"
$outZip = Join-Path $root "release\stock-quant-android-install.zip"

New-Item -ItemType Directory -Force -Path (Split-Path $stage) | Out-Null
if (Test-Path $stage) {
  Remove-Item -Recurse -Force $stage
}
New-Item -ItemType Directory -Force -Path $stage | Out-Null

$hasApk = $false
if ($ApkPath -and (Test-Path -LiteralPath $ApkPath)) {
  Copy-Item -LiteralPath $ApkPath -Destination $stage
  $hasApk = $true
  Write-Host "[package-android] copied APK $(Split-Path $ApkPath -Leaf)"
} else {
  Write-Host "[package-android] No APK path given or file missing — creating documentation-only android zip" -ForegroundColor Yellow
}

$apkDropDir = Join-Path $stage "APK"
New-Item -ItemType Directory -Force -Path $apkDropDir | Out-Null
$apkDropTxt = @"
APK가 이 ZIP에 포함되지 않은 경우, 아래 경로에 APK를 넣어두면 설치 스크립트가 자동 탐지합니다:

  $(Split-Path $apkDropDir -Leaf)\your-app.apk

예: APK\StockQuant.apk
"@
Write-Utf8BomFile -Path (Join-Path $apkDropDir "PLACE-APK-HERE.txt") -Content $apkDropTxt

$installAndroid = @"
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Find-Apk {
  $apk = Get-ChildItem -File -Filter "*.apk" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($apk) { return $apk.FullName }
  if (Test-Path -LiteralPath ".\APK") {
    $apk2 = Get-ChildItem -LiteralPath ".\APK" -File -Filter "*.apk" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($apk2) { return $apk2.FullName }
  }
  return ""
}

$apkPath = Find-Apk
if (-not $apkPath) {
  Write-Host "APK를 찾지 못했습니다. 이 폴더 또는 .\APK 폴더에 *.apk 를 넣어주세요." -ForegroundColor Yellow
  exit 2
}

$adb = Get-Command adb -ErrorAction SilentlyContinue
if (-not $adb) {
  Write-Host "adb를 찾지 못했습니다. Android SDK Platform-Tools 설치 후 PATH에 adb를 추가하세요." -ForegroundColor Yellow
  Write-Host "APK 위치: $apkPath"
  exit 3
}

Write-Host "Installing APK via adb: $apkPath" -ForegroundColor Cyan
& adb devices
& adb install -r $apkPath
"@
Write-Utf8BomFile -Path (Join-Path $stage "INSTALL-ANDROID.ps1") -Content $installAndroid

$hint = Read-TemplateText "ANDROID-APK-BUILD-HINT.txt"
Write-Utf8BomFile -Path (Join-Path $stage "ANDROID-APK-BUILD-HINT.txt") -Content $hint

$banner = @"
=== Stock Quant Android bundle ===
Generated (local time): $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
ZIP name: stock-quant-android-install.zip

$(if ($hasApk) { 'This folder includes an .apk file.' } else { 'This folder does NOT include an .apk yet — see ANDROID-APK-BUILD-HINT.txt and README below.' })

---

"@

$koBody = Read-TemplateText "README-ANDROID-PACKAGE-KO.txt"
$enBody = Read-TemplateText "README-ANDROID-PACKAGE-EN.txt"
if (-not $koBody) { $koBody = "Template missing: README-ANDROID-PACKAGE-KO.txt" }
if (-not $enBody) { $enBody = "Template missing: README-ANDROID-PACKAGE-EN.txt" }

Write-Utf8BomFile -Path (Join-Path $stage "README-ANDROID-PACKAGE-KO.txt") -Content ($banner + $koBody)
Write-Utf8BomFile -Path (Join-Path $stage "README-ANDROID-PACKAGE-EN.txt") -Content ($banner + $enBody)

if (Test-Path $outZip) {
  Remove-Item -Force $outZip
}
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $outZip -Force
Write-Host "[package-android] created $outZip" -ForegroundColor Green
