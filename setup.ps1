# stock-analyzer - Windows PowerShell 环境初始化脚本
# 用法:   .\setup.ps1
# 前置:   需安装 uv (https://docs.astral.sh/uv/) 或 Python 3.10+
#
# 执行流程:
#   1) 检测 uv / Python
#   2) 创建 .venv 虚拟环境
#   3) 安装 requirements.txt
#   4) 提示使用方法

$ErrorActionPreference = "Stop"

Write-Host "=== stock-analyzer 环境初始化 ===" -ForegroundColor Cyan
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $projectRoot

# 1. 检测 uv
$useUv = $false
try {
    $uvVersion = & uv --version 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] 检测到 uv: $uvVersion" -ForegroundColor Green
        $useUv = $true
    }
} catch {}

# 2. 创建虚拟环境
if (-not (Test-Path ".venv")) {
    Write-Host "[步骤 1/3] 创建虚拟环境 .venv ..." -ForegroundColor Yellow
    if ($useUv) {
        & uv venv --python 3.12
    } else {
        & python -m venv .venv
    }
} else {
    Write-Host "[跳过] .venv 已存在" -ForegroundColor Gray
}

# 3. 安装依赖
Write-Host "[步骤 2/3] 安装依赖 ..." -ForegroundColor Yellow
$pythonExe = ".\.venv\Scripts\python.exe"
if ($useUv) {
    & uv pip install -r requirements.txt
} else {
    & $pythonExe -m pip install --upgrade pip
    & $pythonExe -m pip install -r requirements.txt
}

# 4. 验证
Write-Host "[步骤 3/3] 验证安装 ..." -ForegroundColor Yellow
& $pythonExe -c "import akshare, pandas, scipy, jinja2, markdown; print('[OK] 所有依赖就绪')"

Write-Host ""
Write-Host "=== 初始化完成 ===" -ForegroundColor Green
Write-Host ""
Write-Host "使用方法:" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\python.exe analyze.py 002460 --cost 84.363 --shares 600 --formats all"
Write-Host ""
Write-Host "PDF 说明:" -ForegroundColor Cyan
Write-Host "  如需直接导出 PDF, 可额外安装 weasyprint 或 wkhtmltopdf；未安装时仍会生成 HTML 打印源。"
Write-Host ""
Write-Host "或先激活环境:" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  python analyze.py 002460 --cost 84.363 --shares 600"
Write-Host ""
