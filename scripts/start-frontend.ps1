$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location (Join-Path $RootDir "frontend")

if (-not (Test-Path "node_modules")) {
  Write-Error "frontend/node_modules not found. Run: cd frontend; npm install"
}

npm run dev -- --host 127.0.0.1 --port 5173
