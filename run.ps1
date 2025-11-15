# run.ps1 — launch backend (FastAPI) + frontend (Vite) in separate windows
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\run.ps1
#   powershell -ExecutionPolicy Bypass -File .\run.ps1 -Seed
#   powershell -ExecutionPolicy Bypass -File .\run.ps1 -BackendPort 8001 -FrontendPort 5175

param(
  [int]$BackendPort = 8000,
  [int]$FrontendPort = 5174,
  [switch]$Seed
)

$ErrorActionPreference = "Stop"

# ---- Paths (edit $pgBin to match your install if needed) ----
$root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend  = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$pgBin    = "C:\Program Files\PostgreSQL\17\bin"   # <-- change if your version differs

# ---- Helpers ----
function Ensure-PostgresRunning {
  # Try a quick ping to the service (optional)
  try {
    & "$pgBin\psql.exe" -h localhost -p 5433 -U postgres -d postgres -c "select 1;" | Out-Null
  } catch {
    Write-Warning "Could not reach Postgres on localhost:5433. Ensure the PostgreSQL service is running and the path in run.ps1 is correct."
  }
}

function Ensure-BackendVenvAndDeps {
  Push-Location $backend
  if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    Write-Host "Creating backend venv..." -ForegroundColor Cyan
    python -m venv .venv
  }
  . .\.venv\Scripts\Activate.ps1
  # Bulletproof: always ensure deps are installed/updated if requirements.txt exists
  if (Test-Path ".\requirements.txt") {
    Write-Host "Installing backend deps (requirements.txt)..." -ForegroundColor Cyan
    pip install -r requirements.txt | Out-Null
  } else {
    # first-time minimal deps
    Write-Host "Installing backend deps (fastapi, uvicorn, psycopg[binary])..." -ForegroundColor Cyan
    pip install fastapi uvicorn psycopg[binary] | Out-Null
    pip freeze > requirements.txt
  }
  Pop-Location
}

function Ensure-FrontendDeps {
  Push-Location $frontend
  if (-not (Test-Path ".\node_modules")) {
    Write-Host "Installing frontend deps (npm install)..." -ForegroundColor Cyan
    npm install --silent
  } else {
    # Bulletproof: keep deps fresh if package.json changed later
    Write-Host "Verifying frontend deps (npm install)..." -ForegroundColor Cyan
    npm install --silent
  }
  Pop-Location
}

function Seed-Database {
  Write-Host "Seeding database (schema + seed)..." -ForegroundColor Cyan
  & "$pgBin\psql.exe" -h localhost -p 5433 -U postgres -d mgdb -f "$backend\schema.sql"
  & "$pgBin\psql.exe" -h localhost -p 5433 -U postgres -d mgdb -f "$backend\seed.sql"
}

# ---- Ensure prerequisites ----
Ensure-PostgresRunning
Ensure-BackendVenvAndDeps
Ensure-FrontendDeps
if ($Seed) { Seed-Database }

# ---- Launch backend ----
$backendCmd = @"
cd "$backend"
. .\.venv\Scripts\Activate.ps1
uvicorn main:app --reload --port $BackendPort
"@

$backendProc = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit","-Command",$backendCmd) -PassThru
Write-Host "Backend starting on http://localhost:$BackendPort  (PID $($backendProc.Id))" -ForegroundColor Green

# ---- Launch frontend ----
$frontendCmd = @"
cd "$frontend"
npm run dev -- --port $FrontendPort
"@

$frontendProc = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit","-Command",$frontendCmd) -PassThru
Write-Host "Frontend starting on http://localhost:$FrontendPort  (PID $($frontendProc.Id))" -ForegroundColor Green

# ---- Save PIDs for stop.ps1 ----
$pidFile = Join-Path $root ".devpids.json"
@{
  backend  = $backendProc.Id
  frontend = $frontendProc.Id
} | ConvertTo-Json | Set-Content $pidFile -Encoding UTF8

Write-Host "`nDev servers launched. Close their windows or run .\stop.ps1 to stop both." -ForegroundColor Yellow
