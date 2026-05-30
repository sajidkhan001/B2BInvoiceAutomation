$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    py -m venv .venv
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
}

& $Python -m pip install -e ".[dev]"
& $Python -m pytest

$BuildPath = Join-Path $Root "build"
$DistPath = Join-Path $Root "dist"
if (Test-Path -LiteralPath $BuildPath) {
    Remove-Item -LiteralPath $BuildPath -Recurse -Force
}
if (Test-Path -LiteralPath $DistPath) {
    Remove-Item -LiteralPath $DistPath -Recurse -Force
}

& $Python -m PyInstaller --clean --noconfirm "B2BInvoiceAutomation.spec"

$ExePath = Join-Path $Root "dist\B2B Invoice Automation\B2B Invoice Automation.exe"
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "Build failed: $ExePath was not created."
}

Write-Host ""
Write-Host "Desktop app built:"
Write-Host $ExePath
Write-Host ""
Write-Host "Install for the current Windows user with:"
Write-Host ".\scripts\install_desktop.ps1"
