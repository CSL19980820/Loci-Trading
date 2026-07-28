# stock-analyzer 环境初始化

用法: `.\setup.ps1`

$ErrorActionPreference = "Stop"
Write-Host "=== Loci / stock-analyzer 环境初始化 ===" -ForegroundColor Cyan
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $projectRoot

$useUv = $false
try {
    $uvVersion = & uv --version 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] 检测到 uv: $uvVersion" -ForegroundColor Green
        $useUv = $true
    }
} catch {}

if (-not (Test-Path ".venv")) {
    Write-Host "[步骤 1/3] 创建虚拟环境 .venv ..." -ForegroundColor Yellow
    if ($useUv) { & uv venv --python 3.12 } else { & python -m venv .venv }
} else {
    Write-Host "[跳过] .venv 已存在" -ForegroundColor Gray
}

Write-Host "[步骤 2/3] 安装依赖 ..." -ForegroundColor Yellow
$pythonExe = ".\.venv\Scripts\python.exe"
if ($useUv) {
    & uv pip install -r requirements.txt
} else {
    & $pythonExe -m pip install --upgrade pip
    & $pythonExe -m pip install -r requirements.txt
}

Write-Host "[步骤 3/3] 验证安装 ..." -ForegroundColor Yellow
& $pythonExe -c "import fastapi, pandas, akshare, duckdb; print('[OK] 核心依赖可用')"

Write-Host ""
Write-Host "=== 初始化完成 ===" -ForegroundColor Green
Write-Host "启动桌面:  .\.venv\Scripts\python.exe loci.py"
Write-Host "仅 API:    .\.venv\Scripts\python.exe -m cli.serve"
Write-Host "前端:      cd frontend; bun install; bun run dev"
Write-Host "测试:      .\.venv\Scripts\python.exe -m pytest tests/ -q"
Write-Host "架构:      .\.venv\Scripts\lint-imports.exe"
Write-Host "可选:      `$env:LOCI_MARKET_DUCKDB='1'  # market load_panel DuckDB 旁路"
Write-Host "可选:      `$env:LOCI_BACKTEST_FAST='1'  # 回测加速旁路（失败回退经典）"
