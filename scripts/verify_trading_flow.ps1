# 저장소 루트에서 실행하세요. (.env 에 KIS 키·계좌가 있어야 하는 단계는 실패할 수 있습니다.)
# Usage: .\scripts\verify_trading_flow.ps1
# Optional: $env:BACKEND_URL = "http://127.0.0.1:8000"

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

Write-Host "== [1] 단위 테스트 (LiveBroker 조회·로컬 종목 검색) ==" -ForegroundColor Cyan
python -m pytest tests/test_live_broker_reads.py tests/test_local_symbol_catalog.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`n== [2] 백엔드 API (서버가 떠 있을 때) 국내 종목 빠른 찾기 ==" -ForegroundColor Cyan
$base = if ($env:BACKEND_URL) { $env:BACKEND_URL.TrimEnd("/") } else { "http://127.0.0.1:8000" }
try {
  $n = "$base/api/stocks/search-by-name?q=" + [uri]::EscapeDataString("삼성") + "&limit=10"
  Write-Host "[search-by-name]" -ForegroundColor DarkGray
  Invoke-RestMethod -Uri $n -Method Get | ConvertTo-Json -Depth 4
  $s = "$base/api/stocks/search-by-symbol?q=00593&limit=10"
  Write-Host "[search-by-symbol]" -ForegroundColor DarkGray
  Invoke-RestMethod -Uri $s -Method Get | ConvertTo-Json -Depth 4
  $c = "$base/api/stocks/strategy-candidates?strategy_id=swing_v1"
  Write-Host "[strategy-candidates]" -ForegroundColor DarkGray
  Invoke-RestMethod -Uri $c -Method Get | ConvertTo-Json -Depth 6
} catch {
  Write-Warning "백엔드가 꺼져 있거나 URL이 다릅니다: $base — $($_.Exception.Message)"
}

Write-Host "`n== [3] KIS 스크립트 ( .env 필요 ) ==" -ForegroundColor Cyan
Write-Host "  python scripts\check_kis_connection.py"
Write-Host "  python scripts\check_kis_quote.py"
Write-Host "  python scripts\check_kis_order_mock.py --step all"
Write-Host "(실전 LiveBroker 미체결/체결은 위 단위 테스트와 실계좌 환경에서 확인)"
