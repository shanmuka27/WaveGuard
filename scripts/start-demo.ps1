# Starts the WaveGuard backend and dashboard for the demo, then opens the browser.
# Run from anywhere: double-click start-demo.bat in the repo root.
# "start-demo.bat phone" also serves phones on the same Wi-Fi or hotspot.
param([string]$Mode = "")
$phone = $Mode -eq "phone"

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$backendUrl = "http://127.0.0.1:8000/api/health"
$dashboardUrl = "http://127.0.0.1:5500/"

function Test-Url($url) {
    try {
        Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Wait-Url($url, $name) {
    for ($i = 0; $i -lt 30; $i++) {
        if (Test-Url $url) { Write-Host "  $name is up" -ForegroundColor Green; return }
        Start-Sleep -Seconds 1
    }
    Write-Host "  $name did not start. Check its window for errors." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path $python)) {
    Write-Host "Missing .venv. Run once:" -ForegroundColor Red
    Write-Host "  py -3.12 -m venv .venv"
    Write-Host "  .venv\Scripts\python.exe -m pip install -r requirements-dev.txt"
    Read-Host "Press Enter to exit"
    exit 1
}

$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root ".env.example") $envFile
    Write-Host "Created .env from .env.example" -ForegroundColor Yellow
}
$envText = Get-Content $envFile -Raw
if ($envText -notmatch "(?m)^WATSONX_API_KEY=\S" -or $envText -notmatch "(?m)^WATSONX_PROJECT_ID=\S") {
    Write-Host "IBM credentials are not set in .env. Granite will show 'Not configured';" -ForegroundColor Yellow
    Write-Host "the dashboard can still show the prerecorded example." -ForegroundColor Yellow
}

Write-Host "Starting WaveGuard..."
if (Test-Url $backendUrl) {
    Write-Host "  Backend already running" -ForegroundColor Green
} else {
    Start-Process -FilePath $python -WorkingDirectory $root `
        -ArgumentList "-m", "uvicorn", "backend.main:app", "--host", $(if ($phone) { "0.0.0.0" } else { "127.0.0.1" }), "--port", "8000"
    Wait-Url $backendUrl "Backend"
}

if (Test-Url $dashboardUrl) {
    Write-Host "  Dashboard already running" -ForegroundColor Green
} else {
    Start-Process -FilePath $python -WorkingDirectory $root `
        -ArgumentList $(if ($phone) { @((Join-Path $root "scripts\serve_frontend.py"), "--lan") } else { @(Join-Path $root "scripts\serve_frontend.py") })
    Wait-Url $dashboardUrl "Dashboard"
}

Start-Process $dashboardUrl
Write-Host ""
Write-Host "WaveGuard is running at $dashboardUrl" -ForegroundColor Cyan
if ($phone) {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.PrefixOrigin -ne 'WellKnown'
    } | Select-Object -First 1).IPAddress
    Write-Host ""
    Write-Host "Phone (same Wi-Fi or hotspot):" -ForegroundColor Cyan
    Write-Host "  Admin:     http://${ip}:5500/admin.html"
    Write-Host "  Dashboard: http://${ip}:5500/"
    Write-Host "If the phone can't connect, allow Python through Windows Firewall."
}
Write-Host "Close the two server windows to stop it."
Start-Sleep -Seconds 3
