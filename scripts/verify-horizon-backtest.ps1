# Goal verify: horizon backtest backend + frontend typecheck
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot\..
& .\.venv\Scripts\python.exe -m pytest tests/backtest -q --tb=line
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Location frontend
bun run typecheck
exit $LASTEXITCODE
