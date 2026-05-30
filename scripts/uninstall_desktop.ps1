$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\B2B Invoice Automation"
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\B2B Invoice Automation"
$DesktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "B2B Invoice Automation.lnk"

if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}
if (Test-Path -LiteralPath $StartMenuDir) {
    Remove-Item -LiteralPath $StartMenuDir -Recurse -Force
}
if (Test-Path -LiteralPath $DesktopShortcut) {
    Remove-Item -LiteralPath $DesktopShortcut -Force
}

if ($IsWindows) {
    $RunKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    Remove-ItemProperty -Path $RunKey -Name "B2BDocAutomation" -ErrorAction SilentlyContinue
}

Write-Host "B2B Invoice Automation has been uninstalled for this Windows user."
