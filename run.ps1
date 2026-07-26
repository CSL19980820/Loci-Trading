# stock-analyzer - 快捷运行脚本
# 用法:
#   .\run.ps1 002460 84.363 600
#   .\run.ps1 600519 1800 100 120      # 第4个参数为 K线天数 (默认 90)
#   .\run.ps1 002460 84.363 600 120 "赣锋锂业" "md,html,pdf,json,csv"

param(
    [Parameter(Mandatory = $true)][string]$Code,
    [Parameter(Mandatory = $true)][double]$Cost,
    [Parameter(Mandatory = $true)][int]$Shares,
    [int]$Days = 90,
    [string]$Name,
    [string]$Formats = "md,json,csv",
    [string]$PortfolioCsv
)

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $projectRoot

$pythonExe = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    Write-Host "[错误] 虚拟环境未就绪, 请先运行: .\setup.ps1" -ForegroundColor Red
    exit 1
}

$argsList = @($Code, "--cost", $Cost, "--shares", $Shares, "--days", $Days)
if ($Name) { $argsList += @("--name", $Name) }
if ($Formats) { $argsList += @("--formats", $Formats) }
if ($PortfolioCsv) { $argsList += @("--portfolio-csv", $PortfolioCsv) }

& $pythonExe analyze.py @argsList
