$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RootDir

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Error "Python was not found. Install Python 3.11 or later, then run this script again."
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  Write-Error "Node.js was not found. Install Node.js 20 LTS or later, then run this script again."
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  Write-Error "npm was not found. Install Node.js 20 LTS or later, then run this script again."
}

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host "Created .env from .env.example. Edit .env and fill API keys before generating content."
}

Set-Location (Join-Path $RootDir "backend")
if (-not (Test-Path ".venv")) {
  python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Set-Location (Join-Path $RootDir "frontend")
npm install

Set-Location (Join-Path $RootDir "publishing\backend")
if (-not (Test-Path ".venv")) {
  python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Set-Location (Join-Path $RootDir "publishing\frontend")
npm install

Set-Location $RootDir
Write-Host "Install complete. Next: edit .env, then run .\scripts\start-all-windows.ps1"
