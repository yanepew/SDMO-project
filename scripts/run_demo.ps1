# Starts cloud -> gateway -> legacy device. Usage: .\scripts\run_demo.ps1 [-Interval 30s]
param([string]$Interval = "30s")

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"

# One-time key provisioning for local demos (cloud + gateway + trust relationship).
if (-not (Test-Path (Join-Path $root "keys\cloud.private.json"))) {
    & $python -m common.keygen dev
}

Start-Process $python -ArgumentList "-m", "cloud.cloud_service" -WorkingDirectory $root
Start-Sleep -Seconds 3
Start-Process $python -ArgumentList "-m", "gateway.gateway_service", "--interval", $Interval -WorkingDirectory $root
Start-Sleep -Seconds 3
& $python -m device.legacy_device
