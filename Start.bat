@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: Elevate to Administrator (required to start/stop Windows services)
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "%~dp0app.py"
) else (
    start "" python "%~dp0app.py"
)
