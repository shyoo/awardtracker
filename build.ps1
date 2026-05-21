# Award Tracker - Premium Build Script
# Usage: .\build.ps1

Clear-Host
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "      Award Tracker Executable Builder            " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

$SpecFile = "awardtracker.spec"
$VenvPath = "venv\Scripts\Activate.ps1"
$ExePath = "dist\awardtracker.exe"

# 1. Verify Spec file
if (-not (Test-Path $SpecFile)) {
    Write-Error "Specification file '$SpecFile' not found in current directory."
    Exit 1
}

# 2. Verify Virtual Environment
if (-not (Test-Path $VenvPath)) {
    Write-Warning "Virtual environment not found at '$VenvPath'. Attempting to compile using global system python..."
} else {
    Write-Host "Activating virtual environment..." -ForegroundColor Green
    . $VenvPath
}

# 3. Check if PyInstaller is installed
if (-not (Get-Command "pyinstaller" -ErrorAction SilentlyContinue)) {
    Write-Error "PyInstaller is not installed. Please run 'pip install pyinstaller' inside your virtual environment first."
    Exit 1
}

# 4. Clean previous builds
Write-Host "Cleaning previous build directories..." -ForegroundColor Gray
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }

# 5. Build Executable
Write-Host "Starting PyInstaller compilation (this may take a minute)..." -ForegroundColor Yellow
pyinstaller --clean -y $SpecFile

# 6. Verify Output
if (Test-Path $ExePath) {
    $file = Get-Item $ExePath
    $sizeMB = [Math]::Round($file.Length / 1MB, 2)
    Write-Host "`n==================================================" -ForegroundColor Green
    Write-Host "          BUILD COMPLETED SUCCESSFULLY!           " -ForegroundColor Green
    Write-Host "==================================================" -ForegroundColor Green
    Write-Host "Executable generated at: $ExePath" -ForegroundColor White
    Write-Host "Binary Size: $sizeMB MB" -ForegroundColor White
} else {
    Write-Error "Compilation completed, but '$ExePath' was not generated. Please check PyInstaller logs above."
    Exit 1
}
