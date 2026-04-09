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
