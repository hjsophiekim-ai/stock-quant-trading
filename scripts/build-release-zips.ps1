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
$portableDir = $null
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
    try {
      $sha = (& git -C $root rev-parse HEAD 2>$null)
      if ($sha) { $env:GIT_COMMIT_SHA = $sha.Trim() }
    } catch {
      Remove-Item Env:GIT_COMMIT_SHA -ErrorAction SilentlyContinue
    }
    $env:BACKEND_URL = $BackendUrl
    $env:APP_ENV = $AppEnv
    npm run build:win
    $buildExit = $LASTEXITCODE
    $distLocalEarly = Join-Path $root "apps\desktop\dist"
    New-Item -ItemType Directory -Force -Path $distLocalEarly | Out-Null

    $candidates = @(Get-ChildItem -Path (Join-Path $work "dist") -Filter "*Setup*.exe" -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike "*uninstall*" })
    $bestSetup = $null
    if ($candidates.Count -ge 1) {
      $bestSetup = $candidates | Sort-Object Length -Descending | Select-Object -First 1
    }

    $minInstallerBytes = 10000000
    $setupOk = ($buildExit -eq 0) -and ($bestSetup -ne $null) -and ($bestSetup.Length -ge $minInstallerBytes)
    if ($setupOk) {
      # 임시 작업 폴더 삭제 전에 저장소 dist로 복사 (finally에서 $work 가 지워지면 exe 경로가 무효화됨)
      $copiedSetup = Join-Path $distLocalEarly $bestSetup.Name
      Copy-Item -LiteralPath $bestSetup.FullName -Destination $copiedSetup -Force
      $setupExe = Get-Item -LiteralPath $copiedSetup
      Write-Host "[release] saved installer to $($setupExe.FullName)" -ForegroundColor Cyan
    } else {
      $portableCandidate = Join-Path $work "dist\\win-unpacked"
      if (Test-Path -LiteralPath $portableCandidate) {
        $portableOut = Join-Path $distLocalEarly "win-unpacked"
        if (Test-Path $portableOut) { Remove-Item -Recurse -Force $portableOut -ErrorAction SilentlyContinue }
        Copy-Item -LiteralPath $portableCandidate -Destination $portableOut -Recurse -Force
        $portableDir = Get-Item -LiteralPath $portableOut
        $diag = ""
        if ($bestSetup -ne $null) { $diag = " (setup exe bytes=$($bestSetup.Length))" }
        Write-Warning "[release] NSIS installer build did not produce a valid installer (exit=$buildExit)$diag — packaging portable win-unpacked instead."
      } else {
        throw "Desktop build failed and no win-unpacked output found. buildExit=$buildExit"
      }
    }
  } finally {
    Pop-Location
    if ($work -and (Test-Path $work)) {
      Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
    }
  }
}

$deskStage = Join-Path $releaseDir "desktop-zip-staging"
if (Test-Path $deskStage) {
  $removed = $false
  for ($i = 0; $i -lt 3; $i++) {
    try {
      Remove-Item -Recurse -Force $deskStage -ErrorAction Stop
      $removed = $true
      break
    } catch {
      Start-Sleep -Milliseconds 600
    }
  }
  if (-not $removed) {
    try {
      $old = Join-Path $releaseDir ("desktop-zip-staging-old-" + [Guid]::NewGuid().ToString("n").Substring(0, 8))
      Move-Item -LiteralPath $deskStage -Destination $old -Force
    } catch {
      throw
    }
  }
}
New-Item -ItemType Directory -Force -Path $deskStage | Out-Null

$codeSignCert = $null
$signerCer = $null
try {
  $codeSignCert = Get-RequestedCodeSigningCert
  if (-not $setupExe) {
    Write-Host "[release] portable build (win-unpacked) — no installer signing step." -ForegroundColor Yellow
  } elseif ($codeSignCert) {
    Try-SignExecutable -ExePath $setupExe.FullName -Cert $codeSignCert
    $signerCer = Join-Path $deskStage "StockQuantDesktop-Signer.cer"
    Export-Certificate -Cert $codeSignCert -FilePath $signerCer | Out-Null
    $sigNow = Get-AuthenticodeSignature -FilePath $setupExe.FullName
    if ($sigNow.SignerCertificate) {
      Write-Host "[release] signed $($setupExe.Name) (signature status: $($sigNow.Status))" -ForegroundColor Green
    } else {
      Write-Warning "[release] signing did not attach a signer certificate."
    }
  } else {
    Write-Host "[release] no code signing configured (RELEASE_CODESIGN_*). ZIP will contain an unsigned installer." -ForegroundColor Yellow
  }
} catch {
  Write-Warning "[release] code signing failed: $($_.Exception.Message)"
}

$exeName = ""
$isPortable = $false
if ($setupExe) {
  Copy-Item -LiteralPath $setupExe.FullName -Destination $deskStage
  $exeName = $setupExe.Name
} else {
  $isPortable = $true
  $portableFolder = Join-Path $deskStage "StockQuantDesktop"
  if (Test-Path $portableFolder) { Remove-Item -Recurse -Force $portableFolder -ErrorAction SilentlyContinue }
  Copy-Item -LiteralPath $portableDir.FullName -Destination $portableFolder -Recurse -Force
  $exeName = "StockQuantDesktop\\StockQuantDesktop.exe"
}

$installBat = @"
@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "INSTALL-DESKTOP.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL-DESKTOP.ps1"
  exit /b %ERRORLEVEL%
)
start "" "$exeName"
"@
Write-Utf8BomFile -Path (Join-Path $deskStage "INSTALL-DESKTOP.bat") -Content $installBat

$installPs1 = @"
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (Test-Path -LiteralPath ".\UNBLOCK-FILES.ps1") {
  & ".\UNBLOCK-FILES.ps1" | Out-Null
}

if ((-not $isPortable) -and (Test-Path -LiteralPath ".\StockQuantDesktop-Signer.cer")) {
  try {
    Write-Host ""
    Write-Host "이 패키지에는 자체 서명 인증서(StockQuantDesktop-Signer.cer)가 포함되어 있습니다." -ForegroundColor Yellow
    Write-Host "Windows가 설치 파일을 차단하는 경우, 현재 사용자 인증서 저장소에 추가하면 차단이 완화될 수 있습니다." -ForegroundColor Yellow
    $ans = Read-Host "인증서를 추가할까요? (Y/N)"
    if ($ans -match '^(y|Y)$') {
      Import-Certificate -FilePath ".\StockQuantDesktop-Signer.cer" -CertStoreLocation "Cert:\CurrentUser\Root" | Out-Null
      Import-Certificate -FilePath ".\StockQuantDesktop-Signer.cer" -CertStoreLocation "Cert:\CurrentUser\TrustedPublisher" | Out-Null
    }
  } catch {
  }
}

Start-Process -FilePath ".\$exeName"
"@
Write-Utf8BomFile -Path (Join-Path $deskStage "INSTALL-DESKTOP.ps1") -Content $installPs1

$unblockPs1 = @"
Set-StrictMode -Version Latest
$ErrorActionPreference = "SilentlyContinue"
Set-Location -LiteralPath $PSScriptRoot
Get-ChildItem -LiteralPath $PSScriptRoot -Recurse -File | ForEach-Object {
  try { Unblock-File -LiteralPath $_.FullName } catch { }
}
"@
Write-Utf8BomFile -Path (Join-Path $deskStage "UNBLOCK-FILES.ps1") -Content $unblockPs1

$deskReadme = @"
Stock Quant Desktop — Windows 설치 패키지
버전: $version
빌드 시 백엔드 URL: $BackendUrl  (APP_ENV=$AppEnv)

설치 방법
1) 이 ZIP을 임의 폴더에 압축 해제합니다.
2) 다음 중 하나를 더블클릭합니다.
   - INSTALL-DESKTOP.bat  (권장)
   - $exeName

Windows 11 Smart App Control/SmartScreen 관련
- 설치 파일(.exe)이 "디지털 서명되지 않음/알 수 없는 게시자"로 차단될 수 있습니다.
- 가장 확실한 해결책은 상용 코드 서명 인증서(EV 권장)로 설치 파일에 서명해서 배포하는 것입니다.
- 이 ZIP에 StockQuantDesktop-Signer.cer 가 포함되어 있으면, INSTALL-DESKTOP.bat 가 인증서를 현재 사용자 저장소에 추가한 뒤 설치를 실행합니다.

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
