$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location (Join-Path $RootDir "backend")

function Test-Venv($Path) {
  $PythonExe = Join-Path $Path "Scripts\python.exe"
  if (-not (Test-Path $PythonExe)) {
    return $false
  }
  & $PythonExe -c "import sys" *> $null
  return $LASTEXITCODE -eq 0
}

$VenvDir = $null
$BackendVenv = Join-Path $RootDir "backend\.venv"
$RootVenv = Join-Path $RootDir ".venv"
if (Test-Venv $BackendVenv) {
  $VenvDir = $BackendVenv
} elseif (Test-Venv $RootVenv) {
  $VenvDir = $RootVenv
}

if (-not $VenvDir) {
  Write-Error "No Python virtual environment found. Run: python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r backend\requirements.txt"
}

& (Join-Path $VenvDir "Scripts\Activate.ps1")
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
