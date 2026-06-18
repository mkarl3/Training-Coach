# Watt Smith — launch both servers in their own windows, then open the app.
# Usage: right-click -> "Run with PowerShell", or in a terminal:  .\run.ps1
$root = $PSScriptRoot
$py   = "C:\Users\mkarl\OneDrive\Documents\.venv-tc\Scripts\python.exe"
$key  = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "User")

# Backend (FastAPI on :8000) — its own window so it stays up independent of any tool/session.
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "`$env:ANTHROPIC_API_KEY='$key'; Set-Location '$root\app'; & '$py' -m uvicorn api.main:app --port 8000 --host 127.0.0.1"
)

# Frontend (Vite on :5179) — its own window.
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "Set-Location '$root\app\frontend'; npm run dev"
)

Start-Sleep -Seconds 5
Start-Process "http://localhost:5179"
Write-Host "Watt Smith starting -> http://localhost:5179  (two server windows opened; close them to stop)"
