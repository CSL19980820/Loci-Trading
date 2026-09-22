#Requires -Version 7.0
<#
.SYNOPSIS
    Loci 前端联调入口：本地 Vite 接线上或本地后端，退出即收回隧道。

.DESCRIPTION
    只解决「本地改样式、后端用现成数据」这件事：
      · -Mode prod   经 SSH 把 my-debian 上 127.0.0.1:54324 搬到本机 127.0.0.1:8787，
        再起 Vite（5174），/api 代理走该隧道。Ctrl+C 退出即杀掉隧道。
      · -Mode local  不建隧道，Vite 直接连本机已有后端（默认 127.0.0.1:8787）。

    线上端口是部署约定（deploy/docker-compose.yml 的 127.0.0.1:54324 → 容器 8787），
    不是每次现猜的值；隧道只绑本机回环，不对外暴露。

.EXAMPLE
    pwsh .\scripts\dev-ui.ps1
    默认 prod 模式：连线上调样式。

.EXAMPLE
    pwsh .\scripts\dev-ui.ps1 -Mode local
    本机已有后端时用，不建 SSH 隧道。

.EXAMPLE
    pwsh .\scripts\dev-ui.ps1 -LocalPort 18787 -SkipFrontendInstall
    本机 8787 被占用时换一个本地端口，并跳过 bun install。
#>
[CmdletBinding()]
param(
    [ValidateSet('prod', 'local')]
    [string]$Mode = 'prod',
    [string]$RemoteHost = 'my-debian',
    [int]$RemotePort = 54324,
    [int]$LocalPort = 8787,
    [int]$FrontendPort = 5174,
    [switch]$SkipFrontendInstall
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$RepoRoot = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $RepoRoot 'frontend'

function Write-Step { param([string]$Text) Write-Host "`n== $Text" -ForegroundColor Cyan }
function Write-Note { param([string]$Text) Write-Host "   $Text" -ForegroundColor DarkGray }
function Fail { param([string]$Text) Write-Host "!! $Text" -ForegroundColor Red; exit 1 }

$script:tunnel = $null
function Stop-Tunnel {
    if ($null -ne $script:tunnel -and -not $script:tunnel.HasExited) {
        try { Stop-Process -InputObject $script:tunnel -Force } catch { }
    }
    $script:tunnel = $null
}

try {
    if (-not (Test-Path (Join-Path $FrontendDir 'package.json'))) { Fail "找不到前端目录：$FrontendDir" }
    if (-not (Get-Command bun -ErrorAction SilentlyContinue)) { Fail '缺少 bun，无法启动 Vite' }

    if ($Mode -eq 'prod') {
        foreach ($tool in @('ssh')) {
            if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { Fail "缺少命令：$tool" }
        }
        Write-Step "建立隧道 127.0.0.1:$LocalPort → $RemoteHost`:127.0.0.1:$RemotePort"
        $probe = & ssh -o ConnectTimeout=15 -o BatchMode=yes $RemoteHost "curl -fsS -m 5 http://127.0.0.1:$RemotePort/api/health" 2>&1
        if ($LASTEXITCODE -ne 0) { Fail "线上 $RemotePort 不可用（先看容器是否 healthy）：$probe" }
        $global:LASTEXITCODE = 0
        Write-Note "线上健康检查通过：$probe"
        $script:tunnel = Start-Process -FilePath 'ssh' -ArgumentList @(
            '-N',
            '-o', 'ExitOnForwardFailure=yes',
            '-o', 'ServerAliveInterval=30',
            '-o', 'ServerAliveCountMax=3',
            '-L', "127.0.0.1:${LocalPort}:127.0.0.1:${RemotePort}",
            $RemoteHost
        ) -PassThru
        Start-Sleep -Seconds 1
        if ($script:tunnel.HasExited) { Fail 'SSH 隧道启动后立刻退出，请检查免密登录或端口占用' }
        Write-Note "隧道进程 PID $($script:tunnel.Id)，退出脚本即关闭"
    } else {
        Write-Step "本地模式：直连本机 127.0.0.1:$LocalPort"
    }

    Push-Location $FrontendDir
    try {
        if (-not $SkipFrontendInstall) {
            Write-Step '安装前端依赖（bun install --frozen-lockfile）'
            & bun install --frozen-lockfile
            if ($LASTEXITCODE -ne 0) { Fail '前端依赖安装失败' }
        }
        Write-Step "启动 Vite（:$FrontendPort），/api → 127.0.0.1:$LocalPort"
        Write-Note '这是生产数据的只读联调：只调样式，不要提交、改账或触发任务'
        Write-Note '按 Ctrl+C 退出，prod 模式的 SSH 隧道会一并关闭'
        $env:LOCI_API_TARGET = "http://127.0.0.1:$LocalPort"
        & bun run dev -- --host 127.0.0.1 --port $FrontendPort
    } finally { Pop-Location }
} finally {
    Stop-Tunnel
    Write-Note '隧道已关闭'
}

