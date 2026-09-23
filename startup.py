"""Windows startup registration and admin helpers."""

from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path

TASK_NAME = "ControlMySQLServices"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _pythonw() -> Path:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return pythonw if pythonw.exists() else Path(sys.executable)


def launch_parts() -> tuple[str, str]:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve()), ""
    return str(_pythonw()), f'"{app_dir() / "app.py"}"'


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> None:
    script = str(app_dir() / "app.py")
    params = f'"{script}"'
    ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        sys.executable,
        params,
        str(app_dir()),
        1,
    )


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def is_startup_enabled() -> bool:
    result = _run(["schtasks", "/Query", "/TN", TASK_NAME])
    return result.returncode == 0


def enable_startup() -> None:
    exe, args = launch_parts()
    # PowerShell Register-ScheduledTask handles spaces in paths reliably.
    # Highest privileges so start/stop service works after reboot.
    ps = f"""
$ErrorActionPreference = 'Stop'
$taskName = '{TASK_NAME}'
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute '{exe.replace("'", "''")}' -Argument '{args.replace("'", "''")}'
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
"""
    result = _run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            ps,
        ]
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or "Failed to create startup scheduled task")


def disable_startup() -> None:
    _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
