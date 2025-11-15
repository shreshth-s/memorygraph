# stop.ps1 — stops the dev backend & frontend launched by run.ps1

$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $root ".devpids.json"

if (-not (Test-Path $pidFile)) {
  Write-Host "No PID file found (.devpids.json). Close any dev windows manually." -ForegroundColor Yellow
  exit 0
}

try {
  $p = Get-Content $pidFile | ConvertFrom-Json
} catch {
  Write-Host "PID file unreadable; remove .devpids.json and close windows manually." -ForegroundColor Yellow
  exit 1
}

$killed = @()
foreach ($name in "backend","frontend") {
  $pid = $p.$name
  if ($pid -and (Get-Process -Id $pid -ErrorAction SilentlyContinue)) {
    Write-Host "Stopping $name (PID $pid)..." -ForegroundColor Cyan
    Stop-Process -Id $pid -Force
    $killed += $name
  }
}

Remove-Item $pidFile -ErrorAction SilentlyContinue

if ($killed.Count -gt 0) {
  Write-Host "Stopped: $($killed -join ', ')." -ForegroundColor Green
} else {
  Write-Host "No matching processes found. They may already be closed." -ForegroundColor Yellow
}
