# Award Tracker - Premium Release Packaging Script
# Usage: .\release-win.ps1

Clear-Host
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "      Award Tracker Release Builder Tool          " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

$VenvPath = "venv\Scripts\Activate.ps1"
$SpecFile = "awardtracker.spec"
$IssFile = "installer.iss"
$DistDir = "dist"

$VersionSuffix = ""
if (Test-Path "version.txt") {
    $AppVersion = (Get-Content "version.txt").Trim()
    if ($AppVersion) {
        $VersionSuffix = "-v$AppVersion"
    }
}

$PortableZip = "dist\awardtracker-win64-portable$VersionSuffix.zip"
$SetupExe = "dist\awardtracker-win64-setup$VersionSuffix.exe"

# 1. Verify environment
if (-not (Test-Path $SpecFile)) {
    Write-Error "Specification file '$SpecFile' not found."
    Exit 1
}

# Activate virtual environment if available
if (Test-Path $VenvPath) {
    Write-Host "Activating virtual environment..." -ForegroundColor Green
    . $VenvPath
}

# 2. Run compilation build script
Write-Host "Step 1: Compiling standalone binary..." -ForegroundColor Yellow
if (Test-Path "build-win.ps1") {
    powershell -ExecutionPolicy Bypass -File build-win.ps1
} else {
    Write-Host "Running PyInstaller manually..." -ForegroundColor Gray
    if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
    if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
    pyinstaller --clean -y $SpecFile
}

$ExePath = "dist\awardtracker.exe"
if (-not (Test-Path $ExePath)) {
    Write-Error "Compilation failed. Standalone binary '$ExePath' was not generated."
    Exit 1
}

Write-Host "`nStep 2: Packaging Portable ZIP Distribution..." -ForegroundColor Yellow
# Create a temporary portable folder structure for clean extraction
$TempPortableDir = "dist\AwardTracker-Portable"
if (Test-Path $TempPortableDir) { Remove-Item -Recurse -Force $TempPortableDir }
New-Item -ItemType Directory -Path $TempPortableDir -Force > $null

# Copy executable and settings configuration to portable folder
Copy-Item $ExePath -Destination $TempPortableDir\awardtracker.exe -Force
if (Test-Path "settings.json") {
    Copy-Item "settings.json" -Destination $TempPortableDir\settings.json -Force
}

# Clean old portable ZIP if it exists
if (Test-Path $PortableZip) { Remove-Item $PortableZip -Force }

# Compress the folder structure using native PowerShell utility
Compress-Archive -Path $TempPortableDir -DestinationPath $PortableZip -Force
Remove-Item -Recurse -Force $TempPortableDir # Clean up temp directory

if (Test-Path $PortableZip) {
    $zipFile = Get-Item $PortableZip
    $zipSize = [Math]::Round($zipFile.Length / 1MB, 2)
    Write-Host "Portable ZIP created successfully at: $PortableZip ($zipSize MB)" -ForegroundColor Green
} else {
    Write-Warning "Failed to generate portable ZIP archive."
}

Write-Host "`nStep 3: Compiling Setup Wizard Installer..." -ForegroundColor Yellow
# Find Inno Setup Compiler (ISCC.exe)
$IsccPath = $null

# Search 1: System Environment PATH
if (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue) {
    $IsccPath = "ISCC.exe"
}

# Search 2: Common Program Files directories
$CommonPaths = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)

if ($null -eq $IsccPath) {
    foreach ($path in $CommonPaths) {
        if (Test-Path $path) {
            $IsccPath = $path
            break
        }
    }
}

if ($null -ne $IsccPath) {
    Write-Host "Found Inno Setup Compiler at: $IsccPath" -ForegroundColor Gray
    Write-Host "Compiling Windows setup wizard silently..." -ForegroundColor Gray
    
    # Run the Inno Setup compiler with output filename override to include version suffix
    & $IsccPath /Q /F"awardtracker-win64-setup$VersionSuffix" $IssFile
    
    if (Test-Path $SetupExe) {
        $setupFile = Get-Item $SetupExe
        $setupSize = [Math]::Round($setupFile.Length / 1MB, 2)
        Write-Host "Setup Wizard generated successfully at: $SetupExe ($setupSize MB)" -ForegroundColor Green
    } else {
        Write-Error "Installer compilation completed, but '$SetupExe' was not found."
    }
} else {
    Write-Warning "Inno Setup Compiler (ISCC.exe) was not found on your system."
    Write-Host "To generate 'awardtracker-setup.exe', please download and install Inno Setup 6 from:" -ForegroundColor Yellow
    Write-Host "👉 https://jrsoftware.org/isdl.php" -ForegroundColor Yellow
    Write-Host "Once Inno Setup is installed, run this script again or right-click 'installer.iss' and select 'Compile'." -ForegroundColor Gray
}

Write-Host "`n==================================================" -ForegroundColor Cyan
Write-Host "            DISTRIBUTION SUMMARY                  " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
if (Test-Path $PortableZip) {
    $file = Get-Item $PortableZip
    $pSize = [Math]::Round($file.Length/1MB, 2)
    Write-Host "  [Portable]  $PortableZip ($pSize MB)" -ForegroundColor Green
}
if (Test-Path $SetupExe) {
    $file = Get-Item $SetupExe
    $iSize = [Math]::Round($file.Length/1MB, 2)
    Write-Host "  [Installer] $SetupExe ($iSize MB)" -ForegroundColor Green
}
Write-Host "==================================================" -ForegroundColor Cyan
