$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location (Join-Path $RootDir "publishing\frontend")

if (-not (Test-Path "node_modules")) {
  Write-Error "publishing\frontend\node_modules not found. Run: cd publishing\frontend; npm install"
}

npm run dev -- --host 127.0.0.1 --port 5174
