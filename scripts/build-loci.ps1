# Build portable Loci (onedir) and optionally deploy.
# Usage:
#   .\scripts\build-loci.ps1
#   .\scripts\build-loci.ps1 -Mode frontend -DeployDir "E:\entertainment_software\Loci"
#   .\scripts\build-loci.ps1 -Mode app -SrcOnly -DeployDir "E:\entertainment_software\Loci"
#   .\scripts\build-loci.ps1 -Mode app+frontend -DeployDir "E:\entertainment_software\Loci"
#   .\scripts\build-loci.ps1 -Mode full -DeployDir "E:\entertainment_software\Loci"
param(
  [ValidateSet("full", "app", "frontend", "app+frontend")]
  [string]$Mode = "full",
  [switch]$SrcOnly,
  [string]$DeployDir = ""
)

$ErrorActionPreference = "Stop"
$ScriptRepoRoot = if ($PSScriptRoot) { (Resolve-Path "$PSScriptRoot\..").Path } else { (Get-Location).Path }
Set-Location $ScriptRepoRoot

if ($SrcOnly -and $Mode -ne "app") {
  throw "-SrcOnly only applies with -Mode app"
}

$needFrontend = $Mode -in @("full", "frontend", "app+frontend")
$needPyInstaller = ($Mode -in @("full", "app", "app+frontend")) -and -not $SrcOnly
$incremental = $Mode -ne "full"

function Assert-ExistingInstall {
  param(
    [string]$Root,
    [switch]$RequireLooseSrc
  )
  $exePath = Join-Path $Root "Loci.exe"
  $internalPath = Join-Path $Root "_internal"
  if (-not (Test-Path $exePath) -or -not (Test-Path $internalPath)) {
    throw "Incremental mode requires an existing install at $Root (Loci.exe + _internal). Run -Mode full once first."
  }
  if ($RequireLooseSrc) {
    $srcPath = Join-Path $internalPath "src"
    if (-not (Test-Path $srcPath)) {
      throw "Install at $Root has no _internal\src (old PYZ bundle). Run -Mode full once to enable app/SrcOnly patches."
    }
  }
}

function Stop-LociProcess {
  Write-Host "== stop running Loci =="
  Get-Process -Name Loci -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Seconds 1
}

function Sync-Tree {
  param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Destination
  )
  if (-not (Test-Path $Source)) {
    throw "Missing source: $Source"
  }
  if (Test-Path $Destination) {
    Remove-Item -Recurse -Force $Destination
  }
  $parent = Split-Path -Parent $Destination
  if ($parent) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
  }
  Copy-Item -Recurse -Force $Source $Destination
}

function Deploy-Frontend {
  param([string]$TargetRoot)
  $src = Join-Path $ScriptRepoRoot "frontend\dist"
  $dest = Join-Path $TargetRoot "_internal\frontend\dist"
  Write-Host "== sync frontend/dist -> $dest =="
  Sync-Tree -Source $src -Destination $dest
}

function Deploy-AppBits {
  param(
    [string]$TargetRoot,
    [switch]$IncludeExe,
    [switch]$IncludeSrc,
    [switch]$IncludeAssets
  )
  $repoRoot = if ($ScriptRepoRoot) { $ScriptRepoRoot } else { (Get-Location).Path }
  $localRoot = Join-Path $repoRoot "Loci"
  $localInternal = Join-Path $localRoot "_internal"

  if ($IncludeExe) {
    $exeSrc = Join-Path $localRoot "Loci.exe"
    if (-not (Test-Path $exeSrc)) { throw "Loci\Loci.exe not found; run PyInstaller first" }
    Write-Host "== sync Loci.exe -> $TargetRoot =="
    Copy-Item -Force $exeSrc (Join-Path $TargetRoot "Loci.exe")
  }

  if ($IncludeSrc) {
    # 必须以仓库 src 为准。本地 Loci\_internal\src 是上次 PyInstaller 快照，SrcOnly 时往往过期。
    $srcFromRepo = Join-Path $repoRoot "src"
    $srcFromBuild = Join-Path $localInternal "src"
    if ($srcFromRepo -and (Test-Path -Path $srcFromRepo)) {
      $srcPath = $srcFromRepo
    } elseif ($srcFromBuild -and (Test-Path -Path $srcFromBuild)) {
      $srcPath = $srcFromBuild
      Write-Host "WARN: using bundled src (repo src missing): $srcPath"
    } else {
      throw "No src to sync (repo ./src and Loci\_internal\src both missing)"
    }
    $dest = Join-Path $TargetRoot "_internal\src"
    Write-Host "== sync src ($srcPath) -> $dest =="
    Sync-Tree -Source $srcPath -Destination $dest
  }

  if ($IncludeAssets) {
    $assetsFromBuild = Join-Path $localInternal "assets"
    $assetsFromRepo = Join-Path $repoRoot "assets"
    $assetsPath = if ($assetsFromBuild -and (Test-Path $assetsFromBuild)) { $assetsFromBuild } else { $assetsFromRepo }
    $dest = Join-Path $TargetRoot "_internal\assets"
    Write-Host "== sync assets -> $dest =="
    Sync-Tree -Source $assetsPath -Destination $dest
  }

  # akshare 静态资源（calendar.json 等）；缺了交易所列表会炸
  $akFromBuild = Join-Path $localInternal "akshare"
  if ($akFromBuild -and (Test-Path $akFromBuild)) {
    $akDest = Join-Path $TargetRoot "_internal\akshare"
    Write-Host "== sync akshare data -> $akDest =="
    Sync-Tree -Source $akFromBuild -Destination $akDest
  }

  $readme = Join-Path $repoRoot "使用说明.txt"
  if (Test-Path $readme) {
    Copy-Item -Force $readme (Join-Path $TargetRoot "使用说明.txt")
  }
}

function Deploy-Full {
  param([string]$TargetRoot)
  Write-Host "== full deploy -> $TargetRoot =="
  New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null
  $destInternal = Join-Path $TargetRoot "_internal"
  if (Test-Path $destInternal) { Remove-Item -Recurse -Force $destInternal }
  Copy-Item -Force .\Loci\Loci.exe (Join-Path $TargetRoot "Loci.exe")
  Copy-Item -Recurse -Force .\Loci\_internal $destInternal
  Copy-Item -Force .\使用说明.txt (Join-Path $TargetRoot "使用说明.txt") -ErrorAction SilentlyContinue
}

# --- frontend ---
if ($needFrontend) {
  if (-not (Get-Command bun -ErrorAction SilentlyContinue)) {
    throw "bun not found. Install https://bun.sh"
  }
  Write-Host "== frontend build (bun) =="
  Push-Location frontend
  bun run build
  if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
  Pop-Location
}

# --- targets for incremental checks ---
$localBundle = Join-Path (Get-Location) "Loci"
$needLooseSrc = $Mode -in @("app", "app+frontend")
if ($incremental) {
  if ($DeployDir) {
    Assert-ExistingInstall -Root $DeployDir -RequireLooseSrc:$needLooseSrc
  } elseif ($Mode -eq "frontend" -or $SrcOnly) {
    # frontend / SrcOnly can patch local bundle or deploy dir; need at least one
    if (-not (Test-Path (Join-Path $localBundle "Loci.exe"))) {
      throw "Incremental mode requires .\Loci or -DeployDir with an existing install. Run -Mode full once first."
    }
    Assert-ExistingInstall -Root $localBundle -RequireLooseSrc:$needLooseSrc
  }
}

Stop-LociProcess

# --- pyinstaller ---
if ($needPyInstaller) {
  if ($Mode -eq "full") {
    Remove-Item -Force .\Loci.exe -ErrorAction SilentlyContinue
    if (Test-Path .\Loci) {
      Remove-Item -Recurse -Force .\Loci
    }
    Write-Host "== pyinstaller onedir (clean) -> .\Loci\ =="
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean loci.spec
  } else {
    Write-Host "== pyinstaller onedir (no-clean) -> .\Loci\ =="
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm loci.spec
  }
  if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

  $exe = Join-Path (Get-Location) "Loci\Loci.exe"
  if (-not (Test-Path $exe)) { throw "Loci\Loci.exe not found" }
  Get-Item $exe | Format-List FullName, Length, LastWriteTime
  $internal = Join-Path (Get-Location) "Loci\_internal"
  if (Test-Path $internal) {
    $mb = [math]::Round(((Get-ChildItem $internal -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)
    Write-Host "Bundle _internal ~ ${mb} MB (onedir; fast start)"
  }
}

# --- deploy / local sync ---
function Invoke-ModeDeploy {
  param([string]$TargetRoot)

  switch ($Mode) {
    "full" {
      Deploy-Full -TargetRoot $TargetRoot
    }
    "frontend" {
      Assert-ExistingInstall -Root $TargetRoot
      Deploy-Frontend -TargetRoot $TargetRoot
    }
    "app" {
      Assert-ExistingInstall -Root $TargetRoot -RequireLooseSrc
      if ($SrcOnly) {
        Deploy-AppBits -TargetRoot $TargetRoot -IncludeSrc
      } else {
        Deploy-AppBits -TargetRoot $TargetRoot -IncludeExe -IncludeSrc -IncludeAssets
      }
    }
    "app+frontend" {
      Assert-ExistingInstall -Root $TargetRoot -RequireLooseSrc
      Deploy-AppBits -TargetRoot $TargetRoot -IncludeExe -IncludeSrc -IncludeAssets
      Deploy-Frontend -TargetRoot $TargetRoot
    }
  }
}

if ($DeployDir) {
  Invoke-ModeDeploy -TargetRoot $DeployDir
  $deployedExe = Join-Path $DeployDir "Loci.exe"
  if (Test-Path $deployedExe) {
    Get-Item $deployedExe | Format-List FullName, Length, LastWriteTime
  }
} elseif ($Mode -eq "frontend") {
  # Patch local bundle when no DeployDir
  Invoke-ModeDeploy -TargetRoot $localBundle
} elseif ($SrcOnly) {
  Invoke-ModeDeploy -TargetRoot $localBundle
}

Write-Host "Done. Mode=$Mode$(if ($SrcOnly) { ' SrcOnly' }). Run .\Loci\Loci.exe or DeployDir."
