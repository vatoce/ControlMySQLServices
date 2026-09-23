"""Discover and control MySQL / MariaDB — Windows services and standalone processes."""

from __future__ import annotations

import hashlib
import re
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import win32api
import win32con
import win32process
import win32service
import win32serviceutil

try:
    import win32com.client  # type: ignore
except ImportError:
    win32com = None  # type: ignore

MYSQL_PATH_HINTS = re.compile(
    r"mysqld\.exe|mariadbd\.exe|mysql[\\/]|mariadb[\\/]",
    re.IGNORECASE,
)
MYSQL_NAME_HINTS = re.compile(r"mysql|mariadb|percona", re.IGNORECASE)
PORT_RE = re.compile(r"^\s*port\s*=\s*(\d+)", re.IGNORECASE | re.MULTILINE)
DEFAULTS_FILE_RE = re.compile(
    r"""--defaults-file=(?:"([^"]+)"|'([^']+)'|(\S+))""",
    re.IGNORECASE,
)
PORT_ARG_RE = re.compile(r"""--port(?:=|\s+)(\d+)""", re.IGNORECASE)
EXE_FROM_CMDLINE_RE = re.compile(r'^"([^"]+)"|^(\S+)')

KIND_SERVICE = "service"
KIND_PORTABLE = "portable"  # known install (Laragon/XAMPP/…) or standalone process

PORTABLE_ROOTS = [
    Path(r"C:\laragon"),
    Path(r"D:\laragon"),
    Path(r"E:\laragon"),
    Path(r"C:\xampp"),
    Path(r"D:\xampp"),
    Path(r"E:\xampp"),
    Path(r"C:\wamp"),
    Path(r"C:\wamp64"),
    Path(r"D:\wamp"),
    Path(r"D:\wamp64"),
]

# Extra places to look for mysqld.exe (depth-limited walk).
SCAN_ROOTS = [
    Path(r"C:\Program Files\MySQL"),
    Path(r"C:\Program Files (x86)\MySQL"),
    Path(r"C:\Program Files\MariaDB"),
    Path(r"C:\Program Files (x86)\MariaDB"),
    Path(r"C:\tools"),
    Path(r"D:\tools"),
]


@dataclass
class MySqlService:
    name: str
    display_name: str
    status: str
    start_type: str
    kind: str = KIND_SERVICE
    mysqld_path: str | None = None
    mysqladmin_path: str | None = None
    defaults_file: str | None = None
    port: int | None = None
    pids: list[int] = field(default_factory=list)

    @property
    def is_running(self) -> bool:
        return self.status == "Running"

    @property
    def is_manual(self) -> bool:
        return self.start_type == "Manual"

    @property
    def is_portable(self) -> bool:
        return self.kind == KIND_PORTABLE


def _status_name(code: int) -> str:
    mapping = {
        win32service.SERVICE_STOPPED: "Stopped",
        win32service.SERVICE_START_PENDING: "Starting",
        win32service.SERVICE_STOP_PENDING: "Stopping",
        win32service.SERVICE_RUNNING: "Running",
        win32service.SERVICE_CONTINUE_PENDING: "Continuing",
        win32service.SERVICE_PAUSE_PENDING: "Pausing",
        win32service.SERVICE_PAUSED: "Paused",
    }
    return mapping.get(code, f"Unknown({code})")


def _start_type_name(code: int) -> str:
    mapping = {
        win32service.SERVICE_AUTO_START: "Automatic",
        win32service.SERVICE_DEMAND_START: "Manual",
        win32service.SERVICE_DISABLED: "Disabled",
        win32service.SERVICE_BOOT_START: "Boot",
        win32service.SERVICE_SYSTEM_START: "System",
    }
    return mapping.get(code, f"Unknown({code})")


def _looks_like_mysql(name: str, display_name: str, binary_path: str) -> bool:
    if MYSQL_PATH_HINTS.search(binary_path or ""):
        return True
    if MYSQL_NAME_HINTS.search(name or "") or MYSQL_NAME_HINTS.search(display_name or ""):
        return True
    return False


def _norm(path: str | Path | None) -> str | None:
    if not path:
        return None
    try:
        return str(Path(path).resolve()).lower()
    except OSError:
        return str(path).lower()


def _read_port(ini_path: Path) -> int | None:
    try:
        text = ini_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    mysqld = re.search(r"\[mysqld\](.*?)(\n\[|\Z)", text, re.IGNORECASE | re.DOTALL)
    chunk = mysqld.group(1) if mysqld else text
    match = PORT_RE.search(chunk)
    return int(match.group(1)) if match else None


def _port_open(port: int | None, host: str = "127.0.0.1") -> bool:
    if not port:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.35)
        try:
            return sock.connect_ex((host, port)) == 0
        except OSError:
            return False


def _process_image_path(pid: int) -> str | None:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        kernel32.CloseHandle(handle)


def _extract_exe_from_pathname(pathname: str) -> str | None:
    if not pathname:
        return None
    match = EXE_FROM_CMDLINE_RE.match(pathname.strip())
    if not match:
        return None
    return match.group(1) or match.group(2)


def _parse_defaults_file(cmdline: str | None) -> str | None:
    if not cmdline:
        return None
    match = DEFAULTS_FILE_RE.search(cmdline)
    if not match:
        return None
    return match.group(1) or match.group(2) or match.group(3)


def _parse_port_arg(cmdline: str | None) -> int | None:
    if not cmdline:
        return None
    match = PORT_ARG_RE.search(cmdline)
    return int(match.group(1)) if match else None


def _wmi_mysql_processes() -> list[dict]:
    """Return running mysqld/mariadbd with path + command line via WMI."""
    results: list[dict] = []
    if win32com is None:
        return results
    try:
        locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
        svc = locator.ConnectServer(".", "root\\cimv2")
        for name in ("mysqld.exe", "mariadbd.exe"):
            for proc in svc.ExecQuery(
                f"SELECT ProcessId, ExecutablePath, CommandLine FROM Win32_Process WHERE Name='{name}'"
            ):
                results.append(
                    {
                        "pid": int(proc.ProcessId),
                        "path": proc.ExecutablePath,
                        "cmdline": proc.CommandLine,
                    }
                )
    except Exception:
        # Fallback: enumerate PIDs without command line.
        for pid in win32process.EnumProcesses():
            image = _process_image_path(pid)
            if not image:
                continue
            if Path(image).name.lower() in {"mysqld.exe", "mariadbd.exe"}:
                results.append({"pid": pid, "path": image, "cmdline": None})
    return results


def _find_nearby_admin(mysqld_path: Path) -> str | None:
    admin = mysqld_path.parent / "mysqladmin.exe"
    return str(admin) if admin.is_file() else None


def _find_nearby_ini(mysqld_path: Path, cmdline: str | None = None) -> str | None:
    from_cmd = _parse_defaults_file(cmdline)
    if from_cmd and Path(from_cmd).is_file():
        return from_cmd
    candidates = [
        mysqld_path.parent / "my.ini",
        mysqld_path.parent.parent / "my.ini",
        mysqld_path.parent / "my.cnf",
        mysqld_path.parent.parent / "my.cnf",
    ]
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return None


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()


def _stable_id(prefix: str, key: str) -> str:
    digest = hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{prefix}:{digest}"


def _list_windows_services() -> tuple[list[MySqlService], set[str]]:
    services: list[MySqlService] = []
    service_bins: set[str] = set()
    access = win32con.GENERIC_READ
    scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ENUMERATE_SERVICE)

    try:
        statuses = win32service.EnumServicesStatus(
            scm,
            win32service.SERVICE_WIN32,
            win32service.SERVICE_STATE_ALL,
        )
        for name, display_name, _status in statuses:
            try:
                hs = win32service.OpenService(scm, name, access)
            except Exception:
                continue
            try:
                cfg = win32service.QueryServiceConfig(hs)
                binary_path = cfg[3]
                if not _looks_like_mysql(name, display_name, binary_path):
                    continue
                exe = _extract_exe_from_pathname(binary_path)
                exe_norm = _norm(exe)
                if exe_norm:
                    service_bins.add(exe_norm)
                defaults = _parse_defaults_file(binary_path)
                port = _read_port(Path(defaults)) if defaults else None
                if port is None:
                    port = _parse_port_arg(binary_path)
                status = win32service.QueryServiceStatus(hs)[1]
                services.append(
                    MySqlService(
                        name=f"svc:{name}",
                        display_name=display_name or name,
                        status=_status_name(status),
                        start_type=_start_type_name(cfg[1]),
                        kind=KIND_SERVICE,
                        mysqld_path=exe,
                        mysqladmin_path=_find_nearby_admin(Path(exe)) if exe else None,
                        defaults_file=defaults,
                        port=port,
                    )
                )
            finally:
                win32service.CloseServiceHandle(hs)
    finally:
        win32service.CloseServiceHandle(scm)

    return services, service_bins


def _discover_known_installs() -> list[tuple[str, Path, Path | None]]:
    """Return (label, mysqld_path, defaults_file)."""
    found: list[tuple[str, Path, Path | None]] = []

    for root in PORTABLE_ROOTS:
        if not root.exists():
            continue
        name = root.name.lower()

        # Laragon
        mysql_root = root / "bin" / "mysql"
        if mysql_root.is_dir():
            for version_dir in sorted(mysql_root.iterdir()):
                mysqld = version_dir / "bin" / "mysqld.exe"
                if not mysqld.is_file():
                    mysqld = version_dir / "bin" / "mariadbd.exe"
                ini = version_dir / "my.ini"
                if mysqld.is_file():
                    label = f"Laragon ({version_dir.name})"
                    found.append((label, mysqld, ini if ini.is_file() else None))

        # XAMPP / generic mysql\bin
        for rel in (Path("mysql") / "bin", Path("bin") / "mysql"):
            bin_dir = root / rel
            for exe_name in ("mysqld.exe", "mariadbd.exe"):
                mysqld = bin_dir / exe_name
                if mysqld.is_file():
                    ini = bin_dir / "my.ini"
                    if not ini.is_file():
                        ini = bin_dir.parent / "my.ini"
                    label = "XAMPP MySQL" if "xampp" in name else f"{root.name} MySQL"
                    found.append((label, mysqld, ini if ini.is_file() else None))

        # WAMP: bin\mysql\mysql*\bin\mysqld.exe
        wamp_mysql = root / "bin" / "mysql"
        if wamp_mysql.is_dir():
            for version_dir in sorted(wamp_mysql.iterdir()):
                mysqld = version_dir / "bin" / "mysqld.exe"
                ini = version_dir / "my.ini"
                if mysqld.is_file():
                    found.append(
                        (f"WAMP ({version_dir.name})", mysqld, ini if ini.is_file() else None)
                    )

    # Depth-limited scan for other installs
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        try:
            for mysqld in root.rglob("mysqld.exe"):
                # skip deep noise / copies
                parts = {p.lower() for p in mysqld.parts}
                if "data" in parts or "tmp" in parts:
                    continue
                ini = _find_nearby_ini(mysqld)
                label = f"MySQL ({mysqld.parent.parent.name})"
                found.append((label, mysqld, Path(ini) if ini else None))
            for mysqld in root.rglob("mariadbd.exe"):
                parts = {p.lower() for p in mysqld.parts}
                if "data" in parts or "tmp" in parts:
                    continue
                ini = _find_nearby_ini(mysqld)
                label = f"MariaDB ({mysqld.parent.parent.name})"
                found.append((label, mysqld, Path(ini) if ini else None))
        except OSError:
            continue

    return found


def _list_install_instances(service_bins: set[str], running_by_path: dict[str, list[dict]]) -> list[MySqlService]:
    instances: list[MySqlService] = []
    seen: set[str] = set()

    for label, mysqld, ini in _discover_known_installs():
        key = _norm(mysqld)
        if not key or key in seen:
            continue
        # Skip binaries already managed as Windows services
        if key in service_bins:
            continue
        seen.add(key)

        defaults = str(ini) if ini and ini.is_file() else _find_nearby_ini(mysqld)
        port = _read_port(Path(defaults)) if defaults else None
        procs = running_by_path.get(key, [])
        is_running = bool(procs) or _port_open(port)
        if procs and port is None:
            port = _parse_port_arg(procs[0].get("cmdline"))
            if port is None and defaults:
                port = _read_port(Path(defaults))

        drive = Path(str(mysqld)).drive.replace(":", "").upper() or "?"
        port_part = f" :{port}" if port else ""
        display = f"{label} ({drive}:){port_part}"
        instances.append(
            MySqlService(
                name=_stable_id("portable", key),
                display_name=display,
                status="Running" if is_running else "Stopped",
                start_type="Manual",
                kind=KIND_PORTABLE,
                mysqld_path=str(mysqld.resolve()) if mysqld.exists() else str(mysqld),
                mysqladmin_path=_find_nearby_admin(mysqld),
                defaults_file=defaults,
                port=port,
                pids=[p["pid"] for p in procs],
            )
        )
    return instances


def _list_orphan_processes(
    service_bins: set[str],
    known_portable: set[str],
    running_procs: list[dict],
) -> list[MySqlService]:
    """Any running mysqld not already listed as service or known install."""
    instances: list[MySqlService] = []
    seen: set[str] = set()

    for proc in running_procs:
        path = proc.get("path")
        key = _norm(path)
        if not key or key in seen or key in service_bins or key in known_portable:
            continue
        seen.add(key)

        mysqld = Path(path)
        cmdline = proc.get("cmdline")
        defaults = _find_nearby_ini(mysqld, cmdline)
        port = _parse_port_arg(cmdline)
        if port is None and defaults:
            port = _read_port(Path(defaults))

        port_part = f" :{port}" if port else ""
        display = f"MySQL مستقل ({mysqld.parent.parent.name}){port_part}"
        # Collect all pids for same binary
        pids = [p["pid"] for p in running_procs if _norm(p.get("path")) == key]
        instances.append(
            MySqlService(
                name=_stable_id("proc", key),
                display_name=display,
                status="Running",
                start_type="Manual",
                kind=KIND_PORTABLE,
                mysqld_path=str(mysqld),
                mysqladmin_path=_find_nearby_admin(mysqld),
                defaults_file=defaults,
                port=port,
                pids=pids,
            )
        )
    return instances


def list_mysql_services() -> list[MySqlService]:
    running_procs = _wmi_mysql_processes()
    running_by_path: dict[str, list[dict]] = {}
    for proc in running_procs:
        key = _norm(proc.get("path"))
        if not key:
            # Try image path from pid
            image = _process_image_path(proc["pid"])
            key = _norm(image)
            if key:
                proc["path"] = image
        if not key:
            continue
        running_by_path.setdefault(key, []).append(proc)

    services, service_bins = _list_windows_services()
    installs = _list_install_instances(service_bins, running_by_path)
    known_portable = {_norm(i.mysqld_path) for i in installs if i.mysqld_path}
    orphans = _list_orphan_processes(service_bins, known_portable, running_procs)

    all_items = services + installs + orphans
    all_items.sort(key=lambda s: s.display_name.lower())
    return all_items


def get_instance(name: str) -> MySqlService | None:
    for svc in list_mysql_services():
        if svc.name == name:
            return svc
    return None


def _svc_name(name: str) -> str:
    return name[4:] if name.startswith("svc:") else name


def _terminate_pids(pids: list[int]) -> None:
    for pid in pids:
        try:
            handle = win32api.OpenProcess(win32con.PROCESS_TERMINATE, False, pid)
            win32process.TerminateProcess(handle, 1)
            win32api.CloseHandle(handle)
        except Exception:
            pass


def _terminate_by_path(mysqld_path: str) -> None:
    target = _norm(mysqld_path)
    if not target:
        return
    for proc in _wmi_mysql_processes():
        if _norm(proc.get("path")) == target or _norm(_process_image_path(proc["pid"])) == target:
            _terminate_pids([proc["pid"]])


def start_service(name: str, timeout_seconds: int = 60) -> None:
    inst = get_instance(name)
    if inst is None:
        win32serviceutil.StartService(name)
        win32serviceutil.WaitForServiceStatus(
            name, win32service.SERVICE_RUNNING, waitSecs=timeout_seconds
        )
        return

    if inst.kind == KIND_SERVICE:
        real = _svc_name(inst.name)
        win32serviceutil.StartService(real)
        win32serviceutil.WaitForServiceStatus(
            real, win32service.SERVICE_RUNNING, waitSecs=timeout_seconds
        )
        return

    if not inst.mysqld_path:
        raise RuntimeError("مسار mysqld غير معروف لهذه النسخة.")
    if inst.is_running:
        return

    mysqld = Path(inst.mysqld_path)
    args = [str(mysqld)]
    if inst.defaults_file and Path(inst.defaults_file).is_file():
        args.append(f"--defaults-file={inst.defaults_file}")

    # Help portable installs (Laragon/XAMPP) find plugins even if my.ini is incomplete.
    basedir = mysqld.parent.parent
    plugin_dir = basedir / "lib" / "plugin"
    if basedir.is_dir():
        args.append(f"--basedir={basedir}")
    if plugin_dir.is_dir():
        args.append(f"--plugin-dir={plugin_dir}")

    creation = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    creation |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    subprocess.Popen(
        args,
        cwd=str(mysqld.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creation,
        close_fds=True,
    )

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        current = get_instance(name)
        if current and current.is_running:
            return
        time.sleep(0.5)
    raise TimeoutError(f"انتهت المهلة أثناء تشغيل {inst.display_name}")


def stop_service(name: str, timeout_seconds: int = 60) -> None:
    inst = get_instance(name)
    if inst is None:
        win32serviceutil.StopService(name)
        win32serviceutil.WaitForServiceStatus(
            name, win32service.SERVICE_STOPPED, waitSecs=timeout_seconds
        )
        return

    if inst.kind == KIND_SERVICE:
        real = _svc_name(inst.name)
        win32serviceutil.StopService(real)
        win32serviceutil.WaitForServiceStatus(
            real, win32service.SERVICE_STOPPED, waitSecs=timeout_seconds
        )
        return

    if inst.mysqladmin_path and Path(inst.mysqladmin_path).is_file():
        cmd = [inst.mysqladmin_path]
        if inst.defaults_file and Path(inst.defaults_file).is_file():
            cmd.append(f"--defaults-file={inst.defaults_file}")
        if inst.port:
            cmd.append(f"--port={inst.port}")
        cmd.extend(["-uroot", "shutdown"])
        subprocess.run(
            cmd,
            cwd=str(Path(inst.mysqladmin_path).parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=min(30, timeout_seconds),
            check=False,
        )

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        current = get_instance(name)
        if current and not current.is_running:
            return
        if time.time() > deadline - 8:
            if inst.pids:
                _terminate_pids(inst.pids)
            if inst.mysqld_path:
                _terminate_by_path(inst.mysqld_path)
        time.sleep(0.5)

    current = get_instance(name)
    if current and current.is_running:
        raise TimeoutError(f"انتهت المهلة أثناء إيقاف {inst.display_name}")


def _clear_failure_restart(service_name: str) -> None:
    """Disable Windows 'restart service on failure' so it won't come back alone."""
    subprocess.run(
        [
            "sc.exe",
            "failure",
            service_name,
            "reset=",
            "0",
            "actions=",
            "",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        ["sc.exe", "failureflag", service_name, "0"],
        capture_output=True,
        text=True,
        check=False,
    )


def set_start_type_manual(name: str) -> None:
    inst = get_instance(name)
    if inst and inst.is_portable:
        return
    real = _svc_name(inst.name) if inst else name
    # Do NOT use win32serviceutil.ChangeServiceConfig — it rewrites the binary
    # path to pythonservice.exe (intended only for Python Windows services).
    result = subprocess.run(
        ["sc.exe", "config", real, "start=", "demand"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or f"فشل ضبط {real} على Manual")
    _clear_failure_restart(real)


def disable_external_autostart_hooks() -> list[str]:
    """Remove known external watchdogs that force-start VatoceSalesUp."""
    removed: list[str] = []
    # Scheduled tasks
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/FO", "LIST", "/V"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        text = result.stdout or ""
        task_names: set[str] = set()
        current = None
        for line in text.splitlines():
            if line.startswith("TaskName:"):
                current = line.split(":", 1)[1].strip().lstrip("\\")
            elif current and (
                "ForceStart-VatoceSalesUp" in line
                or "VatoceSalesUp-Watchdog" in line
                or current.lower() == "vatocesalesup-watchdog"
            ):
                task_names.add(current.split("\\")[-1])
        # Always try known name
        task_names.add("VatoceSalesUp-Watchdog")
        for name in sorted(task_names):
            del_res = subprocess.run(
                ["schtasks", "/Delete", "/TN", name, "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
            if del_res.returncode == 0:
                removed.append(f"task:{name}")
    except Exception:
        pass

    # Force-start / auto-recovery scripts
    candidates = [
        Path(r"D:\WorkTemp\Current\MrSales\tools\ForceStart-VatoceSalesUp.ps1"),
        Path(r"D:\WorkTemp\Current\MrSales\tools\ForceStart-VatoceSalesUp.bat"),
        Path(r"D:\WorkTemp\Current\MrSales\tools\Install-VatoceSalesUp-AutoRecovery.ps1"),
        Path(r"D:\WorkTemp\Current\MrSales\tools\Install-VatoceSalesUp-AutoRecovery.bat"),
    ]
    for path in candidates:
        if path.is_file() and ".disabled-by-ControlMySQL" not in path.name:
            bak = path.with_name(path.name + ".disabled-by-ControlMySQL")
            try:
                if bak.exists():
                    bak.unlink()
                path.rename(bak)
                removed.append(f"file:{path.name}")
            except OSError:
                pass
    return removed


def set_all_mysql_manual() -> list[str]:
    changed: list[str] = []
    for svc in list_mysql_services():
        if svc.is_portable:
            continue
        set_start_type_manual(svc.name)
        changed.append(svc.display_name)
    hooks = disable_external_autostart_hooks()
    changed.extend(hooks)
    return changed


def discovery_report() -> str:
    """Human-readable audit of what was found."""
    items = list_mysql_services()
    lines = [f"وجد {len(items)} عنصر:"]
    for s in items:
        kind = "خدمة ويندوز" if s.kind == KIND_SERVICE else "برنامج مستقل"
        lines.append(f"- [{kind}] {s.display_name} → {s.status} ({s.start_type})")
        if s.mysqld_path:
            lines.append(f"    {s.mysqld_path}")
    return "\n".join(lines)
