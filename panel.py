"""Compact modern control panel shown on left-click of the tray icon."""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import font as tkfont
from dataclasses import dataclass
from typing import Callable

import services

C_BG = "#eef1f4"
C_SURFACE = "#ffffff"
C_SURFACE_ALT = "#f7f9fb"
C_BORDER = "#d8dee6"
C_TEXT = "#1c2430"
C_MUTED = "#6b7785"
C_TEAL = "#0f766e"
C_TEAL_SOFT = "#ccfbf1"
C_GREEN_DOT = "#22c55e"
C_GREEN_RING = "#bbf7d0"
C_OFF_DOT = "#94a3b8"
C_OFF_RING = "#e2e8f0"
C_BTN = "#0f766e"
C_BTN_TEXT = "#ffffff"
C_BTN_STOP = "#334155"
C_BTN_DISABLED = "#94a3b8"


def _clean_name(display_name: str) -> str:
    return re.sub(r"\s*:\d+\s*$", "", display_name).strip()


@dataclass
class _RowWidgets:
    name: str
    frame: tk.Frame
    sep: tk.Frame
    dot: tk.Label
    title: tk.Label
    kind: tk.Label
    port: tk.Label
    name_box: tk.Frame
    actions: tk.Frame
    start_btn: tk.Button
    stop_btn: tk.Button
    state_key: tuple


class ControlPanel:
    def __init__(
        self,
        root: tk.Tk,
        *,
        on_start: Callable[[str], None],
        on_stop: Callable[[str], None],
        on_set_manual: Callable[[str], None],
        on_stop_all: Callable[[], None],
        on_set_all_manual: Callable[[], None],
        on_toggle_startup: Callable[[], None],
        on_refresh: Callable[[], None],
        on_quit: Callable[[], None],
        is_startup_enabled: Callable[[], bool],
    ) -> None:
        self._root = root
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_set_manual = on_set_manual
        self._on_stop_all = on_stop_all
        self._on_set_all_manual = on_set_all_manual
        self._on_toggle_startup = on_toggle_startup
        self._on_refresh = on_refresh
        self._on_quit = on_quit
        self._is_startup_enabled = is_startup_enabled

        self._win: tk.Toplevel | None = None
        self._rows_frame: tk.Frame | None = None
        self._empty_label: tk.Label | None = None
        self._status_var = tk.StringVar(value="")
        self._startup_var = tk.BooleanVar(value=False)
        self._busy = False
        self._fonts: dict[str, tkfont.Font] = {}
        self._rows: dict[str, _RowWidgets] = {}

    @property
    def is_visible(self) -> bool:
        return (
            self._win is not None
            and self._win.winfo_exists()
            and bool(self._win.winfo_viewable())
        )

    def _ensure_fonts(self) -> None:
        if self._fonts:
            return
        family = "Segoe UI"
        available = set(tkfont.families())
        if "Segoe UI Variable" in available:
            family = "Segoe UI Variable"
        elif "Cascadia UI" in available:
            family = "Cascadia UI"
        self._fonts = {
            "title": tkfont.Font(family=family, size=13, weight="bold"),
            "name": tkfont.Font(family=family, size=10, weight="bold"),
            "meta": tkfont.Font(family=family, size=9),
            "credit": tkfont.Font(family=family, size=8),
            "port": tkfont.Font(family=family, size=9, weight="bold"),
            "btn": tkfont.Font(family=family, size=9, weight="bold"),
            "dot": tkfont.Font(family=family, size=18, weight="bold"),
        }

    def show(self) -> None:
        if self._win is not None and self._win.winfo_exists():
            self._win.deiconify()
            self._win.lift()
            self._win.focus_force()
            return
        self._build()

    def hide(self) -> None:
        if self._win is not None and self._win.winfo_exists():
            self._win.withdraw()

    def destroy(self) -> None:
        self._rows.clear()
        if self._win is not None and self._win.winfo_exists():
            self._win.destroy()
        self._win = None
        self._rows_frame = None
        self._empty_label = None

    def set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        if message or not busy:
            self._status_var.set(message)
        if self._win is not None and self._win.winfo_exists():
            self._win.configure(cursor="watch" if busy else "")
        # Soft-disable action buttons while busy without rebuilding rows.
        for row in self._rows.values():
            if busy:
                row.start_btn.configure(state="disabled", bg=C_BTN_DISABLED, cursor="arrow")
                row.stop_btn.configure(state="disabled", bg=C_BTN_DISABLED, cursor="arrow")

    def apply_items(self, mysql_list: list[services.MySqlService]) -> None:
        """Update the list in-place. Pass a prefetched list to avoid extra scans."""
        if self._win is None or not self._win.winfo_exists() or self._rows_frame is None:
            return

        if not mysql_list:
            self._clear_rows()
            if self._empty_label is None or not self._empty_label.winfo_exists():
                self._empty_label = tk.Label(
                    self._rows_frame,
                    text="لا توجد نسخ MySQL على الجهاز",
                    bg=C_SURFACE,
                    fg=C_MUTED,
                    font=self._fonts["meta"],
                )
                self._empty_label.pack(pady=24)
        else:
            if self._empty_label is not None and self._empty_label.winfo_exists():
                self._empty_label.destroy()
                self._empty_label = None

            incoming = {svc.name: svc for svc in mysql_list}
            current_order = list(self._rows.keys())
            new_order = [svc.name for svc in mysql_list]

            for key in list(self._rows.keys()):
                if key not in incoming:
                    self._destroy_row(key)

            for svc in mysql_list:
                if svc.name in self._rows:
                    self._update_row(self._rows[svc.name], svc)
                else:
                    self._add_row(svc)
                    self._rows[svc.name].frame.pack(fill="x")
                    self._rows[svc.name].sep.pack(fill="x")

            # Only re-order when membership/order actually changed
            if current_order != new_order:
                for name in new_order:
                    row = self._rows.get(name)
                    if not row:
                        continue
                    row.frame.pack_forget()
                    row.sep.pack_forget()
                for name in new_order:
                    row = self._rows[name]
                    row.frame.pack(fill="x")
                    row.sep.pack(fill="x")

        try:
            self._startup_var.set(self._is_startup_enabled())
        except Exception:
            pass

        running = sum(1 for s in mysql_list if s.is_running)
        if not self._busy:
            self._status_var.set(f"{running} / {len(mysql_list)} شغال")

    def refresh(self) -> None:
        self.apply_items(services.list_mysql_services())

    def _clear_rows(self) -> None:
        for key in list(self._rows.keys()):
            self._destroy_row(key)

    def _destroy_row(self, key: str) -> None:
        row = self._rows.pop(key, None)
        if row is None:
            return
        try:
            row.frame.destroy()
            row.sep.destroy()
        except tk.TclError:
            pass

    def _build(self) -> None:
        self._ensure_fonts()
        win = tk.Toplevel(self._root)
        self._win = win
        win.title("Control MySQL — فاتوس للبرمجيات")
        win.geometry("560x420")
        win.minsize(480, 320)
        win.configure(bg=C_BG)
        win.protocol("WM_DELETE_WINDOW", self.hide)

        try:
            win.attributes("-topmost", True)
            win.after(250, lambda: win.attributes("-topmost", False))
        except tk.TclError:
            pass

        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = 560, 420
        win.geometry(f"{w}x{h}+{max(24, sw - w - 20)}+{max(24, sh - h - 72)}")

        shell = tk.Frame(win, bg=C_BG, padx=14, pady=12)
        shell.pack(fill="both", expand=True)

        header = tk.Frame(shell, bg=C_BG)
        header.pack(fill="x", pady=(0, 10))
        tk.Label(
            header,
            text="MySQL Control",
            bg=C_BG,
            fg=C_TEXT,
            font=self._fonts["title"],
        ).pack(side="right")
        self._make_button(header, "تحديث", self._click_refresh, soft=True).pack(side="left")

        list_card = tk.Frame(
            shell, bg=C_SURFACE, highlightbackground=C_BORDER, highlightthickness=1
        )
        list_card.pack(fill="both", expand=True)

        canvas_wrap = tk.Frame(list_card, bg=C_SURFACE)
        canvas_wrap.pack(fill="both", expand=True, padx=1, pady=1)

        canvas = tk.Canvas(canvas_wrap, highlightthickness=0, bg=C_SURFACE, bd=0)
        scroll = tk.Scrollbar(canvas_wrap, orient="vertical", command=canvas.yview)
        rows = tk.Frame(canvas, bg=C_SURFACE)
        self._rows_frame = rows

        rows.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        window_id = canvas.create_window((0, 0), window=rows, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)

        def _sync_width(event: tk.Event) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        canvas.bind("<Configure>", _sync_width)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        footer = tk.Frame(shell, bg=C_BG)
        footer.pack(fill="x", pady=(10, 0))

        right = tk.Frame(footer, bg=C_BG)
        right.pack(side="right")
        self._make_button(right, "إيقاف الكل", self._click_stop_all, danger=True).pack(
            side="right", padx=(6, 0)
        )
        self._make_button(right, "يدوي فقط", self._click_set_all_manual, soft=True).pack(
            side="right"
        )

        left = tk.Frame(footer, bg=C_BG)
        left.pack(side="left")
        self._make_button(left, "إخفاء", self.hide, soft=True).pack(side="left", padx=(0, 6))
        self._make_button(left, "خروج", self._click_quit, soft=True).pack(side="left")

        opts = tk.Frame(shell, bg=C_BG)
        opts.pack(fill="x", pady=(8, 0))
        tk.Checkbutton(
            opts,
            text="تشغيل الأداة مع ويندوز",
            variable=self._startup_var,
            command=self._click_toggle_startup,
            bg=C_BG,
            fg=C_MUTED,
            activebackground=C_BG,
            activeforeground=C_TEXT,
            selectcolor=C_SURFACE,
            font=self._fonts["meta"],
            highlightthickness=0,
            bd=0,
        ).pack(side="right")
        tk.Label(
            opts,
            textvariable=self._status_var,
            bg=C_BG,
            fg=C_MUTED,
            font=self._fonts["meta"],
        ).pack(side="left")

        credit = tk.Frame(shell, bg=C_BG)
        credit.pack(fill="x", pady=(6, 0))
        credit_lbl = tk.Label(
            credit,
            text="© فاتوس للبرمجيات  ·  vatoce.com",
            bg=C_BG,
            fg=C_MUTED,
            font=self._fonts["credit"],
            cursor="hand2",
        )
        credit_lbl.pack(side="right")
        credit_lbl.bind("<Button-1>", lambda _e: self._open_website())

        # Initial populate once after build
        self.refresh()

    def _open_website(self) -> None:
        import webbrowser

        webbrowser.open("https://vatoce.com")

    def _make_button(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], None] | None,
        *,
        soft: bool = False,
        danger: bool = False,
        enabled: bool = True,
    ) -> tk.Button:
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            font=self._fonts["btn"],
            relief="flat",
            bd=0,
            padx=12,
            pady=5,
            highlightthickness=1 if soft else 0,
        )
        self._style_button(btn, soft=soft, danger=danger, enabled=enabled)
        return btn

    def _style_button(
        self,
        btn: tk.Button,
        *,
        soft: bool = False,
        danger: bool = False,
        enabled: bool = True,
    ) -> None:
        if not enabled:
            bg, fg, active = C_BTN_DISABLED, "#f8fafc", C_BTN_DISABLED
        elif danger:
            bg, fg, active = C_BTN_STOP, C_BTN_TEXT, "#1e293b"
        elif soft:
            bg, fg, active = C_SURFACE, C_TEXT, C_TEAL_SOFT
        else:
            bg, fg, active = C_BTN, C_BTN_TEXT, "#0d9488"

        btn.configure(
            bg=bg,
            fg=fg,
            activebackground=active,
            activeforeground=fg,
            cursor="hand2" if enabled else "arrow",
            highlightbackground=C_BORDER if soft else bg,
            state="normal" if enabled else "disabled",
        )

    def _state_key(self, svc: services.MySqlService) -> tuple:
        return (svc.is_running, svc.start_type, svc.port, svc.is_portable, svc.display_name)

    def _paint_status(self, row: _RowWidgets, running: bool) -> None:
        row_bg = C_SURFACE_ALT if running else C_SURFACE
        for w in (row.frame, row.name_box, row.actions, row.title, row.kind):
            try:
                w.configure(bg=row_bg)
            except tk.TclError:
                pass
        if running:
            row.dot.configure(
                text="●",
                fg=C_GREEN_DOT,
                bg=C_GREEN_RING,
                font=self._fonts["dot"],
            )
        else:
            row.dot.configure(
                text="●",
                fg=C_OFF_DOT,
                bg=C_OFF_RING,
                font=self._fonts["dot"],
            )

    def _paint_row_bg(self, row: _RowWidgets, running: bool) -> None:
        self._paint_status(row, running)

    def _update_row(self, row: _RowWidgets, svc: services.MySqlService) -> None:
        key = self._state_key(svc)
        if key == row.state_key and not self._busy:
            return
        row.state_key = key
        self._paint_row_bg(row, svc.is_running)
        row.title.configure(text=_clean_name(svc.display_name))
        row.kind.configure(text="مستقل" if svc.is_portable else "خدمة")
        if svc.port:
            row.port.configure(text=f":{svc.port}", bg=C_TEAL_SOFT, fg=C_TEAL)
        else:
            row.port.configure(text=":—", bg="#e2e8f0", fg=C_MUTED)

        if self._busy:
            self._style_button(row.start_btn, enabled=False)
            self._style_button(row.stop_btn, danger=True, enabled=False)
        else:
            self._style_button(row.start_btn, enabled=not svc.is_running)
            self._style_button(row.stop_btn, danger=True, enabled=svc.is_running)

    def _add_row(self, svc: services.MySqlService) -> None:
        assert self._rows_frame is not None
        row_bg = C_SURFACE_ALT if svc.is_running else C_SURFACE

        frame = tk.Frame(self._rows_frame, bg=row_bg, padx=10, pady=6)
        sep = tk.Frame(self._rows_frame, bg=C_BORDER, height=1)

        dot = tk.Label(
            frame,
            text="●",
            bg=C_GREEN_RING if svc.is_running else C_OFF_RING,
            fg=C_GREEN_DOT if svc.is_running else C_OFF_DOT,
            font=self._fonts["dot"],
            width=2,
            padx=4,
            pady=2,
        )
        dot.pack(side="left", padx=(0, 4))

        name_box = tk.Frame(frame, bg=row_bg)
        name_box.pack(side="left", fill="x", expand=True, padx=(2, 8))
        title = tk.Label(
            name_box,
            text=_clean_name(svc.display_name),
            bg=row_bg,
            fg=C_TEXT,
            font=self._fonts["name"],
            anchor="w",
        )
        title.pack(fill="x")
        kind = tk.Label(
            name_box,
            text="مستقل" if svc.is_portable else "خدمة",
            bg=row_bg,
            fg=C_MUTED,
            font=self._fonts["meta"],
            anchor="w",
        )
        kind.pack(fill="x")

        port = tk.Label(
            frame,
            text=f":{svc.port}" if svc.port else ":—",
            bg=C_TEAL_SOFT if svc.port else "#e2e8f0",
            fg=C_TEAL if svc.port else C_MUTED,
            font=self._fonts["port"],
            padx=8,
            pady=3,
        )
        port.pack(side="left", padx=(0, 8))

        actions = tk.Frame(frame, bg=row_bg)
        actions.pack(side="left")
        name = svc.name
        start_btn = self._make_button(
            actions,
            "تشغيل",
            lambda n=name: self._click_start(n),
            enabled=not svc.is_running,
        )
        start_btn.pack(side="left", padx=(0, 4))
        stop_btn = self._make_button(
            actions,
            "إيقاف",
            lambda n=name: self._click_stop(n),
            danger=True,
            enabled=svc.is_running,
        )
        stop_btn.pack(side="left")

        self._rows[svc.name] = _RowWidgets(
            name=svc.name,
            frame=frame,
            sep=sep,
            dot=dot,
            title=title,
            kind=kind,
            port=port,
            name_box=name_box,
            actions=actions,
            start_btn=start_btn,
            stop_btn=stop_btn,
            state_key=self._state_key(svc),
        )

    def _guard(self) -> bool:
        if self._busy:
            self._status_var.set("جاري التنفيذ...")
            return False
        return True

    def _click_start(self, name: str) -> None:
        if self._guard():
            self._on_start(name)

    def _click_stop(self, name: str) -> None:
        if self._guard():
            self._on_stop(name)

    def _click_manual(self, name: str) -> None:
        if self._guard():
            self._on_set_manual(name)

    def _click_stop_all(self) -> None:
        if self._guard():
            self._on_stop_all()

    def _click_set_all_manual(self) -> None:
        if self._guard():
            self._on_set_all_manual()

    def _click_toggle_startup(self) -> None:
        self._on_toggle_startup()

    def _click_refresh(self) -> None:
        self._on_refresh()

    def _click_quit(self) -> None:
        self._on_quit()
