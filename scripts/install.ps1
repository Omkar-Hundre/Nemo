<#
.SYNOPSIS
    One-click automated installer for NEMO on Windows.
.DESCRIPTION
    Installs NEMO globally, configures user PATH, initializes local database,
    and sets up credentials.
#>

param(
    [string]$ApiKey = ""
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "         NEMO - Developer Operating Assistant for Windows     " -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repoRoot

# 1. Check / Install uv
Write-Host "[1/5] Checking toolchain prerequisites..." -ForegroundColor White
$hasUv = (Get-Command uv -ErrorAction SilentlyContinue)

if (-not $hasUv) {
    Write-Host "      'uv' package manager not found. Installing uv..." -ForegroundColor Yellow
    try {
        irm https://astral.sh/uv/install.ps1 | iex
        $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
    } catch {
        Write-Error "Failed to install uv automatically. Please install Python 3.11+ or uv manually."
        exit 1
    }
} else {
    Write-Host "      [OK] uv package manager detected." -ForegroundColor Green
}

# 2. Install NEMO globally via uv tool
Write-Host "[2/5] Installing NEMO CLI globally..." -ForegroundColor White
try {
    uv tool install --editable "$repoRoot" --force
    Write-Host "      [OK] NEMO executable installed to $env:USERPROFILE\.local\bin\nemo.exe" -ForegroundColor Green
} catch {
    Write-Host "      Warning: uv tool install encountered issue. Trying fallback install..." -ForegroundColor Yellow
    uv pip install -e "$repoRoot"
}

# 3. Ensure User PATH includes ~/.local/bin
Write-Host "[3/5] Verifying Windows PATH configuration..." -ForegroundColor White
$localBin = "$env:USERPROFILE\.local\bin"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$localBin*") {
    Write-Host "      Adding $localBin to User PATH..." -ForegroundColor Yellow
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$localBin", "User")
    $env:PATH = "$localBin;$env:PATH"
}
Write-Host "      [OK] Windows PATH verified." -ForegroundColor Green

# 4. Configure credentials in ~/.nemo/.env
Write-Host "[4/5] Setting up credentials and local storage..." -ForegroundColor White
$nemoHome = "$env:USERPROFILE\.nemo"
if (-not (Test-Path $nemoHome)) {
    New-Item -ItemType Directory -Path $nemoHome -Force | Out-Null
}

$envFile = "$nemoHome\.env"
if (-not (Test-Path $envFile) -or (Get-Content $envFile -Raw) -notmatch "nvapi-") {
    if ($ApiKey -and $ApiKey.StartsWith("nvapi-")) {
        Set-Content -Path $envFile -Value "NVIDIA_API_KEY=$ApiKey`n" -Encoding UTF8
        Write-Host "      [OK] API key configured from argument." -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "Enter your NVIDIA NIM API Key (starts with 'nvapi-'):" -ForegroundColor Yellow
        Write-Host "(Press Enter to skip and configure later with 'nemo setup')" -ForegroundColor DarkGray
        $inputKey = Read-Host "API Key"
        if ($inputKey -and $inputKey.StartsWith("nvapi-")) {
            Set-Content -Path $envFile -Value "NVIDIA_API_KEY=$inputKey`n" -Encoding UTF8
            Write-Host "      [OK] API key saved to ~/.nemo/.env" -ForegroundColor Green
        } else {
            Write-Host "      [INFO] API key skipped. Configure anytime with 'nemo setup'." -ForegroundColor DarkYellow
        }
    }
} else {
    Write-Host "      [OK] Existing credentials found in ~/.nemo/.env." -ForegroundColor Green
}

# 5. Initialize Database & Run Status
Write-Host "[5/5] Initializing database schema..." -ForegroundColor White
try {
    & "$localBin\nemo.exe" memory init
    Write-Host "      [OK] Memory database ready." -ForegroundColor Green
} catch {
    Write-Host "      [WARN] Database init note: $_" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Green
Write-Host "🎉 NEMO is installed and ready to use everywhere on Windows!  " -ForegroundColor Green
Write-Host "==============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "You can now open any Command Prompt or PowerShell and type:" -ForegroundColor White
Write-Host "   nemo `"what can you do?`"" -ForegroundColor Cyan
Write-Host "   nemo `"analyze this project`"" -ForegroundColor Cyan
Write-Host "   nemo status" -ForegroundColor Cyan
Write-Host "   nemo" -ForegroundColor Cyan
Write-Host ""

