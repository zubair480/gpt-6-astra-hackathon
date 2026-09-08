$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    python -m venv .venv
}
& .venv\Scripts\python.exe -m pip install -r requirements.txt --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& .venv\Scripts\python.exe -m plva.detection.provision
if ($LASTEXITCODE -ne 0) { throw 'Local OCR model provisioning failed' }
Write-Host 'Open http://127.0.0.1:18080 — Ctrl+C stops the server.'
& .venv\Scripts\python.exe -m plva
