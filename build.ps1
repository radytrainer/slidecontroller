# Build AirSlide for other computers.
#
#   powershell -ExecutionPolicy Bypass -File build.ps1              -> dist\AirSlide-Setup-<version>.exe (installer)
#   powershell -ExecutionPolicy Bypass -File build.ps1 -SingleFile  -> dist\AirSlide.exe (portable, one file)
#
# The installer is recommended: it installs AirSlide as a normal program folder,
# which antivirus programs trust much more than a single self-unpacking .exe.
#
# Requires the project venv with requirements installed (pyinstaller is added if
# missing) and, for the installer, Inno Setup 6 (winget install JRSoftware.InnoSetup).

param([switch]$SingleFile)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = ".\venv\Scripts\python.exe"

if (-not (Test-Path $python)) { throw "venv not found - create it first (see README, Installation)." }

$iscc = $null
if (-not $SingleFile) {
    $iscc = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) { throw "Inno Setup 6 not found - install it: winget install JRSoftware.InnoSetup" }
}

& $python -m pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) { & $python -m pip install pyinstaller }

$version = (& $python -c "import config; print(config.APP_VERSION)").Trim()

Write-Host "1/5 Checking the hand and pose models..."
& $python -c "import config; from src.hand.hand_detector import ensure_model; print('   ', ensure_model()); print('   ', ensure_model(config.POSE_MODEL_PATH, config.POSE_MODEL_URL))"

Write-Host "2/5 Creating the icon..."
& $python -m tools.make_icon

Write-Host "3/5 Running tests..."
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed - not building." }

if ($SingleFile) {
    Write-Host "4/5 Building the single file dist\AirSlide.exe (takes a few minutes)..."
    $env:AIRSLIDE_BUILD = "onefile"
    & $python -m PyInstaller AirSlide.spec --noconfirm --clean
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
    $exe = Get-Item dist\AirSlide.exe
    Write-Host ("Done: {0} ({1:N0} MB)" -f $exe.FullName, ($exe.Length / 1MB))
    return
}

Write-Host "4/5 Building the program folder dist\AirSlide\ (takes a few minutes)..."
$env:AIRSLIDE_BUILD = "folder"
& $python -m PyInstaller AirSlide.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

Write-Host "5/5 Building the installer..."
& $iscc /Q "/DAppVersion=$version" installer\AirSlide.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }

$setup = Get-Item "dist\AirSlide-Setup-$version.exe"
Write-Host ("Done: {0} ({1:N0} MB)" -f $setup.FullName, ($setup.Length / 1MB))
