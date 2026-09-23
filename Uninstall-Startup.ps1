#Requires -Version 5.1
$ErrorActionPreference = "SilentlyContinue"
schtasks /Delete /TN "ControlMySQLServices" /F | Out-Null
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" `
    -Name "ControlMySQLServices" -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match 'ControlMySQLSErvices\\app\.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Host "Removed startup task/entry and stopped tray app (if running)."
Write-Host "MySQL service StartupType was left unchanged."
