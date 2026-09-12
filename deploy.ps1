# deploy.ps1 - Automates deployment of the OpenWrt Mesh Presence integration to Home Assistant server

$ErrorActionPreference = "Stop"

$SourceDir = "$PSScriptRoot\custom_components\openwrt_mesh_presence"
$DestDir = "\\192.168.100.5\config\custom_components\openwrt_mesh_presence"
$HostIP = "192.168.100.5"

Write-Host "=== Starting OpenWrt Mesh Presence Integration Deployment ===" -ForegroundColor Cyan

# 1. Check destination folder accessibility
Write-Host "Checking accessibility of destination share: $DestDir..." -NoNewline
if (Test-Path "\\192.168.100.5\config\custom_components") {
    Write-Host " [OK]" -ForegroundColor Green
    if (-not (Test-Path $DestDir)) {
        New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
    }
} else {
    Write-Host " [NOT FOUND]" -ForegroundColor Red
    Write-Error "Destination path \\192.168.100.5\config\custom_components is not accessible. Please ensure SMB share is mounted and accessible."
}

# 2. Synchronize files using robocopy
Write-Host "Synchronizing files from $SourceDir to $DestDir..." -ForegroundColor Yellow
$exitCode = 0
try {
    robocopy $SourceDir $DestDir /MIR /XD __pycache__ /R:3 /W:5 /NDL /NFL | Out-Null
    $exitCode = $LASTEXITCODE
} catch {
    $exitCode = 8
}

if ($exitCode -ge 8) {
    Write-Error "Robocopy failed during synchronization (exit code: $exitCode)."
} else {
    Write-Host "Synchronization completed successfully." -ForegroundColor Green
}

# 3. Clean remote __pycache__ directory to force HA to reload fresh files
$RemoteCache = Join-Path $DestDir "__pycache__"
if (Test-Path $RemoteCache) {
    Write-Host "Cleaning remote __pycache__ on server..." -ForegroundColor Yellow
    Remove-Item -Path $RemoteCache -Recurse -Force
    Write-Host "Remote __pycache__ directory deleted." -ForegroundColor Green
} else {
    Write-Host "No remote __pycache__ directory found, skipping cleanup." -ForegroundColor Gray
}

Write-Host "=== Deployment Completed Successfully ===" -ForegroundColor Green
