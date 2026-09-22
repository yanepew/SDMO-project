<#
.SYNOPSIS
    Starts the simulated cloud service, edge gateway, and legacy device.

.DESCRIPTION
    This script starts the cloud and gateway services as background Python
    processes, then starts the legacy device in the current terminal.

    When the legacy device is stopped with Ctrl+C, the script attempts to stop
    the cloud and gateway background processes.

.NOTES
    Run this script from the repository root, for example:

        .\scripts\run_demo.ps1

    The Python virtual environment should already be activated before running
    this script:

        .\.venv\Scripts\Activate.ps1
        .\scripts\run_demo.ps1
#>

$ErrorActionPreference = "Stop"

# Move to the repository root even when the script is launched from elsewhere.
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepositoryRoot

Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "Starting simulated legacy edge-cloud system..." -ForegroundColor Cyan
Write-Host "Repository root: $RepositoryRoot" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan

$CloudProcess = $null
$GatewayProcess = $null

try {
    # Verify that Python is available before launching any services.
    $PythonVersion = python --version 2>&1
    Write-Host "[SETUP] Using $PythonVersion" -ForegroundColor Green

    Write-Host ""
    Write-Host "[1/3] Starting cloud service at http://127.0.0.1:8002 ..." -ForegroundColor Yellow

    $CloudProcess = Start-Process `
        -FilePath "python" `
        -ArgumentList "-m", "cloud.cloud_service" `
        -WorkingDirectory $RepositoryRoot `
        -PassThru `
        -NoNewWindow

    Start-Sleep -Seconds 2

    if ($CloudProcess.HasExited) {
        throw "Cloud service exited unexpectedly. Check the terminal output."
    }

    Write-Host "[CLOUD] Started with process ID $($CloudProcess.Id)." -ForegroundColor Green

    Write-Host ""
    Write-Host "[2/3] Starting edge gateway at http://127.0.0.1:8001 ..." -ForegroundColor Yellow

    $GatewayProcess = Start-Process `
        -FilePath "python" `
        -ArgumentList "-m", "gateway.gateway_service" `
        -WorkingDirectory $RepositoryRoot `
        -PassThru `
        -NoNewWindow

    Start-Sleep -Seconds 2

    if ($GatewayProcess.HasExited) {
        throw "Gateway service exited unexpectedly. Check the terminal output."
    }

    Write-Host "[GATEWAY] Started with process ID $($GatewayProcess.Id)." -ForegroundColor Green

    Write-Host ""
    Write-Host "[3/3] Starting simulated legacy device..." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "The device runs in this terminal." -ForegroundColor Cyan
    Write-Host "Press Ctrl+C to stop the device and shut down the demo." -ForegroundColor Cyan
    Write-Host ""

    # Run the device in the current PowerShell terminal so its output is visible.
    python -m device.legacy_device
}
catch {
    Write-Host ""
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Write-Host ""
    Write-Host "Stopping background services..." -ForegroundColor Yellow

    if ($GatewayProcess -and -not $GatewayProcess.HasExited) {
        Stop-Process -Id $GatewayProcess.Id -Force
        Write-Host "[GATEWAY] Stopped process ID $($GatewayProcess.Id)." -ForegroundColor Green
    }

    if ($CloudProcess -and -not $CloudProcess.HasExited) {
        Stop-Process -Id $CloudProcess.Id -Force
        Write-Host "[CLOUD] Stopped process ID $($CloudProcess.Id)." -ForegroundColor Green
    }

    Write-Host "Demo shutdown complete." -ForegroundColor Cyan
}
