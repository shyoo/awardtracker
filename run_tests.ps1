# Award Tracker - Premium Test Runner Script
# Usage: .\run_tests.ps1

Clear-Host
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "      Award Tracker Unit Test Runner              " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

$VenvPath = "venv\Scripts\Activate.ps1"
$PythonCmd = "python"

# 1. Verify and Activate Virtual Environment
if (-not (Test-Path $VenvPath)) {
    Write-Warning "Virtual environment not found at '$VenvPath'. Attempting to run using global system python..."
} else {
    Write-Host "Activating virtual environment..." -ForegroundColor Green
    . $VenvPath
}

# 2. Run test discovery
Write-Host "Starting unit tests discovery and execution...`n" -ForegroundColor Yellow

# Execute tests with unittest discover
& $PythonCmd -m unittest discover -s tests -p "test_*.py"

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n==================================================" -ForegroundColor Green
    Write-Host "          ALL TESTS PASSED SUCCESSFULLY!           " -ForegroundColor Green
    Write-Host "==================================================" -ForegroundColor Green
} else {
    Write-Host "`n==================================================" -ForegroundColor Red
    Write-Host "               SOME TESTS FAILED!                  " -ForegroundColor Red
    Write-Host "==================================================" -ForegroundColor Red
    Exit $LASTEXITCODE
}
