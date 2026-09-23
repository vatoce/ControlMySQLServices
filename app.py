"""
Control MySQL Services — Windows system-tray tool.

- Left-click tray icon → control panel
- Right-click → quick menu
- Starts with Windows (optional)
- Never starts MySQL by itself — only on user action
"""

from __future__ import annotations

import ctypes
import threading
import tkinter as tk
from typing import Callable

import pystray
from pystray import MenuItem as Item

import icons
import services
import startup
from panel import ControlPanel

MB_OK = 0x0
MB_YESNO = 0x4
MB_ICONERROR = 0x10
MB_ICONWARNING = 0x30
MB_ICONINFORMATION = 0x40
MB_ICONQUESTION = 0x20
IDYES = 6


def _msg(title: str, text: str, flags: int = MB_OK | MB_ICONINFORMATION) -> int:
    return int(ctypes.windll.user32.MessageBoxW(None, text, title, flags))


class MySqlTrayApp:
    AUTO_REFRESH_MS = 4000

    def __init__(self) -> None:
        self._busy = False
        self._icon: pystray.Icon | None = None
        self._auto_refresh_job: str | None = None
        self._last_snapshot: tuple | None = None
        self._refresh_lock = threading.Lock()
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.title("Control MySQL Services")
        self._panel = ControlPanel(
            self._root,
            on_start=self._on_start,
            on_stop=self._on_stop,
            on_set_manual=self._on_set_manual,
            on_stop_all=lambda: self._on_stop_all(),
            on_set_all_manual=lambda: self._on_set_all_manual(),
            on_toggle_startup=lambda: self._on_toggle_startup(),
            on_refresh=lambda: self._refresh_all(force=True, rebuild_menu=True),
            on_quit=lambda: self._on_quit(),
            is_startup_enabled=startup.is_startup_enabled,
        )

    def run(self) -> None:
        if not startup.is_admin():
            _msg(
                "صلاحيات المسؤول",
                "تشغيل وإيقاف خدمات ويندوز يحتاج صلاحيات مسؤول.\n"
                "سيتم طلب رفع الصلاحيات الآن.",
                MB_OK | MB_ICONWARNING,
            )
            startup.relaunch_as_admin()
            return

        self._icon = pystray.Icon(
            "ControlMySQLServices",
            icons.icon_idle(),
            "Control MySQL Services — كليك يسار للواجهة",
            menu=self._build_menu(),
        )
        self._refresh_icon()

        threading.Thread(target=self._icon.run, daemon=True).start()
        self._schedule_auto_refresh()
        self._root.mainloop()

    def _ui(self, fn: Callable[[], None]) -> None:
        self._root.after(0, fn)

    def _notify(self, title: str, message: str) -> None:
        if self._icon is not None:
            try:
                self._icon.notify(message, title)
            except Exception:
                pass

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy

        def apply() -> None:
            self._panel.set_busy(busy, message)

        self._ui(apply)

    def _run_bg(self, work: Callable[[], None], busy_message: str = "جاري التنفيذ...") -> None:
        if self._busy:
            self._notify("مشغول", "عملية أخرى قيد التنفيذ، انتظر قليلاً.")
            return

        def worker() -> None:
            self._set_busy(True, busy_message)
            try:
                work()
            finally:
                self._set_busy(False, "")
                self._refresh_all(force=True, rebuild_menu=True)

        threading.Thread(target=worker, daemon=True).start()

    def _status_label(self, svc: services.MySqlService) -> str:
        mark = "●" if svc.is_running else "○"
        if svc.is_portable:
            mode = "مستقل"
        else:
            mode = "يدوي" if svc.is_manual else svc.start_type
        return f"{mark} {svc.display_name}  [{svc.status} · {mode}]"

    def _bind(self, handler: Callable[[str], None], name: str) -> Callable:
        def action(_icon=None, _item=None) -> None:
            handler(name)

        return action

    def _service_submenu(self, svc: services.MySqlService) -> pystray.Menu:
        name = svc.name
        entries = [
            Item("تشغيل", self._bind(self._on_start, name), enabled=not svc.is_running),
            Item("إيقاف", self._bind(self._on_stop, name), enabled=svc.is_running),
        ]
        if not svc.is_portable:
            entries.append(
                Item(
                    "تعيين للتشغيل اليدوي فقط",
                    self._bind(self._on_set_manual, name),
                    enabled=not svc.is_manual,
                )
            )
        return pystray.Menu(*entries)

    def _build_menu(self) -> pystray.Menu:
        items: list[Item] = [
            Item("فتح واجهة التحكم", self._on_open_panel, default=True),
            Item("تحديث القائمة", self._on_refresh),
            pystray.Menu.SEPARATOR,
        ]

        mysql_list = getattr(self, "_menu_items_cache", None) or services.list_mysql_services()
        if not mysql_list:
            items.append(Item("لا توجد خدمات MySQL", None, enabled=False))
        else:
            for svc in mysql_list:
                items.append(Item(self._status_label(svc), self._service_submenu(svc)))

        items.extend(
            [
                pystray.Menu.SEPARATOR,
                Item("إيقاف كل خدمات MySQL", self._on_stop_all),
                Item("منع التشغيل التلقائي لخدمات ويندوز", self._on_set_all_manual),
                pystray.Menu.SEPARATOR,
                Item(
                    "التشغيل مع ويندوز",
                    self._on_toggle_startup,
                    checked=lambda _icon: startup.is_startup_enabled(),
                ),
                Item("فاتوس للبرمجيات — vatoce.com", self._on_about),
                Item("خروج", self._on_quit),
            ]
        )
        return pystray.Menu(*items)

    def _refresh_menu(self, items: list[services.MySqlService] | None = None) -> None:
        if self._icon is None:
            return
        # Keep a short cache so menu builders can reuse the same scan.
        self._menu_items_cache = items
        self._icon.menu = self._build_menu()
        self._refresh_icon(items)
        try:
            self._icon.update_menu()
        except Exception:
            pass

    def _refresh_icon(self, items: list[services.MySqlService] | None = None) -> None:
        if self._icon is None:
            return
        mysql_list = items if items is not None else services.list_mysql_services()
        if not mysql_list:
            self._icon.icon = icons.icon_idle()
            self._icon.title = "Control MySQL Services — لا خدمات"
            return

        running = sum(1 for s in mysql_list if s.is_running)
        total = len(mysql_list)
        if running == 0:
            self._icon.icon = icons.icon_stopped()
        elif running == total:
            self._icon.icon = icons.icon_running()
        else:
            self._icon.icon = icons.icon_mixed()
        self._icon.title = f"Control MySQL Services — {running}/{total} شغال · كليك يسار"

    def _snapshot_of(self, items: list[services.MySqlService]) -> tuple:
        return tuple(
            (s.name, s.status, s.start_type, s.port, tuple(s.pids))
            for s in items
        )

    def _apply_refresh(
        self,
        items: list[services.MySqlService],
        *,
        rebuild_menu: bool,
    ) -> None:
        snap = self._snapshot_of(items)
        names_changed = (
            self._last_snapshot is None
            or tuple(x[0] for x in snap) != tuple(x[0] for x in self._last_snapshot)
        )
        self._last_snapshot = snap

        if rebuild_menu or names_changed:
            self._refresh_menu(items)
        else:
            self._refresh_icon(items)

        if self._panel.is_visible or rebuild_menu:
            self._panel.apply_items(items)

    def _refresh_all(self, force: bool = True, rebuild_menu: bool = False) -> None:
        if self._busy and not force:
            return
        if not self._refresh_lock.acquire(blocking=False):
            return

        def worker() -> None:
            try:
                items = services.list_mysql_services()
                snap = self._snapshot_of(items)
                if not force and snap == self._last_snapshot:
                    return

                def apply() -> None:
                    if self._busy and not force:
                        return
                    self._apply_refresh(items, rebuild_menu=rebuild_menu or force)

                self._ui(apply)
            except Exception:
                pass
            finally:
                self._refresh_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    def _schedule_auto_refresh(self) -> None:
        def tick() -> None:
            self._auto_refresh_job = None
            try:
                if not self._busy:
                    # Light refresh: panel/icon only, no tray menu rebuild.
                    self._refresh_all(force=False, rebuild_menu=False)
            finally:
                try:
                    self._auto_refresh_job = self._root.after(
                        self.AUTO_REFRESH_MS, tick
                    )
                except tk.TclError:
                    self._auto_refresh_job = None

        self._auto_refresh_job = self._root.after(self.AUTO_REFRESH_MS, tick)

    def _on_open_panel(self, _icon=None, _item=None) -> None:
        def open_and_load() -> None:
            self._panel.show()
            self._refresh_all(force=True, rebuild_menu=False)

        self._ui(open_and_load)

    def _on_refresh(self, _icon=None, _item=None) -> None:
        self._refresh_all(force=True, rebuild_menu=True)
        self._notify("تحديث", "تم تحديث حالة الخدمات.")

    def _on_start(self, name: str) -> None:
        def work() -> None:
            try:
                services.start_service(name)
                self._notify("تشغيل", "تم التشغيل بنجاح")
            except Exception as exc:
                _msg("خطأ", f"تعذر التشغيل:\n{name}\n{exc}", MB_OK | MB_ICONERROR)

        self._run_bg(work, "جاري التشغيل...")

    def _on_stop(self, name: str) -> None:
        def work() -> None:
            try:
                services.stop_service(name)
                self._notify("إيقاف", "تم الإيقاف بنجاح")
            except Exception as exc:
                _msg("خطأ", f"تعذر الإيقاف:\n{name}\n{exc}", MB_OK | MB_ICONERROR)

        self._run_bg(work, "جاري الإيقاف...")

    def _on_set_manual(self, name: str) -> None:
        def work() -> None:
            try:
                services.set_start_type_manual(name)
                self._notify("يدوي", "لن يعمل تلقائياً مع ويندوز")
            except Exception as exc:
                _msg("خطأ", f"تعذر التعديل:\n{name}\n{exc}", MB_OK | MB_ICONERROR)

        self._run_bg(work, "جاري التعديل...")

    def _on_stop_all(self, _icon=None, _item=None) -> None:
        def work() -> None:
            errors: list[str] = []
            for svc in services.list_mysql_services():
                if not svc.is_running:
                    continue
                try:
                    services.stop_service(svc.name)
                except Exception as exc:
                    errors.append(f"{svc.display_name}: {exc}")
            if errors:
                _msg("إيقاف جزئي", "\n".join(errors), MB_OK | MB_ICONERROR)
            else:
                self._notify("إيقاف", "تم إيقاف كل نسخ MySQL.")

        self._run_bg(work, "جاري إيقاف الكل...")

    def _on_set_all_manual(self, _icon=None, _item=None) -> None:
        answer = _msg(
            "منع التشغيل التلقائي",
            "سيتم ضبط خدمات MySQL الخاصة بويندوز على Manual.\n"
            "(نسخ Laragon/XAMPP أصلًا لا تعمل كخدمة ويندوز)\n\n"
            "متابعة؟",
            MB_YESNO | MB_ICONQUESTION,
        )
        if answer != IDYES:
            return

        def work() -> None:
            try:
                changed = services.set_all_mysql_manual()
                if changed:
                    self._notify("تم", "تم الضبط على Manual:\n" + "\n".join(changed))
                else:
                    self._notify("تم", "كل خدمات ويندوز مضبوطة يدوياً بالفعل.")
            except Exception as exc:
                _msg("خطأ", str(exc), MB_OK | MB_ICONERROR)

        self._run_bg(work, "جاري التعديل...")

    def _on_toggle_startup(self, _icon=None, _item=None) -> None:
        try:
            if startup.is_startup_enabled():
                startup.disable_startup()
                self._notify("Startup", "لن تفتح الأداة مع ويندوز.")
            else:
                startup.enable_startup()
                self._notify("Startup", "ستظهر الأداة تلقائياً مع إقلاع الجهاز.")
        except Exception as exc:
            _msg("خطأ", str(exc), MB_OK | MB_ICONERROR)
        self._refresh_all(force=True, rebuild_menu=True)

    def _on_about(self, _icon=None, _item=None) -> None:
        import webbrowser

        _msg(
            "حول الأداة",
            "Control MySQL Services\n\n"
            "برمجة: فاتوس للبرمجيات\n"
            "vatoce.com",
            MB_OK | MB_ICONINFORMATION,
        )
        try:
            webbrowser.open("https://vatoce.com")
        except Exception:
            pass

    def _on_quit(self, _icon=None, _item=None) -> None:
        def shutdown() -> None:
            if self._auto_refresh_job is not None:
                try:
                    self._root.after_cancel(self._auto_refresh_job)
                except Exception:
                    pass
                self._auto_refresh_job = None
            self._panel.destroy()
            if self._icon is not None:
                self._icon.stop()
            self._root.quit()
            self._root.destroy()

        self._ui(shutdown)


def main() -> None:
    MySqlTrayApp().run()


if __name__ == "__main__":
    main()
