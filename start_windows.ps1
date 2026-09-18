<#
Start the GUI locally on Windows.

Run this after activating the desired conda environment:
  powershell -ExecutionPolicy Bypass -File .\start_windows.ps1

The backend stays attached to this terminal so its logs remain visible.
#>
[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$url = 'http://127.0.0.1:18080'
Set-Location -LiteralPath $projectRoot

$pythonCommand = Get-Command python -ErrorAction Stop
$pythonExe = $pythonCommand.Source

if (-not $SkipInstall) {
    Write-Host 'Installing/checking Python dependencies...'
    & $pythonExe -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) {
        throw 'Dependency installation failed. Activate the intended conda environment and retry.'
    }
}

& $pythonExe -c "import cv2, numpy; print('OpenCV ' + cv2.__version__ + '; NumPy ' + numpy.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw 'OpenCV or NumPy cannot be imported. Run pip install -r requirements.txt in the active environment.'
}

if (Get-NetTCPConnection -LocalPort 18080 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 18080 is already in use. Stop the existing backend or open http://127.0.0.1:18080 directly.'
}

if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        param($healthUrl, $browserUrl)
        for ($attempt = 0; $attempt -lt 40; $attempt++) {
            try {
                Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 -Uri $healthUrl | Out-Null
                Start-Process $browserUrl
                return
            } catch {
                Start-Sleep -Milliseconds 250
            }
        }
    } -ArgumentList "$url/api/status", $url | Out-Null
}

Write-Host "Starting GUI at $url (Ctrl+C stops it)."
& $pythonExe (Join-Path $projectRoot 'backend.py')
exit $LASTEXITCODE
