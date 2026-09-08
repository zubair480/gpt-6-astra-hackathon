param([string]$Python = "", [string]$Out = "", [switch]$NoOpen)
$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    $demoPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $demoPython)) {
        if (-not $Python) {
            $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
            if (Test-Path -LiteralPath $bundledPython) { $Python = $bundledPython }
            elseif (Get-Command python -ErrorAction SilentlyContinue) { $Python = (Get-Command python).Source }
            else { throw 'Python 3.11+ is required. Pass its executable with -Python.' }
        }
        & $Python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the local virtual environment.' }
        & $demoPython -m pip install -r requirements.txt -e .
        if ($LASTEXITCODE -ne 0) { throw 'Local package setup failed.' }
    }
    if (-not $Out) { $Out = 'out/demo-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') }
    Write-Host 'Preparing the workflow, learning its procedure, and running skill rehearsal cases...'
    $demoJson = & $demoPython -m plva_skill_learning demo --out $Out
    if ($LASTEXITCODE -ne 0) { throw 'Demo did not complete. See the error above.' }
    $demoResult = ($demoJson -join "`n") | ConvertFrom-Json
    # Keep the user's bookmarked page current while preserving each run's package.
    $latestDirectory = Join-Path $PSScriptRoot 'out\visual-demo'
    New-Item -ItemType Directory -Path $latestDirectory -Force | Out-Null
    $latestViewer = Join-Path $latestDirectory 'demo.html'
    Copy-Item -LiteralPath $demoResult.viewer -Destination $latestViewer -Force
    Write-Host "`nDemo ready."
    Write-Host "Open the walkthrough: $latestViewer"
    Write-Host 'Already open? Refresh that browser tab to see this run.'
    Write-Host '1. Play the recording  2. Review the skill  3. Inspect test cases  4. Prepare fresh inputs'
    Write-Host ("Rehearsal: {0} passed / {1} failed / {2} pending live execution" -f $demoResult.rehearsal.passed, $demoResult.rehearsal.failed, $demoResult.rehearsal.pending)
    Write-Host 'This is a synthetic offline demo. Live Astra execution remains pending.'
    if (-not $NoOpen) { Invoke-Item -LiteralPath $latestViewer }
}
finally { Pop-Location }
