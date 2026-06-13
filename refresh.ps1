# Refresh the Training Coach after dropping new WKO5 exports into "WKO5 Exports\".
#
# Usage:  .\refresh.ps1          (from the Training Coach folder)
#
# 1. Rebuilds slice0\wko.db from the exports (full validation, data_flags re-stamped)
# 2. Restarts the unified backend on :8000 so the dashboard + coach see the new data
#
# Workflow in WKO5: re-export the current-year files (Training History, PMC Report,
# Daily TiZ) and let them REPLACE the existing files of the same name. Weekly
# "Week of ..." snapshots are used for validation only — PMC/TiZ inside them are
# never ingested, so don't rely on weekly files to carry new data.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = "C:\Users\mkarl\OneDrive\Documents\.venv-tc\Scripts\python.exe"

Write-Host "=== 1/2 Rebuilding dataset from WKO5 Exports ===" -ForegroundColor Cyan
Set-Location (Join-Path $root "slice0")
& $py build.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Build reported issues - backend NOT restarted. Fix the FAIL lines above." -ForegroundColor Red
    exit 1
}

Write-Host "`n=== 2/2 Restarting backend on :8000 ===" -ForegroundColor Cyan
$conns = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
    try { Stop-Process -Id $c.OwningProcess -Force -Confirm:$false } catch {}
}
Start-Sleep -Seconds 2

$env:ANTHROPIC_API_KEY = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "User")
Set-Location (Join-Path $root "app")
Start-Process -WindowStyle Hidden -FilePath $py `
    -ArgumentList "-m", "uvicorn", "api.main:app", "--port", "8000", "--host", "127.0.0.1" `
    -RedirectStandardOutput "$env:TEMP\tc_api.log" -RedirectStandardError "$env:TEMP\tc_api.err"
Start-Sleep -Seconds 12

try {
    $meta = Invoke-RestMethod "http://127.0.0.1:8000/api/meta"
    Write-Host "Backend up. Data now through $($meta.date_max)  (board: $($meta.board_status))" -ForegroundColor Green
    Write-Host "Dashboard: http://127.0.0.1:5179"
} catch {
    Write-Host "Backend failed to start - last errors:" -ForegroundColor Red
    Get-Content "$env:TEMP\tc_api.err" -Tail 10
    exit 1
}
