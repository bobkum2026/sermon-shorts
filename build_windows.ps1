<#
.SYNOPSIS
    Sermon Shorts Generator - Windows Build Script
.DESCRIPTION
    Builds a standalone .exe for Windows.
    Run this in PowerShell from the Short-form directory.
#>

$ErrorActionPreference = "Stop"
Write-Host ""
Write-Host "=== Sermon Shorts Generator - Windows Build ===" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Check Python ──
Write-Host "[1/5] Checking Python..." -ForegroundColor Yellow
try {
    $pyVer = python --version 2>&1
    Write-Host "  Found: $pyVer" -ForegroundColor Green
} catch {
    Write-Host "  Python not found! Install from https://python.org" -ForegroundColor Red
    Write-Host "  Make sure to check 'Add Python to PATH' during install" -ForegroundColor Red
    exit 1
}

# ── Step 2: Install Python packages ──
Write-Host "[2/5] Installing Python packages..." -ForegroundColor Yellow
pip install --upgrade pip | Out-Null
pip install -r requirements.txt pyinstaller | Out-Null
Write-Host "  Done" -ForegroundColor Green

# ── Step 3: Download ffmpeg for Windows ──
Write-Host "[3/5] Downloading ffmpeg for Windows..." -ForegroundColor Yellow
$ffmpegDir = ".\ffmpeg"
if (-not (Test-Path "$ffmpegDir\ffmpeg.exe")) {
    New-Item -ItemType Directory -Force -Path $ffmpegDir | Out-Null

    $ffmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    $zipPath = "$env:TEMP\ffmpeg.zip"

    Write-Host "  Downloading from GitHub..." -ForegroundColor Gray
    Invoke-WebRequest -Uri $ffmpegUrl -OutFile $zipPath

    Write-Host "  Extracting..." -ForegroundColor Gray
    Expand-Archive -Path $zipPath -DestinationPath "$env:TEMP\ffmpeg_extract" -Force

    # Find and copy binaries
    $binDir = Get-ChildItem "$env:TEMP\ffmpeg_extract" -Recurse -Directory -Filter "bin" | Select-Object -First 1
    Copy-Item "$($binDir.FullName)\ffmpeg.exe" "$ffmpegDir\ffmpeg.exe"
    Copy-Item "$($binDir.FullName)\ffprobe.exe" "$ffmpegDir\ffprobe.exe"

    # Cleanup
    Remove-Item $zipPath -Force
    Remove-Item "$env:TEMP\ffmpeg_extract" -Recurse -Force

    Write-Host "  ffmpeg.exe installed" -ForegroundColor Green
} else {
    Write-Host "  ffmpeg already present" -ForegroundColor Green
}

# ── Step 4: Download Korean font ──
Write-Host "[4/5] Checking Korean font..." -ForegroundColor Yellow
$fontPath = ".\assets\fonts\NotoSansKR-Bold.ttf"
if (-not (Test-Path $fontPath)) {
    New-Item -ItemType Directory -Force -Path ".\assets\fonts" | Out-Null

    # Download from Google Fonts API
    Write-Host "  Downloading Noto Sans KR..." -ForegroundColor Gray
    $cssUrl = "https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@700"
    $css = Invoke-WebRequest -Uri $cssUrl -Headers @{"User-Agent"="Mozilla/5.0"} | Select-Object -ExpandProperty Content

    # Extract OTF URL from CSS
    if ($css -match "src: url\((https://[^)]+\.otf)\)") {
        $fontUrl = $Matches[1]
        Invoke-WebRequest -Uri $fontUrl -OutFile $fontPath
        Write-Host "  Font installed" -ForegroundColor Green
    } else {
        Write-Host "  Warning: Could not download font. Korean text may not display correctly." -ForegroundColor Yellow
    }
} else {
    Write-Host "  Font already present" -ForegroundColor Green
}

# ── Step 5: Build with PyInstaller ──
Write-Host "[5/5] Building executable..." -ForegroundColor Yellow

# Add ffmpeg to the spec datas
$specContent = Get-Content "sermon_shorts.spec" -Raw
if ($specContent -notmatch "ffmpeg") {
    $specContent = $specContent -replace "datas=\[", "datas=[`n        ('ffmpeg', 'ffmpeg'),"
    Set-Content "sermon_shorts.spec" $specContent
}

pyinstaller sermon_shorts.spec --noconfirm 2>&1 | ForEach-Object {
    if ($_ -match "ERROR|error") { Write-Host "  $_" -ForegroundColor Red }
}

# ── Done ──
if (Test-Path ".\dist\SermonShorts\SermonShorts.exe") {
    # Copy .env.example next to the exe
    Copy-Item ".env.example" ".\dist\SermonShorts\.env.example" -Force

    Write-Host ""
    Write-Host "=== Build Complete! ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Output: dist\SermonShorts\SermonShorts.exe" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Setup:" -ForegroundColor Yellow
    Write-Host "  1. Copy dist\SermonShorts folder anywhere" -ForegroundColor White
    Write-Host "  2. Rename .env.example to .env" -ForegroundColor White
    Write-Host "  3. Add your API keys to .env" -ForegroundColor White
    Write-Host "  4. Double-click SermonShorts.exe" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "  Build failed! Check errors above." -ForegroundColor Red
    Write-Host ""
}
