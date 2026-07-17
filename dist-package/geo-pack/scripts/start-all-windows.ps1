$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendScript = Join-Path $RootDir "scripts\start-backend.ps1"
$FrontendScript = Join-Path $RootDir "scripts\start-frontend.ps1"
$PublishingBackendScript = Join-Path $RootDir "scripts\start-publishing-backend.ps1"
$PublishingFrontendScript = Join-Path $RootDir "scripts\start-publishing-frontend.ps1"
$PowerShellExe = "powershell.exe"

if (Get-Command pwsh -ErrorAction SilentlyContinue) {
  $PowerShellExe = "pwsh"
}

Start-Process -FilePath $PowerShellExe -WorkingDirectory $RootDir -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$BackendScript`""
Start-Sleep -Seconds 2
Start-Process -FilePath $PowerShellExe -WorkingDirectory $RootDir -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$FrontendScript`""
Start-Sleep -Seconds 2
Start-Process -FilePath $PowerShellExe -WorkingDirectory $RootDir -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$PublishingBackendScript`""
Start-Sleep -Seconds 2
Start-Process -FilePath $PowerShellExe -WorkingDirectory $RootDir -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$PublishingFrontendScript`""
Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:5173"
Start-Process "http://127.0.0.1:5174"

Write-Host "Writing and publishing services are starting in separate PowerShell windows."
Write-Host "Open http://127.0.0.1:5173 if the browser did not open automatically."
Write-Host "Open http://127.0.0.1:5174 for the publishing workbench."
