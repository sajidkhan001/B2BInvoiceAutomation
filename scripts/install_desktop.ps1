$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$SourceDir = Join-Path $Root "dist\B2B Invoice Automation"
$ExeName = "B2B Invoice Automation.exe"
$SourceExe = Join-Path $SourceDir $ExeName

if (-not (Test-Path -LiteralPath $SourceExe)) {
    throw "Build output not found. Run .\scripts\build_desktop.ps1 first."
}

$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\B2B Invoice Automation"
if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Copy-Item -Path (Join-Path $SourceDir "*") -Destination $InstallDir -Recurse -Force

$InstalledExe = Join-Path $InstallDir $ExeName
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\B2B Invoice Automation"
New-Item -ItemType Directory -Path $StartMenuDir -Force | Out-Null

$Shell = New-Object -ComObject WScript.Shell
$StartShortcut = $Shell.CreateShortcut((Join-Path $StartMenuDir "B2B Invoice Automation.lnk"))
$StartShortcut.TargetPath = $InstalledExe
$StartShortcut.WorkingDirectory = $InstallDir
$StartShortcut.Description = "B2B Invoice Automation"
$StartShortcut.Save()

$DesktopShortcut = $Shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "B2B Invoice Automation.lnk"))
$DesktopShortcut.TargetPath = $InstalledExe
$DesktopShortcut.WorkingDirectory = $InstallDir
$DesktopShortcut.Description = "B2B Invoice Automation"
$DesktopShortcut.Save()

Write-Host ""
Write-Host "Installed B2B Invoice Automation for this Windows user."
Write-Host "Start menu shortcut: $(Join-Path $StartMenuDir 'B2B Invoice Automation.lnk')"
Write-Host "Desktop shortcut: $(Join-Path ([Environment]::GetFolderPath('Desktop')) 'B2B Invoice Automation.lnk')"
Write-Host "App executable: $InstalledExe"
