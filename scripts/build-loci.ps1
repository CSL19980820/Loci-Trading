# Build portable Loci (onedir) and optionally deploy.
# Usage:
#   .\scripts\build-loci.ps1
#   .\scripts\build-loci.ps1 -DeployDir "E:\entertainment_software\Loci"
param(
  [string]$DeployDir = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

if (-not (Get-Command bun -ErrorAction SilentlyContinue)) {
  throw "bun not found. Install https://bun.sh"
}

Write-Host "== frontend build (bun) =="
Push-Location frontend
bun run build
if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
Pop-Location

Write-Host "== stop running Loci =="
Get-Process -Name Loci -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

Remove-Item -Force .\Loci.exe -ErrorAction SilentlyContinue
if (Test-Path .\Loci) {
  Remove-Item -Recurse -Force .\Loci
}

Write-Host "== pyinstaller onedir -> .\Loci\ =="
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean loci.spec
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

$exe = Join-Path (Get-Location) "Loci\Loci.exe"
if (-not (Test-Path $exe)) { throw "Loci\Loci.exe not found" }

Get-Item $exe | Format-List FullName, Length, LastWriteTime
$internal = Join-Path (Get-Location) "Loci\_internal"
if (Test-Path $internal) {
  $mb = [math]::Round(((Get-ChildItem $internal -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)
  Write-Host "Bundle _internal ~ ${mb} MB (onedir; fast start)"
}

if ($DeployDir) {
  Write-Host "== deploy -> $DeployDir =="
  New-Item -ItemType Directory -Force -Path $DeployDir | Out-Null
  $destInternal = Join-Path $DeployDir "_internal"
  if (Test-Path $destInternal) { Remove-Item -Recurse -Force $destInternal }
  Copy-Item -Force .\Loci\Loci.exe (Join-Path $DeployDir "Loci.exe")
  Copy-Item -Recurse -Force .\Loci\_internal $destInternal
  Copy-Item -Force .\使用说明.txt (Join-Path $DeployDir "使用说明.txt") -ErrorAction SilentlyContinue
  Get-Item (Join-Path $DeployDir "Loci.exe") | Format-List FullName, Length, LastWriteTime
}

Write-Host "Done. Run .\Loci\Loci.exe"
