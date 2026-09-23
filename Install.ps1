#Requires -Version 5.1
<#
.SYNOPSIS
  Installs Control MySQL Services: dependencies, elevated logon task, Manual service mode.
#>
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "=== Control MySQL Services — Install ===" -ForegroundColor Cyan

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).
    IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Requesting Administrator privileges..."
    Start-Process powershell -Verb RunAs -Wait -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`""
    )
    exit
}

Write-Host "Installing Python packages..."
python -m pip install -r "$Root\requirements.txt"

Write-Host "Creating elevated logon task (tray at startup with admin rights)..."
$pythonwCmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if ($pythonwCmd) {
    $pythonw = $pythonwCmd.Source
} else {
    $pythonw = (Get-Command python.exe).Source
}
$app = Join-Path $Root "app.py"
$taskName = "ControlMySQLServices"

Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" `
    -Name "ControlMySQLServices" -ErrorAction SilentlyContinue

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$app`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings | Out-Null
Write-Host "Scheduled task ready: $taskName"

Write-Host "Setting MySQL Windows services to Manual + no failure auto-restart..."
Get-CimInstance Win32_Service |
    Where-Object {
        $_.PathName -match 'mysqld\.exe|mariadbd\.exe|mysql\\|mariadb\\' -or
        $_.Name -match 'mysql|mariadb|percona' -or
        $_.DisplayName -match 'mysql|mariadb|percona'
    } |
    ForEach-Object {
        Write-Host ("  {0}  ({1} -> Manual, clear failure restart)" -f $_.Name, $_.StartMode)
        Set-Service -Name $_.Name -StartupType Manual
        sc.exe failure $_.Name reset= 0 actions= ""/0/""/0/""/0 | Out-Null
        sc.exe failureflag $_.Name 0 | Out-Null
    }

# SalesUp app starts VatoceSalesUp MySQL when it launches — disable its Startup shortcut
$salesUpLnk = "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup\SalesUp.lnk"
$salesUpBak = "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup\SalesUp.lnk.disabled-by-ControlMySQL"
if (Test-Path $salesUpLnk) {
    if (Test-Path $salesUpBak) { Remove-Item $salesUpBak -Force }
    Move-Item $salesUpLnk $salesUpBak -Force
    Write-Host "Disabled Startup shortcut: SalesUp.lnk (was starting MrSales -> MySQL)"
}

# Remove VatoceSalesUp Watchdog (forces MySQL every 3 minutes)
Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
    $_.TaskName -match 'VatoceSalesUp' -or
    (($_.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join ' ') -match 'ForceStart-VatoceSalesUp|VatoceSalesUp-Watchdog'
} | ForEach-Object {
    Write-Host "Removing scheduled task: $($_.TaskName)"
    Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false -ErrorAction SilentlyContinue
}

$forceTools = @(
    'D:\WorkTemp\Current\MrSales\tools\ForceStart-VatoceSalesUp.ps1',
    'D:\WorkTemp\Current\MrSales\tools\ForceStart-VatoceSalesUp.bat',
    'D:\WorkTemp\Current\MrSales\tools\Install-VatoceSalesUp-AutoRecovery.ps1',
    'D:\WorkTemp\Current\MrSales\tools\Install-VatoceSalesUp-AutoRecovery.bat'
)
foreach ($f in $forceTools) {
    if (Test-Path $f) {
        $bak = "$f.disabled-by-ControlMySQL"
        if (Test-Path $bak) { Remove-Item $bak -Force }
        Move-Item $f $bak -Force
        Write-Host "Disabled: $f"
    }
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "- Tray app starts at logon (elevated task)."
Write-Host "- MySQL services stay Manual — they will NOT auto-start."
Write-Host "Launch tray app now? (Y/N)"
$ans = Read-Host
if ($ans -match '^(y|Y)') {
    Start-Process -FilePath (Join-Path $Root "Start.bat")
}
