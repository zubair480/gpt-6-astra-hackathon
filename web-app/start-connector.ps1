param([string]$ApiKeyFile = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
}
& $pythonPath -m pip install -r web-app/requirements-bridge.txt --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& $pythonPath -m plva.detection.provision
if ($LASTEXITCODE -ne 0) { throw 'OCR provisioning failed' }
$connectionFile = Join-Path $env:LOCALAPPDATA 'PLVA\CloudWorkspace\secrets.json'
if (-not (Test-Path -LiteralPath $connectionFile)) { throw 'This computer needs the private workspace connection file. Run npm run setup in web-app, then upload its secrets to your Worker.' }
$bridgeArguments = @('-m', 'plva.cloud_bridge', '--secrets', $connectionFile)
if ($ApiKeyFile) { $bridgeArguments += @('--key-file', $ApiKeyFile) }
& $pythonPath @bridgeArguments
