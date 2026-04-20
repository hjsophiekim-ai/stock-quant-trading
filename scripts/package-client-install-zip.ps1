# Creates release/stock-quant-client-install.zip (Windows installer + README KO/EN UTF-8 BOM + optional APK).
# Run from repo root after: npm run desktop:build:win
# Use ASCII path (e.g. C:\dev\stock-quant-trading) for reliable electron-builder.
# Optional: -ApkPath "C:\path\app.apk"

param(
  [string]$ApkPath = ""
)

$ErrorActionPreference = "Stop"

function Get-RequestedCodeSigningCert {
  $thumb = $env:RELEASE_CODESIGN_THUMBPRINT
  if ($thumb) {
    $t = ($thumb -replace '\s', '').ToUpperInvariant()
    $c = Get-Item -LiteralPath ("Cert:\CurrentUser\My\" + $t) -ErrorAction SilentlyContinue
    if (-not $c) { throw "RELEASE_CODESIGN_THUMBPRINT not found in Cert:\\CurrentUser\\My: $t" }
    return $c
  }

  $pfx = $env:RELEASE_CODESIGN_PFX_PATH
  if ($pfx) {
    if (-not (Test-Path -LiteralPath $pfx)) { throw "RELEASE_CODESIGN_PFX_PATH not found: $pfx" }
    $pw = $env:RELEASE_CODESIGN_PFX_PASSWORD
    if (-not $pw) { throw "RELEASE_CODESIGN_PFX_PASSWORD is required when RELEASE_CODESIGN_PFX_PATH is set." }
    $secure = ConvertTo-SecureString -String $pw -AsPlainText -Force
    $imported = Import-PfxCertificate -FilePath $pfx -Password $secure -CertStoreLocation "Cert:\CurrentUser\My"
    if (-not $imported) { throw "Failed to import PFX: $pfx" }
    return $imported
  }

  if ($env:RELEASE_CODESIGN_SELF_SIGN -eq "true") {
    return New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=Stock Quant Desktop (Dev)" -CertStoreLocation "Cert:\CurrentUser\My" -KeyAlgorithm RSA -KeyLength 2048 -HashAlgorithm SHA256
  }

  return $null
}

function Try-SignExecutable {
  param(
    [Parameter(Mandatory = $true)][string]$ExePath,
    [Parameter(Mandatory = $true)][System.Security.Cryptography.X509Certificates.X509Certificate2]$Cert
  )

  $sig = Get-AuthenticodeSignature -FilePath $ExePath
  if ($sig.Status -eq "Valid") { return }

  try {
    $ts = $env:RELEASE_CODESIGN_TIMESTAMP_SERVER
    if (-not $ts) { $ts = "http://timestamp.digicert.com" }
    $r = Set-AuthenticodeSignature -FilePath $ExePath -Certificate $Cert -HashAlgorithm SHA256 -TimestampServer $ts
    if (-not $r.SignerCertificate) { throw $r.StatusMessage }
  } catch {
    $r2 = Set-AuthenticodeSignature -FilePath $ExePath -Certificate $Cert -HashAlgorithm SHA256
    if (-not $r2.SignerCertificate) { throw $r2.StatusMessage }
  }
}

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

$codeSignCert = $null
try {
  $codeSignCert = Get-RequestedCodeSigningCert
  if ($codeSignCert) {
    $cerOut = Join-Path $stage "StockQuantDesktop-Signer.cer"
    Export-Certificate -Cert $codeSignCert -FilePath $cerOut | Out-Null
  }
} catch {
  Write-Warning "[package] code signing init failed: $($_.Exception.Message)"
}

foreach ($x in $exes) {
  try {
    if ($codeSignCert) { Try-SignExecutable -ExePath $x.FullName -Cert $codeSignCert }
  } catch {
    Write-Warning "[package] code signing failed for $($x.Name): $($_.Exception.Message)"
  }
  Copy-Item -LiteralPath $x.FullName -Destination $stage
  Write-Host "[package] copied $($x.Name)"
}

$unblockPs1 = @"
Set-StrictMode -Version Latest
$ErrorActionPreference = "SilentlyContinue"
Set-Location -LiteralPath $PSScriptRoot
Get-ChildItem -LiteralPath $PSScriptRoot -Recurse -File | ForEach-Object {
  try { Unblock-File -LiteralPath $_.FullName } catch { }
}
"@
Write-Utf8BomFile -Path (Join-Path $stage "UNBLOCK-FILES.ps1") -Content $unblockPs1

$installPs1 = @"
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (Test-Path -LiteralPath ".\UNBLOCK-FILES.ps1") {
  & ".\UNBLOCK-FILES.ps1" | Out-Null
}

if (Test-Path -LiteralPath ".\StockQuantDesktop-Signer.cer") {
  try {
    Write-Host ""
    Write-Host "이 번들에는 자체 서명 인증서(StockQuantDesktop-Signer.cer)가 포함되어 있습니다." -ForegroundColor Yellow
    Write-Host "Windows가 설치 파일을 차단하는 경우, 현재 사용자 인증서 저장소에 추가하면 차단이 완화될 수 있습니다." -ForegroundColor Yellow
    $ans = Read-Host "인증서를 추가할까요? (Y/N)"
    if ($ans -match '^(y|Y)$') {
      Import-Certificate -FilePath ".\StockQuantDesktop-Signer.cer" -CertStoreLocation "Cert:\CurrentUser\Root" | Out-Null
      Import-Certificate -FilePath ".\StockQuantDesktop-Signer.cer" -CertStoreLocation "Cert:\CurrentUser\TrustedPublisher" | Out-Null
    }
  } catch {
  }
}

$setup = Get-ChildItem -LiteralPath $PSScriptRoot -Filter "*Setup*.exe" | Select-Object -First 1
if (-not $setup) { throw "No *Setup*.exe found in this folder." }
Start-Process -FilePath $setup.FullName
"@
Write-Utf8BomFile -Path (Join-Path $stage "INSTALL-WINDOWS.ps1") -Content $installPs1

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
