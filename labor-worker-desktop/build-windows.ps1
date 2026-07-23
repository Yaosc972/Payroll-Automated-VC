param(
  [string]$MaterialsRoot = "",
  [switch]$SkipDependencies
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") {
  throw "The Windows installer must be built on Windows 10/11 x64."
}
if (-not [Environment]::Is64BitOperatingSystem) {
  throw "Only Windows 10/11 x64 is supported."
}

$DesktopRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $DesktopRoot
$BuildCacheRoot = Join-Path $env:LOCALAPPDATA "SigmaWorkerBuild"
$VenvRoot = Join-Path $BuildCacheRoot "py311"
$BuildPython = Join-Path $VenvRoot "Scripts\python.exe"
$BuildPip = Join-Path $VenvRoot "Scripts\pip.exe"

function Find-Python {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" *> $null
    if ($LASTEXITCODE -eq 0) {
      return @{ Command = "py"; Prefix = @("-3.11") }
    }
  }
  if (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    if ($LASTEXITCODE -eq 0 -and $PythonVersion -eq "3.11") {
      return @{ Command = "python"; Prefix = @() }
    }
  }
  throw "Python 3.11 x64 was not found. Install Python 3.11 x64 and run build-windows.cmd again. Python 3.13 is not supported by the pinned OCR runtime."
}

function Invoke-Checked {
  param(
    [string]$Command,
    [string[]]$Arguments
  )
  & $Command @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed: $Command $($Arguments -join ' ')"
  }
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  throw "Node.js was not found. Install Node.js 20 LTS x64 and run build-windows.cmd again."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  throw "npm was not found. Reinstall Node.js 20 LTS x64."
}

Push-Location $DesktopRoot
try {
  $SystemPython = Find-Python
  if (-not (Test-Path $BuildPython) -or -not (Test-Path $BuildPip)) {
    Invoke-Checked $SystemPython.Command (@($SystemPython.Prefix) + @("-m", "venv", "--clear", $VenvRoot))
  }

  if (-not $SkipDependencies) {
    Invoke-Checked $BuildPython @("-m", "ensurepip", "--upgrade")
    Invoke-Checked $BuildPython @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Checked $BuildPython @(
      "-m", "pip", "install",
      "-r", (Join-Path $ProjectRoot "requirements.txt"),
      "-r", (Join-Path $DesktopRoot "requirements-worker.txt"),
      "pyinstaller", "pillow"
    )
    Invoke-Checked "npm" @("ci")
  }

  $LocalMaterials = Join-Path $DesktopRoot "release-gate-materials"
  if (-not $MaterialsRoot -and (Test-Path $LocalMaterials)) {
    $MaterialsRoot = $LocalMaterials
  }
  if ($MaterialsRoot) {
    $ResolvedMaterials = (Resolve-Path $MaterialsRoot).Path
    $env:SIGMA_LABOR_GOLDEN_MATERIALS_ROOT = $ResolvedMaterials
  }
  $env:PYTHON = $BuildPython

  Write-Host "[1/3] Running the approved legacy-invoice release gate..." -ForegroundColor Cyan
  Invoke-Checked "npm" @("run", "release:gate")
  Write-Host "[2/3] Packaging the Windows x64 Worker..." -ForegroundColor Cyan
  Invoke-Checked "npm" @("run", "build:worker")
  Write-Host "[3/3] Building the unsigned NSIS installer..." -ForegroundColor Cyan
  Invoke-Checked "npx" @("electron-builder", "--win", "nsis", "--x64")

  $PackageMetadata = Get-Content (Join-Path $DesktopRoot "package.json") -Encoding UTF8 -Raw | ConvertFrom-Json
  $PackageVersion = $PackageMetadata.version
  $InstallerName = "$($PackageMetadata.build.productName)-$PackageVersion-windows-x64.exe"
  $Installer = Join-Path (Join-Path $DesktopRoot "release") $InstallerName
  if (-not (Test-Path $Installer)) {
    throw "Build finished but the installer was not found: $Installer"
  }
  $Hash = (Get-FileHash $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
  Write-Host "Windows x64 installer created:" -ForegroundColor Green
  Write-Host $Installer
  Write-Host "SHA-256: $Hash"
} finally {
  Pop-Location
}
