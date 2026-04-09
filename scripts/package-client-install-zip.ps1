# Creates release/stock-quant-client-install.zip (Windows installer + README KO/EN UTF-8 BOM + optional APK).
# Run from repo root after: npm run desktop:build:win
# Use ASCII path (e.g. C:\dev\stock-quant-trading) for reliable electron-builder.
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

$stage = Join-Path $root "release\client-install-staging"
$outZip = Join-Path $root "release\stock-quant-client-install.zip"

New-Item -ItemType Directory -Force -Path (Split-Path $stage) | Out-Null
if (Test-Path $stage) {
  Remove-Item -Recurse -Force $stage
}
New-Item -ItemType Directory -Force -Path $stage | Out-Null

$dist = Join-Path $root "apps\desktop\dist"
$exes = @(Get-ChildItem -Path $dist -Filter "*.exe" -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike "*elevate*" })
$hasExe = $exes.Count -gt 0
$hasApk = $false

foreach ($x in $exes) {
  Copy-Item -LiteralPath $x.FullName -Destination $stage
  Write-Host "[package] copied $($x.Name)"
}

if ($ApkPath -and (Test-Path -LiteralPath $ApkPath)) {
  Copy-Item -LiteralPath $ApkPath -Destination $stage
  $hasApk = $true
  Write-Host "[package] copied APK $(Split-Path $ApkPath -Leaf)"
}

$banner = @"
=== Stock Quant client bundle ===
Generated (local time): $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
ZIP name: stock-quant-client-install.zip

Included in this folder:
$(if ($hasExe) { '- Windows: NSIS installer (.exe)' } else { '- Windows: NO .exe — run npm run desktop:build:win from an ASCII path (e.g. C:\dev\stock-quant-trading)' })
$(if ($hasApk) { '- Android: .apk file' } else { '- Android: NO .apk — requires eas login; see README-CLIENT-INSTALL-*.txt and scripts/release-templates/ANDROID-APK-BUILD-HINT.txt' })

---

"@

$koBody = Read-TemplateText "README-CLIENT-INSTALL-KO.txt"
if (-not $koBody) {
  $koBody = "README template missing: scripts/release-templates/README-CLIENT-INSTALL-KO.txt"
}
$enBody = Read-TemplateText "README-CLIENT-INSTALL-EN.txt"
if (-not $enBody) {
  $enBody = "README template missing: scripts/release-templates/README-CLIENT-INSTALL-EN.txt"
}

Write-Utf8BomFile -Path (Join-Path $stage "README-CLIENT-INSTALL-KO.txt") -Content ($banner + $koBody)
Write-Utf8BomFile -Path (Join-Path $stage "README-CLIENT-INSTALL-EN.txt") -Content ($banner + $enBody)

$mdSrc = Join-Path $root "Docs\client_install_download.md"
if (Test-Path -LiteralPath $mdSrc) {
  $md = [System.IO.File]::ReadAllText($mdSrc, [System.Text.UTF8Encoding]::new($false))
  Write-Utf8BomFile -Path (Join-Path $stage "client_install_download.md") -Content $md
}

if (Test-Path $outZip) {
  Remove-Item -Force $outZip
}
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $outZip -Force
Write-Host "[package] created $outZip" -ForegroundColor Green
