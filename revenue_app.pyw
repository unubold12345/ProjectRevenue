from __future__ import annotations

import json
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import urlparse

from neon_billing import NeonApiError, fetch_neon_billing, fmt_usd
from revenue_client import (
    APP_DIR,
    CONFIG_PATH,
    DEFAULT_API_URL,
    DEFAULT_NEON_RATE,
    DEFAULT_VERCEL_RATE,
    RevenueApiError,
    active_project,
    clean_neon,
    clean_vercel,
    fetch_summary,
    fmt_money,
    fmt_month,
    fmt_short,
    fmt_time,
    load_config,
    month_name,
    new_project_id,
    nice_ceiling,
    revenue_endpoint,
    save_config,
)
from vercel_billing import VercelApiError, fetch_vercel_billing, fmt_usd as fmt_usd_vercel

BG = "#090e16"
PANEL = "#101826"
PANEL_ALT = "#0c1320"
BORDER = "#1e2a3b"
TEXT = "#e8eef8"
MUTED = "#8b9cb3"
DIM = "#5f7189"
ACCENT = "#7c8cff"
ACCENT_ACTIVE = "#6b7bf0"
GREEN = "#3ddc97"
RED = "#ff6b81"
AMBER = "#ffc857"
CYAN = "#5fd0e6"
VERCEL = "#c4ccda"
TRACK = "#1a2535"
NEON_REFRESH_SECONDS = 900
VERCEL_REFRESH_SECONDS = 900

CATEGORIES = {
    "neon": ("Neon DB", "#3ddc97"),
    "vercel": ("Vercel", "#c4ccda"),
    "custom": ("Бусад", "#ffc857"),
}
CATEGORY_COLORS = (GREEN, "#c4ccda", AMBER, ACCENT, "#5fd0e6", "#f78fb3")


def category_meta(key: str) -> tuple[str, str]:
    known = CATEGORIES.get(key)
    if known:
        return known
    label = str(key).replace("_", " ").replace("-", " ").strip().title() or "Бусад"
    color = CATEGORY_COLORS[sum(ord(char) for char in str(key)) % len(CATEGORY_COLORS)]
    return label, color



def rounded_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, radius: float, **kwargs):
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=32, **kwargs)


def flat_button(parent: tk.Misc, text: str, command, primary: bool = False) -> tk.Button:
    background = ACCENT if primary else PANEL_ALT
    foreground = "#ffffff" if primary else TEXT
    active = ACCENT_ACTIVE if primary else "#162235"
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=background,
        fg=foreground,
        activebackground=active,
        activeforeground=foreground,
        relief="flat",
        bd=0,
        padx=16,
        pady=8,
        cursor="hand2",
        font=("Segoe UI", 9, "bold"),
        highlightthickness=1,
        highlightbackground=ACCENT if primary else BORDER,
        highlightcolor=ACCENT if primary else BORDER,
    )


def make_card(parent: tk.Misc, accent: str) -> tuple[tk.Frame, tk.Frame]:
    outer = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
    tk.Frame(outer, bg=accent, height=3).pack(fill="x", side="top")
    inner = tk.Frame(outer, bg=PANEL)
    inner.pack(fill="both", expand=True, padx=18, pady=(11, 14))
    return outer, inner


def center_toplevel(window: tk.Misc, width: int, height: int) -> None:
    window.update_idletasks()
    screen_w = window.winfo_screenwidth()
    screen_h = window.winfo_screenheight()
    parent = window.master
    x = y = None
    try:
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        if 0 <= px < screen_w and 0 <= py < screen_h:
            x = px + (pw - width) // 2
            y = py + (ph - height) // 2
    except (AttributeError, tk.TclError):
        pass
    if x is None or y is None:
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2 - 20
    x = max(8, min(x, screen_w - width - 8))
    y = max(8, min(y, screen_h - height - 48))
    window.geometry(f"{width}x{height}+{x}+{y}")


def enable_dark_titlebar(window: tk.Misc) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        for attribute, value in ((20, 1), (19, 1)):
            data = ctypes.c_int(value)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))
        for attribute, color in ((35, 0x00160E09), (36, 0x00F8EEE8), (34, 0x003B2A1E)):
            data = ctypes.c_int(color)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))
    except Exception:
        pass


class RevenueApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config = load_config()
        self.projects: list[dict[str, str]] = self.config["projects"]
        self.active_id: str = self.config["activeProjectId"]
        self.project_var = tk.StringVar(value=self.active_id)
        self.summary_cache: dict[str, dict] = {}
        self.summary: dict | None = self.summary_cache.get(self.active_id)
        self.loading = False
        self.closed = False
        self.auto_job: str | None = None
        self.settings_window: tk.Toplevel | None = None
        self.settings_project_id: str | None = None
        self.neon: dict = self.config.get("neon") or {}
        self.neon_billing: dict | None = None
        self.neon_error = ""
        self.neon_loading = False
        self.neon_last_fetch = 0.0
        self.neon_window: tk.Toplevel | None = None
        self.neon_settings_window: tk.Toplevel | None = None
        self.vercel: dict = self.config.get("vercel") or {}
        self.vercel_billing: dict | None = None
        self.vercel_error = ""
        self.vercel_loading = False
        self.vercel_last_fetch = 0.0
        self.vercel_window: tk.Toplevel | None = None
        self.vercel_settings_window: tk.Toplevel | None = None
        self.result_queue: queue.Queue[tuple[str, str, object]] = queue.Queue()
        self.chart_geometry: tuple[float, float, int, float, float] | None = None
        self.cost_bars: dict[str, tk.Frame] = {}
        self.cost_values: dict[str, tk.Label] = {}

        root.title("Project Revenue")
        root.configure(bg=BG)
        root.minsize(1040, 700)
        width, height = 1200, 800
        x = max((root.winfo_screenwidth() - width) // 2, 0)
        y = max((root.winfo_screenheight() - height) // 2 - 20, 0)
        root.geometry(f"{width}x{height}+{x}+{y}")
        self.icon: tk.PhotoImage | None = None
        try:
            icon_path = APP_DIR / "icon.png"
            if icon_path.exists():
                self.icon = tk.PhotoImage(file=str(icon_path))
                root.iconphoto(True, self.icon)
        except tk.TclError:
            self.icon = None

        self.build_ui()
        self.refresh_project_menu()
        self.update_project_chrome()
        root.after(80, lambda: enable_dark_titlebar(root))
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<F5>", lambda _event: self.refresh(True))
        root.bind("<Control-comma>", lambda _event: self.open_settings())
        root.after(120, self.poll_results)
        root.after(300, self.startup)
        self.schedule_auto()

    def build_ui(self) -> None:
        outer = tk.Frame(self.root, bg=BG, padx=24, pady=20)
        outer.pack(fill="both", expand=True)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(3, weight=1)

        self.build_header(outer)
        self.build_error_banner(outer)
        self.build_kpis(outer)
        self.build_main(outer)
        self.build_footer(outer)

    def build_header(self, parent: tk.Frame) -> None:
        header = tk.Frame(parent, bg=BG)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        brand = tk.Frame(header, bg=BG)
        brand.grid(row=0, column=0, sticky="w")
        mark = tk.Canvas(brand, width=42, height=42, bg=BG, highlightthickness=0)
        mark.pack(side="left", padx=(0, 12))
        rounded_rect(mark, 2, 2, 40, 40, 12, fill=ACCENT, outline="")
        mark.create_text(21, 21, text="R", fill="#ffffff", font=("Segoe UI", 19, "bold"))

        titles = tk.Frame(brand, bg=BG)
        titles.pack(side="left")
        tk.Label(
            titles,
            text="P R O J E C T   R E V E N U E",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            titles,
            text="Орлогын самбар",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 20, "bold"),
            anchor="w",
        ).pack(anchor="w")

        actions = tk.Frame(header, bg=BG)
        actions.grid(row=0, column=2, sticky="e")

        self.project_button = tk.Menubutton(
            actions,
            text="",
            bg=PANEL_ALT,
            fg=TEXT,
            activebackground="#162235",
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=12,
            pady=8,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
        )
        self.project_button.pack(side="left", padx=(0, 10))
        self.project_menu = tk.Menu(
            self.project_button,
            tearoff=False,
            bg=PANEL_ALT,
            fg=TEXT,
            activebackground=ACCENT,
            activeforeground="#ffffff",
            bd=0,
            font=("Segoe UI", 9),
        )
        self.project_button.configure(menu=self.project_menu)

        self.status_pill = tk.Frame(actions, bg=PANEL_ALT, highlightbackground=BORDER, highlightthickness=1)
        self.status_pill.pack(side="left", padx=(0, 10))
        self.status_dot = tk.Canvas(self.status_pill, width=10, height=10, bg=PANEL_ALT, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(11, 6), pady=9)
        self.status_dot_id = self.status_dot.create_oval(1, 1, 9, 9, fill=AMBER, outline="")
        self.status_label = tk.Label(
            self.status_pill,
            text="Бэлэн",
            bg=PANEL_ALT,
            fg=MUTED,
            font=("Segoe UI", 9),
        )
        self.status_label.pack(side="left", padx=(0, 11))

        self.refresh_button = flat_button(actions, "Сэргээх", lambda: self.refresh(True))
        self.refresh_button.pack(side="left", padx=(0, 8))
        flat_button(actions, "Neon", self.open_neon_dialog).pack(side="left", padx=(0, 8))
        flat_button(actions, "Vercel", self.open_vercel_dialog).pack(side="left", padx=(0, 8))
        flat_button(actions, "Тохиргоо", self.open_settings).pack(side="left")

    def current_project(self) -> dict[str, str] | None:
        return active_project({"projects": self.projects, "activeProjectId": self.active_id})

    def persist_config(self) -> bool:
        try:
            save_config(
                {
                    "projects": self.projects,
                    "activeProjectId": self.active_id,
                    "neon": self.neon,
                    "vercel": self.vercel,
                }
            )
        except OSError:
            return False
        return True

    def refresh_project_menu(self) -> None:
        self.project_menu.delete(0, "end")
        if not self.projects:
            self.project_menu.add_command(label="Төсөл нэмэх…", command=self.open_settings)
        for project in self.projects:
            self.project_menu.add_radiobutton(
                label=project["name"],
                value=project["id"],
                variable=self.project_var,
                command=lambda project_id=project["id"]: self.switch_project(project_id),
            )
        self.project_menu.add_separator()
        self.project_menu.add_command(label="Төслүүдийн тохиргоо…", command=self.open_settings)
        self.project_var.set(self.active_id)

    def update_project_chrome(self) -> None:
        project = self.current_project()
        if project is None:
            self.root.title("Project Revenue")
            self.project_button.configure(text="Төсөл нэмэх  ▾")
            self.endpoint_label.configure(text="API: —")
            return
        self.root.title("Project Revenue")
        self.project_button.configure(text=f"Төсөл: {project['name']}  ▾")
        self.endpoint_label.configure(text=f"API: {revenue_endpoint(project['apiUrl'])}")

    def switch_project(self, project_id: str) -> None:
        project = next((item for item in self.projects if item["id"] == project_id), None)
        if project is None or project_id == self.active_id:
            return
        self.active_id = project_id
        self.project_var.set(project_id)
        self.summary = self.summary_cache.get(project_id)
        self.loading = False
        self.hide_error()
        self.update_project_chrome()
        if self.summary is not None:
            self.render_summary()
            self.updated_label.configure(text="Хадгалагдсан өгөгдөл")
        else:
            self.render_empty()
            self.updated_label.configure(text="Шинэчлэгдсэн: —")
        if not self.persist_config():
            self.show_error("Тохиргоог хадгалж чадсангүй.")
        self.refresh()

    def build_error_banner(self, parent: tk.Frame) -> None:
        self.error_banner = tk.Frame(
            parent,
            bg="#2a1220",
            highlightbackground="#5a2339",
            highlightthickness=1,
        )
        self.error_banner.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self.error_banner.grid_remove()
        self.error_label = tk.Label(
            self.error_banner,
            text="",
            bg="#2a1220",
            fg="#ffb3c1",
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
            wraplength=1050,
        )
        self.error_label.pack(fill="x", padx=14, pady=9)

    def build_kpis(self, parent: tk.Frame) -> None:
        row = tk.Frame(parent, bg=BG)
        row.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        for column in range(6):
            row.grid_columnconfigure(column, weight=1, uniform="kpi")

        self.kpi_value: dict[str, tk.Label] = {}
        self.kpi_sub: dict[str, tk.Label] = {}

        specs = [
            ("revenue", "НИЙТ ОРЛОГО", ACCENT, "Баталгаажсан төлбөр"),
            ("month", "ЭНЭ САРЫН ОРЛОГО", GREEN, "Энэ сар"),
            ("profit", "ЦЭВЭР АШИГ", GREEN, "Орлогоос зардал хассан"),
            ("cost", "НИЙТ ЗАРДАЛ", RED, "Зардлын нийлбэр"),
            ("neon", "NEON ТӨЛБӨР", CYAN, "API тооцоо"),
            ("vercel", "VERCEL ТӨЛБӨР", VERCEL, "Credit + invoice"),
        ]
        for index, (key, title, accent, subtitle) in enumerate(specs):
            card, inner = make_card(row, accent)
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 6, 0))
            title_label = tk.Label(inner, text=title, bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w")
            title_label.pack(anchor="w")
            value = tk.Label(inner, text="—", bg=PANEL, fg=TEXT, font=("Segoe UI", 21, "bold"), anchor="w")
            value.pack(anchor="w", pady=(7, 4))
            sub = tk.Label(inner, text=subtitle, bg=PANEL, fg=DIM, font=("Segoe UI", 8), anchor="w")
            sub.pack(anchor="w")
            self.kpi_value[key] = value
            self.kpi_sub[key] = sub
            if key in ("neon", "vercel"):
                action = self.open_neon_dialog if key == "neon" else self.open_vercel_dialog
                for widget in (card, inner, title_label, value, sub):
                    widget.configure(cursor="hand2")
                    widget.bind("<Button-1>", lambda _event, handler=action: handler())

    def build_main(self, parent: tk.Frame) -> None:
        main = tk.Frame(parent, bg=BG)
        main.grid(row=3, column=0, sticky="nsew", pady=(16, 0))
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=3)
        main.grid_columnconfigure(1, weight=2)

        chart_card = tk.Frame(main, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        chart_card.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        chart_inner = tk.Frame(chart_card, bg=PANEL)
        chart_inner.pack(fill="both", expand=True, padx=18, pady=16)
        chart_inner.grid_columnconfigure(0, weight=1)
        chart_inner.grid_rowconfigure(2, weight=1)

        chart_head = tk.Frame(chart_inner, bg=PANEL)
        chart_head.grid(row=0, column=0, sticky="ew")
        chart_head.grid_columnconfigure(0, weight=1)
        tk.Label(
            chart_head,
            text="Орлого ба зардал",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 13, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            chart_head,
            text="Сүүлийн 12 сар",
            bg=PANEL,
            fg=DIM,
            font=("Segoe UI", 8),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        legend = tk.Frame(chart_head, bg=PANEL)
        legend.grid(row=0, column=1, rowspan=2, sticky="e")
        self.legend_item(legend, "Орлого", ACCENT).pack(side="left", padx=(0, 14))
        self.legend_item(legend, "Зардал", RED).pack(side="left")

        self.chart = tk.Canvas(chart_inner, bg=PANEL, highlightthickness=0, height=300)
        self.chart.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        self.chart.bind("<Configure>", lambda _event: self.redraw_chart())
        self.chart.bind("<Motion>", self.chart_motion)
        self.chart.bind("<Leave>", lambda _event: self.reset_chart_hint())

        self.chart_hint = tk.Label(
            chart_inner,
            text="",
            bg=PANEL,
            fg=DIM,
            font=("Segoe UI", 8),
            anchor="w",
        )
        self.chart_hint.grid(row=3, column=0, sticky="ew", pady=(6, 0))

        self.build_cost_panel(main)

    def build_cost_panel(self, parent: tk.Frame) -> None:
        card = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        card.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        inner = tk.Frame(card, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=18, pady=16)

        tk.Label(
            inner,
            text="Зардлын задаргаа",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 13, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            inner,
            text="Бүртгэгдсэн зардлын нийлбэр",
            bg=PANEL,
            fg=DIM,
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(anchor="w", pady=(2, 14))

        self.cost_rows_frame = tk.Frame(inner, bg=PANEL)
        self.cost_rows_frame.pack(fill="x")

        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=(4, 16))
        tk.Label(
            inner,
            text="ЭНЭ САРЫН ЦЭВЭР АШИГ",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).pack(anchor="w")
        self.month_profit = tk.Label(
            inner,
            text="—",
            bg=PANEL,
            fg=GREEN,
            font=("Segoe UI", 23, "bold"),
            anchor="w",
        )
        self.month_profit.pack(anchor="w", pady=(6, 3))
        self.month_margin = tk.Label(
            inner,
            text="",
            bg=PANEL,
            fg=DIM,
            font=("Segoe UI", 8),
            anchor="w",
        )
        self.month_margin.pack(anchor="w")

        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=(16, 12))
        insights = tk.Frame(inner, bg=PANEL)
        insights.pack(fill="x")
        insights.grid_columnconfigure(0, weight=1)
        insights.grid_columnconfigure(1, weight=1)
        self.insight_value: dict[str, tk.Label] = {}
        for column, (key, title) in enumerate((("ratio", "ЗАРДЛЫН ХУВЬ"), ("average", "12 САРЫН ДУНДАЖ"))):
            cell = tk.Frame(insights, bg=PANEL)
            cell.grid(row=0, column=column, sticky="w", padx=(0 if column == 0 else 10, 0))
            tk.Label(cell, text=title, bg=PANEL, fg=MUTED, font=("Segoe UI", 7, "bold"), anchor="w").pack(anchor="w")
            value = tk.Label(cell, text="—", bg=PANEL, fg=TEXT, font=("Segoe UI", 12, "bold"), anchor="w")
            value.pack(anchor="w", pady=(4, 0))
            self.insight_value[key] = value

        tk.Label(
            inner,
            text="Зардлыг тухайн төслийн админ панелд бүртгэнэ.",
            bg=PANEL,
            fg=DIM,
            font=("Segoe UI", 8),
            anchor="w",
            wraplength=330,
            justify="left",
        ).pack(side="bottom", anchor="w", pady=(12, 0))

    def render_cost_rows(self, categories: dict[str, int]) -> None:
        for child in self.cost_rows_frame.winfo_children():
            child.destroy()
        self.cost_values = {}
        self.cost_bars = {}
        if not categories:
            tk.Label(
                self.cost_rows_frame,
                text="Зардал бүртгэгдээгүй",
                bg=PANEL,
                fg=DIM,
                font=("Segoe UI", 9),
                anchor="w",
            ).pack(anchor="w", pady=(0, 12))
            return
        maximum = max(max(categories.values()), 1)
        for key, amount in categories.items():
            label, color = category_meta(key)
            row = tk.Frame(self.cost_rows_frame, bg=PANEL)
            row.pack(fill="x", pady=(0, 12))
            head = tk.Frame(row, bg=PANEL)
            head.pack(fill="x")
            dot = tk.Canvas(head, width=8, height=8, bg=PANEL, highlightthickness=0)
            dot.pack(side="left", padx=(0, 7))
            dot.create_oval(0, 0, 8, 8, fill=color, outline="")
            tk.Label(head, text=label, bg=PANEL, fg=TEXT, font=("Segoe UI", 9)).pack(side="left")
            value = tk.Label(head, text=fmt_money(amount), bg=PANEL, fg=MUTED, font=("Segoe UI", 9, "bold"))
            value.pack(side="right")
            self.cost_values[key] = value
            track = tk.Frame(row, bg=TRACK, height=5)
            track.pack(fill="x", pady=(7, 0))
            track.pack_propagate(False)
            bar = tk.Frame(track, bg=color)
            bar.place(x=0, y=0, relheight=1, relwidth=min(max(amount, 0) / maximum, 1.0))
            self.cost_bars[key] = bar

    def build_footer(self, parent: tk.Frame) -> None:
        footer = tk.Frame(parent, bg=BG)
        footer.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        footer.grid_columnconfigure(0, weight=1)
        self.endpoint_label = tk.Label(
            footer,
            text="",
            bg=BG,
            fg=DIM,
            font=("Segoe UI", 8),
            anchor="w",
        )
        self.endpoint_label.grid(row=0, column=0, sticky="w")
        self.updated_label = tk.Label(
            footer,
            text="F5 сэргээх · 60 сек тутам автомат",
            bg=BG,
            fg=DIM,
            font=("Segoe UI", 8),
            anchor="e",
        )
        self.updated_label.grid(row=0, column=1, sticky="e")

    def legend_item(self, parent: tk.Misc, text: str, color: str) -> tk.Frame:
        item = tk.Frame(parent, bg=PANEL)
        dot = tk.Canvas(item, width=8, height=8, bg=PANEL, highlightthickness=0)
        dot.pack(side="left", padx=(0, 6))
        dot.create_oval(0, 0, 8, 8, fill=color, outline="")
        tk.Label(item, text=text, bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(side="left")
        return item

    def startup(self) -> None:
        project = self.current_project()
        if project is None:
            self.set_status(AMBER, "Төсөл нэмэх")
            self.show_error("Эхлээд төсөл нэмж, API түлхүүрээ оруулна уу.")
            self.open_settings()
            return
        if not project["apiKey"]:
            self.set_status(AMBER, "Тохиргоо хэрэгтэй")
            self.show_error("API түлхүүр оруулж, холболтоо тохируулна уу.")
            self.open_settings()
            return
        self.refresh()

    def schedule_auto(self) -> None:
        if not self.closed:
            self.auto_job = self.root.after(60000, self.auto_tick)

    def auto_tick(self) -> None:
        self.auto_job = None
        self.refresh()
        self.schedule_auto()

    def refresh(self, force_billing: bool = False) -> None:
        self.refresh_neon(force=force_billing)
        self.refresh_vercel(force=force_billing)
        if self.loading:
            return
        project = self.current_project()
        if project is None:
            self.set_status(AMBER, "Төсөл нэмэх")
            self.show_error("Эхлээд төсөл нэмж, API түлхүүрээ оруулна уу.")
            self.open_settings()
            return
        if not project["apiKey"]:
            self.set_status(AMBER, "Тохиргоо хэрэгтэй")
            self.show_error("API түлхүүр оруулж, холболтоо тохируулна уу.")
            self.open_settings()
            return
        self.loading = True
        self.refresh_button.configure(state="disabled", text="Ачаалж байна…")
        self.set_status(ACCENT, "Холбогдож байна")
        self.update_project_chrome()
        worker = threading.Thread(
            target=self.fetch_worker,
            args=(project["id"], project["apiUrl"], project["apiKey"]),
            daemon=True,
        )
        worker.start()

    def fetch_worker(self, project_id: str, api_url: str, api_key: str) -> None:
        try:
            data = fetch_summary(api_url, api_key)
        except RevenueApiError as exc:
            self.result_queue.put(("error", project_id, str(exc)))
        except Exception:
            self.result_queue.put(("error", project_id, "Гэнэтийн алдаа гарлаа. Дахин оролдоно уу."))
        else:
            self.result_queue.put(("ok", project_id, data))

    def poll_results(self) -> None:
        try:
            while True:
                kind, project_id, payload = self.result_queue.get_nowait()
                if kind == "ok" and isinstance(payload, dict):
                    self.on_data(project_id, payload)
                elif kind == "error":
                    self.on_error(project_id, str(payload))
                elif kind == "neon_ok" and isinstance(payload, dict):
                    self.on_neon_data(payload)
                elif kind == "neon_error":
                    self.on_neon_error(str(payload))
                elif kind == "vercel_ok" and isinstance(payload, dict):
                    self.on_vercel_data(payload)
                elif kind == "vercel_error":
                    self.on_vercel_error(str(payload))
        except queue.Empty:
            pass
        if not self.closed:
            self.root.after(120, self.poll_results)

    def on_data(self, project_id: str, data: dict) -> None:
        self.summary_cache[project_id] = data
        if project_id != self.active_id:
            return
        self.loading = False
        self.summary = data
        self.refresh_button.configure(state="normal", text="Сэргээх")
        self.set_status(GREEN, "Холбогдсон")
        self.hide_error()
        self.render_summary()
        self.updated_label.configure(text=f"Шинэчлэгдсэн: {fmt_time(data.get('generatedAt'))}")

    def on_error(self, project_id: str, message: str) -> None:
        if project_id != self.active_id:
            return
        self.loading = False
        self.refresh_button.configure(state="normal", text="Сэргээх")
        self.set_status(RED, "Алдаа")
        self.show_error(message)
        if self.summary is None:
            self.render_empty()

    def refresh_neon(self, force: bool = False) -> None:
        key = str(self.neon.get("apiKey") or "").strip()
        if not key:
            self.neon_billing = None
            self.neon_error = ""
            self.neon_loading = False
            self.render_neon()
            self.render_neon_dialog()
            return
        if self.neon_loading:
            return
        if not force and self.neon_last_fetch and time.time() - self.neon_last_fetch < NEON_REFRESH_SECONDS:
            return
        self.neon_loading = True
        self.neon_error = ""
        self.render_neon()
        self.render_neon_dialog()
        worker = threading.Thread(
            target=self.neon_worker,
            args=(
                key,
                str(self.neon.get("orgId") or ""),
                str(self.neon.get("projectIds") or ""),
                float(self.neon.get("usdMntRate") or DEFAULT_NEON_RATE),
            ),
            daemon=True,
        )
        worker.start()

    def neon_worker(self, api_key: str, org_id: str, project_ids: str, usd_mnt_rate: float) -> None:
        try:
            data = fetch_neon_billing(api_key, org_id, project_ids, usd_mnt_rate)
        except NeonApiError as exc:
            self.result_queue.put(("neon_error", "", str(exc)))
        except Exception:
            self.result_queue.put(("neon_error", "", "Neon API-аас гэнэтийн алдаа гарлаа."))
        else:
            self.result_queue.put(("neon_ok", "", data))

    def on_neon_data(self, data: dict) -> None:
        self.neon_billing = data
        self.neon_loading = False
        self.neon_error = ""
        self.neon_last_fetch = time.time()
        self.render_neon()
        self.render_neon_dialog()

    def on_neon_error(self, message: str) -> None:
        self.neon_loading = False
        self.neon_error = message
        self.neon_last_fetch = time.time()
        self.render_neon()
        self.render_neon_dialog()

    def render_neon(self) -> None:
        value = self.kpi_value.get("neon")
        sub = self.kpi_sub.get("neon")
        if value is None or sub is None:
            return
        if not str(self.neon.get("apiKey") or "").strip():
            value.configure(text="—", fg=TEXT)
            sub.configure(text="Neon API тохируулаагүй")
            return
        if self.neon_loading and self.neon_billing is None:
            value.configure(text="…", fg=TEXT)
            sub.configure(text="Neon-оос уншиж байна…")
            return
        data = self.neon_billing
        if data is None:
            value.configure(text="—", fg=TEXT)
            sub.configure(text="Алдаа · дарж үзнэ үү" if self.neon_error else "API тооцоо")
            return
        total_usd = float(data.get("totalUsd", 0) or 0)
        total_mnt = int(data.get("totalMnt", 0) or 0)
        projects = len(data.get("projects") or [])
        value.configure(text=fmt_usd(total_usd), fg=AMBER if total_usd > 0 else GREEN)
        suffix = f" · {projects} төсөл" if projects else ""
        sub.configure(text=f"≈ {fmt_money(total_mnt)}{suffix}")

    def refresh_vercel(self, force: bool = False) -> None:
        token = str(self.vercel.get("apiToken") or "").strip()
        if not token:
            self.vercel_billing = None
            self.vercel_error = ""
            self.vercel_loading = False
            self.render_vercel()
            self.render_vercel_dialog()
            return
        if self.vercel_loading:
            return
        if not force and self.vercel_last_fetch and time.time() - self.vercel_last_fetch < VERCEL_REFRESH_SECONDS:
            return
        self.vercel_loading = True
        self.vercel_error = ""
        self.render_vercel()
        self.render_vercel_dialog()
        worker = threading.Thread(
            target=self.vercel_worker,
            args=(
                token,
                str(self.vercel.get("teamId") or ""),
                str(self.vercel.get("slug") or ""),
                float(self.vercel.get("usdMntRate") or DEFAULT_VERCEL_RATE),
            ),
            daemon=True,
        )
        worker.start()

    def vercel_worker(self, api_token: str, team_id: str, slug: str, usd_mnt_rate: float) -> None:
        try:
            data = fetch_vercel_billing(api_token, team_id, slug, usd_mnt_rate)
        except VercelApiError as exc:
            self.result_queue.put(("vercel_error", "", str(exc)))
        except Exception:
            self.result_queue.put(("vercel_error", "", "Vercel API-аас гэнэтийн алдаа гарлаа."))
        else:
            self.result_queue.put(("vercel_ok", "", data))

    def on_vercel_data(self, data: dict) -> None:
        self.vercel_billing = data
        self.vercel_loading = False
        self.vercel_error = ""
        self.vercel_last_fetch = time.time()
        self.render_vercel()
        self.render_vercel_dialog()

    def on_vercel_error(self, message: str) -> None:
        self.vercel_loading = False
        self.vercel_error = message
        self.vercel_last_fetch = time.time()
        self.render_vercel()
        self.render_vercel_dialog()

    def render_vercel(self) -> None:
        value = self.kpi_value.get("vercel")
        sub = self.kpi_sub.get("vercel")
        if value is None or sub is None:
            return
        if not str(self.vercel.get("apiToken") or "").strip():
            value.configure(text="—", fg=TEXT)
            sub.configure(text="Vercel API тохируулаагүй")
            return
        if self.vercel_loading and self.vercel_billing is None:
            value.configure(text="…", fg=TEXT)
            sub.configure(text="Vercel-ээс уншиж байна…")
            return
        data = self.vercel_billing
        if data is None:
            value.configure(text="—", fg=TEXT)
            sub.configure(text="Алдаа · дарж үзнэ үү" if self.vercel_error else "FOCUS API")
            return
        billing_usd = float(data.get("billingCostUsd", 0) or 0)
        credit_used = float(data.get("creditUsedUsd", 0) or 0)
        credit_total = float(data.get("creditAllocatedUsd", 20) or 20)
        credit_pct = float(data.get("creditUsedPct", 0) or 0)
        prefix = "" if data.get("invoicePaid") else "≈ "
        value.configure(
            text=f"{prefix}{fmt_usd_vercel(billing_usd)}",
            fg=AMBER if billing_usd > 0 else GREEN,
        )
        sub.configure(
            text=(
                f"Кредит {fmt_usd_vercel(credit_used)}/{fmt_usd_vercel(credit_total)} · "
                f"+{fmt_usd_vercel(float(data.get('paidOtherInvoiceTotalUsd', 0) or 0))}"
                if float(data.get("paidOtherInvoiceTotalUsd", 0) or 0) > 0
                else f"Кредит {fmt_usd_vercel(credit_used)}/{fmt_usd_vercel(credit_total)} · {credit_pct:.0f}%"
            )
        )

    def set_status(self, color: str, text: str) -> None:
        self.status_dot.itemconfigure(self.status_dot_id, fill=color)
        self.status_label.configure(text=text, fg=color)

    def show_error(self, message: str) -> None:
        self.error_label.configure(text=message)
        self.error_banner.grid()

    def hide_error(self) -> None:
        self.error_banner.grid_remove()

    def render_empty(self) -> None:
        for label in self.kpi_value.values():
            label.configure(text="—", fg=TEXT)
        self.kpi_sub["revenue"].configure(text="Баталгаажсан төлбөр")
        self.kpi_sub["month"].configure(text="Энэ сар")
        self.kpi_sub["profit"].configure(text="Орлогоос зардал хассан")
        self.kpi_sub["cost"].configure(text="Зардлын нийлбэр")
        self.kpi_sub["neon"].configure(text="API тооцоо")
        self.kpi_sub["vercel"].configure(text="Credit + invoice")
        self.render_cost_rows({})
        self.month_profit.configure(text="—", fg=GREEN)
        self.month_margin.configure(text="")
        for label in self.insight_value.values():
            label.configure(text="—")
        self.chart_hint.configure(text="")
        self.render_neon()
        self.render_vercel()
        self.redraw_chart()

    def render_summary(self) -> None:
        if not self.summary:
            return
        total = self.summary.get("allTime", {})
        current = self.summary.get("current", {})
        revenue = int(total.get("revenue", 0) or 0)
        cost = int(total.get("cost", 0) or 0)
        profit = int(total.get("profit", 0) or 0)
        payments = int(total.get("payments", 0) or 0)
        margin = (profit / revenue * 100) if revenue else 0

        self.kpi_value["revenue"].configure(text=fmt_money(revenue))
        self.kpi_sub["revenue"].configure(text=f"{payments} баталгаажсан төлбөр")
        self.kpi_value["month"].configure(text=fmt_money(current.get("revenue", 0)))
        self.kpi_sub["month"].configure(
            text=f"{month_name(str(current.get('month', '')))} · {int(current.get('payments', 0) or 0)} төлбөр"
        )
        self.kpi_value["profit"].configure(text=fmt_money(profit), fg=GREEN if profit >= 0 else RED)
        self.kpi_sub["profit"].configure(text=f"Ашгийн хувь {margin:.1f}%")
        self.kpi_value["cost"].configure(text=fmt_money(cost))
        self.kpi_sub["cost"].configure(text="Зардлын нийлбэр")

        by_category = self.summary.get("byCategory") or {}
        categories: dict[str, int] = {}
        if isinstance(by_category, dict):
            for key, value in by_category.items():
                try:
                    categories[str(key)] = int(value or 0)
                except (TypeError, ValueError):
                    continue
        if not categories and cost:
            categories = {"custom": cost}
        ordered: dict[str, int] = {}
        for key in ("neon", "vercel", "custom"):
            if key in categories:
                ordered[key] = categories[key]
        for key, value in categories.items():
            if key not in ordered:
                ordered[key] = value
        self.render_cost_rows(ordered)

        current_profit = int(current.get("profit", 0) or 0)
        current_revenue = int(current.get("revenue", 0) or 0)
        current_margin = (current_profit / current_revenue * 100) if current_revenue else 0
        self.month_profit.configure(
            text=fmt_money(current_profit),
            fg=GREEN if current_profit >= 0 else RED,
        )
        self.month_margin.configure(
            text=f"Ашгийн хувь {current_margin:.1f}% · {int(current.get('payments', 0) or 0)} төлбөр"
        )

        series = self.summary.get("series") or []
        average = sum(float(row.get("revenue", 0) or 0) for row in series) / max(len(series), 1)
        cost_ratio = (cost / revenue * 100) if revenue else 0
        self.insight_value["ratio"].configure(text=f"{cost_ratio:.1f}%")
        self.insight_value["average"].configure(text=fmt_money(average))
        self.redraw_chart()

    def category(self, key: str) -> int:
        if not self.summary:
            return 0
        by_category = self.summary.get("byCategory") or {}
        try:
            return int(by_category.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    def redraw_chart(self) -> None:
        canvas = self.chart
        canvas.delete("all")
        width = max(canvas.winfo_width(), 460)
        height = max(canvas.winfo_height(), 220)
        series = (self.summary or {}).get("series")
        if not isinstance(series, list) or not series:
            canvas.create_text(
                width / 2,
                height / 2,
                text="Өгөгдөл ачаалж байна…" if self.loading else "Өгөгдөл байхгүй",
                fill=DIM,
                font=("Segoe UI", 10),
            )
            self.chart_geometry = None
            return

        left, right, top, bottom = 58, 12, 14, 32
        plot_width = max(width - left - right, 100)
        plot_height = max(height - top - bottom, 80)
        maximum = nice_ceiling(
            max(max(float(row.get("revenue", 0) or 0), float(row.get("cost", 0) or 0)) for row in series)
        )

        for index in range(5):
            value = maximum * index / 4
            y = top + plot_height * (1 - index / 4)
            canvas.create_line(left, y, width - right, y, fill="#1a2535")
            canvas.create_text(
                left - 9,
                y,
                text=fmt_short(value),
                anchor="e",
                fill=DIM,
                font=("Segoe UI", 7),
            )

        count = len(series)
        group_width = plot_width / count
        bar_width = min(18.0, group_width * 0.27)
        gap = min(4.0, group_width * 0.08)
        baseline = top + plot_height
        last_index = count - 1

        for index, row in enumerate(series):
            group_left = left + group_width * index
            if index == last_index:
                canvas.create_rectangle(
                    group_left + 1,
                    top,
                    group_left + group_width - 1,
                    baseline,
                    fill="#151f30",
                    outline="",
                )
            revenue_height = plot_height * float(row.get("revenue", 0) or 0) / maximum
            cost_height = plot_height * float(row.get("cost", 0) or 0) / maximum
            center = group_left + group_width / 2
            revenue_x = center - bar_width - gap / 2
            cost_x = center + gap / 2
            canvas.create_rectangle(
                revenue_x,
                baseline - revenue_height,
                revenue_x + bar_width,
                baseline,
                fill=ACCENT,
                outline="",
            )
            canvas.create_rectangle(
                cost_x,
                baseline - cost_height,
                cost_x + bar_width,
                baseline,
                fill=RED,
                outline="",
            )
            canvas.create_text(
                center,
                baseline + 13,
                text=fmt_month(str(row.get("month", ""))),
                fill=MUTED if index == last_index else DIM,
                font=("Segoe UI", 7, "bold" if index == last_index else "normal"),
            )

        self.chart_geometry = (left, group_width, count, plot_height, top)
        self.reset_chart_hint()

    def reset_chart_hint(self) -> None:
        if not self.summary:
            self.chart_hint.configure(text="")
            return
        current = self.summary.get("current", {})
        self.chart_hint.configure(
            text=(
                f"{month_name(str(current.get('month', '')))}: орлого {fmt_money(current.get('revenue', 0))}"
                f" · зардал {fmt_money(current.get('cost', 0))}"
                f" · цэвэр ашиг {fmt_money(current.get('profit', 0))}"
            )
        )

    def chart_motion(self, event: tk.Event) -> None:
        if not self.summary or not self.chart_geometry:
            return
        left, group_width, count, _plot_height, _top = self.chart_geometry
        index = int((event.x - left) // group_width)
        if index < 0 or index >= count:
            self.reset_chart_hint()
            return
        row = self.summary["series"][index]
        self.chart_hint.configure(
            text=(
                f"{fmt_month(str(row.get('month', '')))}: орлого {fmt_money(row.get('revenue', 0))}"
                f" · зардал {fmt_money(row.get('cost', 0))}"
                f" · цэвэр ашиг {fmt_money(row.get('profit', 0))}"
            )
        )

    def open_neon_settings(self) -> None:
        if self.neon_settings_window is not None:
            self.neon_settings_window.lift()
            self.neon_settings_window.focus_force()
            return
        window = tk.Toplevel(self.root)
        self.neon_settings_window = window
        window.title("Neon API тохиргоо")
        window.configure(bg=BG)
        window.resizable(False, False)
        window.transient(self.root)
        window.grab_set()
        width, height = 600, 650
        center_toplevel(window, width, height)
        window.after(60, lambda: enable_dark_titlebar(window))

        panel = tk.Frame(window, bg=BG, padx=26, pady=22)
        panel.pack(fill="both", expand=True)
        tk.Label(panel, text="Neon API тохиргоо", bg=BG, fg=TEXT, font=("Segoe UI", 16, "bold"), anchor="w").pack(anchor="w")
        tk.Label(
            panel,
            text="Neon Console-ийн API key-ээр одоогийн consumption зардлыг тооцоолно.",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(anchor="w", pady=(4, 4))

        self.neon_key = self.add_settings_field(panel, "Neon API түлхүүр", "Neon Console → Account settings → API keys")
        self.neon_key.configure(show="•")
        self.neon_show_key = tk.BooleanVar(value=False)
        tk.Checkbutton(
            panel,
            text="Түлхүүрийг харуулах",
            variable=self.neon_show_key,
            command=lambda: self.neon_key.configure(show="" if self.neon_show_key.get() else "•"),
            bg=BG,
            fg=MUTED,
            activebackground=BG,
            activeforeground=TEXT,
            selectcolor=PANEL_ALT,
            font=("Segoe UI", 8),
            bd=0,
            highlightthickness=0,
        ).pack(anchor="w", pady=(4, 0))
        self.neon_org = self.add_settings_field(
            panel,
            "Organization ID (заавал биш)",
            "org-... ; хоосон бол эхний organization-г автоматаар сонгоно",
        )
        self.neon_projects = self.add_settings_field(
            panel,
            "Project ID (заавал биш)",
            "Таслалаар тусгаарлана; хоосон бол бүх төслийн зардлыг нэмнэ",
        )
        self.neon_rate = self.add_settings_field(
            panel,
            "USD → MNT ханш",
            f"Анхдагч {DEFAULT_NEON_RATE:,.0f}. Тооцооллын ханшийг өөрчилж болно.",
        )

        neon = self.neon
        self.neon_key.insert(0, str(neon.get("apiKey") or ""))
        self.neon_org.insert(0, str(neon.get("orgId") or ""))
        self.neon_projects.insert(0, str(neon.get("projectIds") or ""))
        rate = neon.get("usdMntRate") or DEFAULT_NEON_RATE
        self.neon_rate.insert(0, f"{float(rate):g}")

        tk.Label(
            panel,
            text="Түлхүүр зөвхөн энэ компьютерт (config.json) хадгалагдана. Neon API нь зөвхөн\nтөлбөртэй Launch / Scale / Agent / Enterprise планы consumption өгөгдөл уншина.",
            bg=BG,
            fg=DIM,
            font=("Segoe UI", 8),
            anchor="w",
            justify="left",
        ).pack(anchor="w", pady=(14, 0))

        buttons = tk.Frame(panel, bg=BG)
        buttons.pack(side="bottom", fill="x", pady=(16, 0))
        flat_button(buttons, "Хадгалах", lambda: self.save_neon_settings(window), True).pack(side="right")
        flat_button(buttons, "Болих", lambda: self.close_neon_settings(window)).pack(side="right", padx=(0, 8))
        window.bind("<Return>", lambda _event: self.save_neon_settings(window))
        window.bind("<Escape>", lambda _event: self.close_neon_settings(window))
        window.protocol("WM_DELETE_WINDOW", lambda: self.close_neon_settings(window))
        self.neon_key.focus_set()

    def save_neon_settings(self, window: tk.Toplevel) -> None:
        key = self.neon_key.get().strip()
        org_id = self.neon_org.get().strip()
        project_ids = self.neon_projects.get().strip()
        try:
            rate = float(self.neon_rate.get().strip().replace(",", "."))
        except ValueError:
            messagebox.showerror("Neon тохиргоо", "USD → MNT ханш тоо байх ёстой.", parent=window)
            return
        if not 1 <= rate <= 100_000:
            messagebox.showerror("Neon тохиргоо", "Ханш 1-100000 хооронд байх ёстой.", parent=window)
            return
        self.neon = clean_neon(
            {"apiKey": key, "orgId": org_id, "projectIds": project_ids, "usdMntRate": rate}
        )
        self.config["neon"] = self.neon
        if not self.persist_config():
            messagebox.showerror("Neon тохиргоо", "Тохиргоог хадгалж чадсангүй.", parent=window)
            return
        self.close_neon_settings(window)
        self.neon_billing = None
        self.neon_error = ""
        self.neon_last_fetch = 0.0
        self.render_neon()
        self.render_neon_dialog()
        if key:
            self.refresh_neon(force=True)

    def close_neon_settings(self, window: tk.Toplevel) -> None:
        if self.neon_settings_window is window:
            self.neon_settings_window = None
        try:
            window.grab_release()
        except tk.TclError:
            pass
        window.destroy()

    def open_neon_dialog(self) -> None:
        if self.neon_window is not None:
            self.neon_window.lift()
            self.neon_window.focus_force()
            return
        window = tk.Toplevel(self.root)
        self.neon_window = window
        window.title("Neon төлбөр")
        window.configure(bg=BG)
        window.transient(self.root)
        width, height = 820, 680
        center_toplevel(window, width, height)
        window.minsize(720, 560)
        window.after(60, lambda: enable_dark_titlebar(window))
        window.protocol("WM_DELETE_WINDOW", lambda: self.close_neon_dialog(window))

        panel = tk.Frame(window, bg=BG, padx=26, pady=22)
        panel.pack(fill="both", expand=True)
        header = tk.Frame(panel, bg=BG)
        header.pack(fill="x")
        header.grid_columnconfigure(0, weight=1)
        tk.Label(header, text="Neon төлбөр", bg=BG, fg=TEXT, font=("Segoe UI", 16, "bold"), anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(
            header,
            text="Consumption API-аас тооцоолсон одоогийн зардал",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        flat_button(header, "Neon тохиргоо", self.open_neon_settings).grid(row=0, column=1, rowspan=2, sticky="e")

        self.neon_dialog_total = tk.Label(panel, text="—", bg=BG, fg=TEXT, font=("Segoe UI", 30, "bold"), anchor="w")
        self.neon_dialog_total.pack(anchor="w", pady=(16, 2))
        self.neon_dialog_meta = tk.Label(panel, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w")
        self.neon_dialog_meta.pack(anchor="w")

        tiles = tk.Frame(panel, bg=BG)
        tiles.pack(fill="x", pady=(16, 0))
        for column in range(4):
            tiles.grid_columnconfigure(column, weight=1, uniform="neon")
        self.neon_tile_value: dict[str, tk.Label] = {}
        self.neon_tile_sub: dict[str, tk.Label] = {}
        tile_specs = (
            ("month", "ЭНЭ САРЫН ТООЦОО"),
            ("projected", "САРЫН ТӨГСӨЛИЙН ТӨСӨӨЛӨЛ"),
            ("daily", "ӨДРИЙН ДУНДАЖ"),
            ("limit", "SPENDING LIMIT"),
        )
        for index, (key, title) in enumerate(tile_specs):
            cell = tk.Frame(tiles, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
            cell.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 7, 0))
            inner = tk.Frame(cell, bg=PANEL)
            inner.pack(fill="both", expand=True, padx=14, pady=11)
            tk.Label(inner, text=title, bg=PANEL, fg=MUTED, font=("Segoe UI", 7, "bold"), anchor="w").pack(anchor="w")
            value = tk.Label(inner, text="—", bg=PANEL, fg=TEXT, font=("Segoe UI", 15, "bold"), anchor="w")
            value.pack(anchor="w", pady=(4, 1))
            sub = tk.Label(inner, text="", bg=PANEL, fg=DIM, font=("Segoe UI", 7), anchor="w")
            sub.pack(anchor="w")
            self.neon_tile_value[key] = value
            self.neon_tile_sub[key] = sub

        tk.Label(panel, text="ТӨСЛҮҮДИЙН ЗАДАРГАА", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w").pack(
            anchor="w", pady=(18, 8)
        )
        self.neon_dialog_body = tk.Frame(panel, bg=BG)
        self.neon_dialog_body.pack(fill="both", expand=True)

        tk.Label(
            panel,
            text="Neon consumption өгөгдөл ~15 мин тутам шинэчлэгддэг. Энэ бол тооцоолол, эцсийн нэхэмжлэл биш.\n"
            "Neon API зардал нь админ панелд гараар бүртгэсэн зардлаас тусдаа харагдана.",
            bg=BG,
            fg=DIM,
            font=("Segoe UI", 8),
            anchor="w",
            justify="left",
        ).pack(anchor="w", pady=(10, 0))
        buttons = tk.Frame(panel, bg=BG)
        buttons.pack(fill="x", pady=(10, 0))
        flat_button(buttons, "Сэргээх", lambda: self.refresh_neon(force=True), True).pack(side="left")
        flat_button(buttons, "Хаах", lambda: self.close_neon_dialog(window)).pack(side="right")
        self.render_neon_dialog()

    def close_neon_dialog(self, window: tk.Toplevel) -> None:
        if self.neon_window is window:
            self.neon_window = None
        window.destroy()

    def render_neon_dialog(self) -> None:
        if self.neon_window is None or not hasattr(self, "neon_dialog_total"):
            return
        if not str(self.neon.get("apiKey") or "").strip():
            self.neon_dialog_total.configure(text="—", fg=TEXT)
            self.neon_dialog_meta.configure(text="Neon API түлхүүр тохируулаагүй байна.")
            for key in self.neon_tile_value:
                self.neon_tile_value[key].configure(text="—", fg=TEXT)
                self.neon_tile_sub[key].configure(text="")
            self.clear_neon_dialog_body()
            tk.Label(
                self.neon_dialog_body,
                text="Neon Console → Account settings → API keys-ээс түлхүүр авч, «Neon тохиргоо»-д оруулна уу.",
                bg=BG,
                fg=MUTED,
                font=("Segoe UI", 9),
                anchor="w",
                wraplength=720,
                justify="left",
            ).pack(anchor="w")
            return
        if self.neon_loading and self.neon_billing is None:
            self.neon_dialog_total.configure(text="…", fg=TEXT)
            self.neon_dialog_meta.configure(text="Neon consumption өгөгдөл уншиж байна…")
            self.clear_neon_dialog_body()
            return
        data = self.neon_billing
        if data is None:
            message = self.neon_error or "Neon API өгөгдөл байхгүй."
            self.neon_dialog_total.configure(text="—", fg=TEXT)
            self.neon_dialog_meta.configure(text=message)
            for key in self.neon_tile_value:
                self.neon_tile_value[key].configure(text="—", fg=TEXT)
                self.neon_tile_sub[key].configure(text="")
            self.clear_neon_dialog_body()
            tk.Label(
                self.neon_dialog_body,
                text=message,
                bg=BG,
                fg=RED,
                font=("Segoe UI", 9),
                anchor="w",
                wraplength=720,
                justify="left",
            ).pack(anchor="w")
            return

        total_usd = float(data.get("totalUsd", 0) or 0)
        total_mnt = int(data.get("totalMnt", 0) or 0)
        self.neon_dialog_total.configure(text=fmt_usd(total_usd), fg=GREEN if total_usd == 0 else TEXT)
        period_start = fmt_time(data.get("periodStart"))[:10].replace("-", ".")
        period_end = fmt_time(data.get("periodEnd"))[:10].replace("-", ".")
        self.neon_dialog_meta.configure(
            text=f"≈ {fmt_money(total_mnt)} · {data.get('orgName', '')} · {period_start} — {period_end} · 1 USD = {float(data.get('usdMntRate', 0)):g}₮"
        )
        self.neon_tile_value["month"].configure(text=fmt_usd(total_usd), fg=TEXT)
        self.neon_tile_sub["month"].configure(text=f"≈ {fmt_money(total_mnt)}")
        self.neon_tile_value["projected"].configure(text=fmt_usd(float(data.get("projectedUsd", 0) or 0)), fg=TEXT)
        self.neon_tile_sub["projected"].configure(text=f"≈ {fmt_money(data.get('projectedMnt', 0))}")
        self.neon_tile_value["daily"].configure(text=fmt_usd(float(data.get("dailyAvgUsd", 0) or 0)), fg=TEXT)
        self.neon_tile_sub["daily"].configure(text="өнөөг хүртэл")
        limit_cents = data.get("spendingLimitCents")
        if limit_cents is None:
            self.neon_tile_value["limit"].configure(text="—", fg=TEXT)
            self.neon_tile_sub["limit"].configure(text="тохируулаагүй")
        else:
            self.neon_tile_value["limit"].configure(text=fmt_usd(float(limit_cents) / 100), fg=TEXT)
            self.neon_tile_sub["limit"].configure(text="сарын хязгаар")

        self.clear_neon_dialog_body()
        projects = data.get("projects") or []
        if not projects:
            tk.Label(
                self.neon_dialog_body,
                text="Энэ сард Neon consumption өгөгдөл алга.",
                bg=BG,
                fg=MUTED,
                font=("Segoe UI", 9),
                anchor="w",
            ).pack(anchor="w")
            return
        for project in projects[:8]:
            card = tk.Frame(self.neon_dialog_body, bg=PANEL_ALT, highlightbackground=BORDER, highlightthickness=1)
            card.pack(fill="x", pady=(0, 7))
            inner = tk.Frame(card, bg=PANEL_ALT)
            inner.pack(fill="x", padx=14, pady=9)
            head = tk.Frame(inner, bg=PANEL_ALT)
            head.pack(fill="x")
            tk.Label(
                head,
                text=str(project.get("name") or project.get("id") or "Neon"),
                bg=PANEL_ALT,
                fg=TEXT,
                font=("Segoe UI", 10, "bold"),
                anchor="w",
            ).pack(side="left")
            tk.Label(
                head,
                text=str(project.get("plan") or "").upper(),
                bg=PANEL_ALT,
                fg=DIM,
                font=("Segoe UI", 7, "bold"),
                anchor="w",
            ).pack(side="left", padx=(9, 0))
            tk.Label(
                head,
                text=f"{fmt_usd(float(project.get('totalUsd', 0) or 0))}  ≈ {fmt_money(project.get('totalMnt', 0))}",
                bg=PANEL_ALT,
                fg=TEXT,
                font=("Segoe UI", 9, "bold"),
                anchor="e",
            ).pack(side="right")
            usage = project.get("usage") or {}
            tk.Label(
                inner,
                text=(
                    f"{float(usage.get('compute_cu_hours', 0) or 0):.2f} CU-h · "
                    f"{float(usage.get('storage_gb_months', 0) or 0):.3f} GB-mo · "
                    f"{float(usage.get('public_gb', 0) or 0):.1f} GB transfer · "
                    f"{float(usage.get('branch_months', 0) or 0):.2f} branch-mo"
                ),
                bg=PANEL_ALT,
                fg=MUTED,
                font=("Segoe UI", 8),
                anchor="w",
            ).pack(anchor="w", pady=(4, 0))
            costs = project.get("costs") or {}
            tk.Label(
                inner,
                text=(
                    f"Compute {fmt_usd(float(costs.get('compute', 0) or 0))} · "
                    f"Storage {fmt_usd(float(costs.get('storage', 0) or 0))} · "
                    f"Transfer {fmt_usd(float(costs.get('transfer', 0) or 0))} · "
                    f"Branches {fmt_usd(float(costs.get('branches', 0) or 0))}"
                ),
                bg=PANEL_ALT,
                fg=DIM,
                font=("Segoe UI", 8),
                anchor="w",
            ).pack(anchor="w", pady=(2, 0))
        if len(projects) > 6:
            tk.Label(
                self.neon_dialog_body,
                text=f"… өөр {len(projects) - 6} төсөл",
                bg=BG,
                fg=DIM,
                font=("Segoe UI", 8),
                anchor="w",
            ).pack(anchor="w")

    def clear_neon_dialog_body(self) -> None:
        for child in self.neon_dialog_body.winfo_children():
            child.destroy()

    def open_vercel_settings(self) -> None:
        if self.vercel_settings_window is not None:
            self.vercel_settings_window.lift()
            self.vercel_settings_window.focus_force()
            return
        window = tk.Toplevel(self.root)
        self.vercel_settings_window = window
        window.title("Vercel API тохиргоо")
        window.configure(bg=BG)
        window.resizable(False, False)
        window.transient(self.root)
        window.grab_set()
        width, height = 620, 720
        center_toplevel(window, width, height)
        window.after(60, lambda: enable_dark_titlebar(window))

        panel = tk.Frame(window, bg=BG, padx=26, pady=22)
        panel.pack(fill="both", expand=True)
        tk.Label(panel, text="Vercel API тохиргоо", bg=BG, fg=TEXT, font=("Segoe UI", 16, "bold"), anchor="w").pack(anchor="w")
        tk.Label(
            panel,
            text="FOCUS charges, Pro-ийн $20 credit, төлсөн нэхэмжлэлийг уншина.",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(anchor="w", pady=(4, 4))

        self.vercel_token = self.add_settings_field(
            panel,
            "Vercel API токен",
            "Vercel → Account settings → Tokens",
        )
        self.vercel_token.configure(show="•")
        self.vercel_show_token = tk.BooleanVar(value=False)
        tk.Checkbutton(
            panel,
            text="Токеныг харуулах",
            variable=self.vercel_show_token,
            command=lambda: self.vercel_token.configure(show="" if self.vercel_show_token.get() else "•"),
            bg=BG,
            fg=MUTED,
            activebackground=BG,
            activeforeground=TEXT,
            selectcolor=PANEL_ALT,
            font=("Segoe UI", 8),
            bd=0,
            highlightthickness=0,
        ).pack(anchor="w", pady=(4, 0))
        self.vercel_team = self.add_settings_field(
            panel,
            "Team ID (заавал биш)",
            "team_... ; хоосон бол токены хувийн account",
        )
        self.vercel_slug = self.add_settings_field(
            panel,
            "Team slug (заавал биш)",
            "Team ID байхгүй бол team-ийн URL slug-ийг оруулна",
        )
        self.vercel_rate = self.add_settings_field(
            panel,
            "USD → MNT ханш",
            f"Анхдагч {DEFAULT_VERCEL_RATE:,.0f}. Тооцооллын ханшийг өөрчилж болно.",
        )

        vercel = self.vercel
        self.vercel_token.insert(0, str(vercel.get("apiToken") or ""))
        self.vercel_team.insert(0, str(vercel.get("teamId") or ""))
        self.vercel_slug.insert(0, str(vercel.get("slug") or ""))
        rate = vercel.get("usdMntRate") or DEFAULT_VERCEL_RATE
        self.vercel_rate.insert(0, f"{float(rate):g}")

        tk.Label(
            panel,
            text=(
                "Токен зөвхөн энэ компьютерт (config.json) хадгалагдана. Billing API нь\n"
                "Pro/Enterprise team-д нээлттэй; токенд Billing/Usage унших эрх хэрэгтэй.\n"
                "Төлсөн нэхэмжлэлүүдийн нийт дүнг /v1/invoices-ээс зардал болгоно; олдохгүй бол тооцоо."
            ),
            bg=BG,
            fg=DIM,
            font=("Segoe UI", 8),
            anchor="w",
            justify="left",
        ).pack(anchor="w", pady=(14, 0))

        buttons = tk.Frame(panel, bg=BG)
        buttons.pack(side="bottom", fill="x", pady=(16, 0))
        flat_button(buttons, "Хадгалах", lambda: self.save_vercel_settings(window), True).pack(side="right")
        flat_button(buttons, "Болих", lambda: self.close_vercel_settings(window)).pack(side="right", padx=(0, 8))
        window.bind("<Return>", lambda _event: self.save_vercel_settings(window))
        window.bind("<Escape>", lambda _event: self.close_vercel_settings(window))
        window.protocol("WM_DELETE_WINDOW", lambda: self.close_vercel_settings(window))
        self.vercel_token.focus_set()

    def save_vercel_settings(self, window: tk.Toplevel) -> None:
        token = self.vercel_token.get().strip()
        team_id = self.vercel_team.get().strip()
        slug = self.vercel_slug.get().strip()
        try:
            rate = float(self.vercel_rate.get().strip().replace(",", "."))
        except ValueError:
            messagebox.showerror("Vercel тохиргоо", "USD → MNT ханш тоо байх ёстой.", parent=window)
            return
        if not 1 <= rate <= 100_000:
            messagebox.showerror("Vercel тохиргоо", "Ханш 1-100000 хооронд байх ёстой.", parent=window)
            return
        self.vercel = clean_vercel(
            {"apiToken": token, "teamId": team_id, "slug": slug, "usdMntRate": rate}
        )
        self.config["vercel"] = self.vercel
        if not self.persist_config():
            messagebox.showerror("Vercel тохиргоо", "Тохиргоог хадгалж чадсангүй.", parent=window)
            return
        self.close_vercel_settings(window)
        self.vercel_billing = None
        self.vercel_error = ""
        self.vercel_last_fetch = 0.0
        self.render_vercel()
        self.render_vercel_dialog()
        if token:
            self.refresh_vercel(force=True)

    def close_vercel_settings(self, window: tk.Toplevel) -> None:
        if self.vercel_settings_window is window:
            self.vercel_settings_window = None
        try:
            window.grab_release()
        except tk.TclError:
            pass
        window.destroy()

    def open_vercel_dialog(self) -> None:
        if self.vercel_window is not None:
            self.vercel_window.lift()
            self.vercel_window.focus_force()
            return
        window = tk.Toplevel(self.root)
        self.vercel_window = window
        window.title("Vercel төлбөр")
        window.configure(bg=BG)
        window.transient(self.root)
        width, height = 880, 900
        center_toplevel(window, width, height)
        window.minsize(760, 680)
        window.after(60, lambda: enable_dark_titlebar(window))
        window.protocol("WM_DELETE_WINDOW", lambda: self.close_vercel_dialog(window))

        panel = tk.Frame(window, bg=BG, padx=26, pady=22)
        panel.pack(fill="both", expand=True)
        header = tk.Frame(panel, bg=BG)
        header.pack(fill="x")
        header.grid_columnconfigure(0, weight=1)
        tk.Label(header, text="Vercel төлбөр", bg=BG, fg=TEXT, font=("Segoe UI", 16, "bold"), anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(
            header,
            text="Pro $20 credit · subscription тусдаа · төлсөн нэхэмжлэл",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        flat_button(header, "Vercel тохиргоо", self.open_vercel_settings).grid(row=0, column=1, rowspan=2, sticky="e")

        self.vercel_dialog_total = tk.Label(panel, text="—", bg=BG, fg=TEXT, font=("Segoe UI", 30, "bold"), anchor="w")
        self.vercel_dialog_total.pack(anchor="w", pady=(16, 2))
        self.vercel_dialog_meta = tk.Label(panel, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w")
        self.vercel_dialog_meta.pack(anchor="w")
        self.vercel_dialog_breakdown = tk.Label(
            panel,
            text="",
            bg=BG,
            fg=AMBER,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        self.vercel_dialog_breakdown.pack(anchor="w", pady=(4, 0))

        tiles = tk.Frame(panel, bg=BG)
        tiles.pack(fill="x", pady=(16, 0))
        for column in range(5):
            tiles.grid_columnconfigure(column, weight=1, uniform="vercel")
        self.vercel_tile_value: dict[str, tk.Label] = {}
        self.vercel_tile_sub: dict[str, tk.Label] = {}
        tile_specs = (
            ("month", "USAGE (FOCUS)"),
            ("credit", "CREDIT АШИГЛАСАН"),
            ("remaining", "КРЕДИТ ҮЛДСЭН"),
            ("overage", "OVERAGE / ТӨСӨӨЛӨЛ"),
            ("invoice", "PRO НЭХЭМЖЛЭЛ"),
        )
        for index, (key, title) in enumerate(tile_specs):
            cell = tk.Frame(tiles, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
            cell.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 7, 0))
            inner = tk.Frame(cell, bg=PANEL)
            inner.pack(fill="both", expand=True, padx=14, pady=11)
            tk.Label(inner, text=title, bg=PANEL, fg=MUTED, font=("Segoe UI", 7, "bold"), anchor="w").pack(anchor="w")
            value = tk.Label(inner, text="—", bg=PANEL, fg=TEXT, font=("Segoe UI", 15, "bold"), anchor="w")
            value.pack(anchor="w", pady=(4, 1))
            sub = tk.Label(inner, text="", bg=PANEL, fg=DIM, font=("Segoe UI", 7), anchor="w")
            sub.pack(anchor="w")
            self.vercel_tile_value[key] = value
            self.vercel_tile_sub[key] = sub

        self.vercel_dialog_detail = tk.Label(
            panel,
            text="",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 8),
            anchor="w",
            justify="left",
            wraplength=820,
        )
        self.vercel_dialog_detail.pack(anchor="w", pady=(12, 0))

        tk.Label(panel, text="ЗАРДЛЫН ЗАДАРГАА", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w").pack(
            anchor="w", pady=(12, 6)
        )
        self.vercel_dialog_body = tk.Frame(panel, bg=BG)
        self.vercel_dialog_body.pack(fill="both", expand=True)

        tk.Label(
            panel,
            text=(
                "Credit usage = infra EffectiveCost (Pro, seats, add-ons хассан). Төлсөн нэхэмжлэл зардал; "
                "Pro болон бусад төлбөрийг тусад нь харуулна. FOCUS 1 өдрийн хоцролттой. "
                "Vercel зардал нь админ панелд гараар бүртгэсэн зардлаас тусдаа."
            ),
            bg=BG,
            fg=DIM,
            font=("Segoe UI", 8),
            anchor="w",
            justify="left",
            wraplength=820,
        ).pack(anchor="w", pady=(6, 0))
        buttons = tk.Frame(panel, bg=BG)
        buttons.pack(fill="x", pady=(6, 0))
        flat_button(buttons, "Сэргээх", lambda: self.refresh_vercel(force=True), True).pack(side="left")
        flat_button(buttons, "Хаах", lambda: self.close_vercel_dialog(window)).pack(side="right")
        self.render_vercel_dialog()

    def close_vercel_dialog(self, window: tk.Toplevel) -> None:
        if self.vercel_window is window:
            self.vercel_window = None
        window.destroy()

    def clear_vercel_dialog_body(self) -> None:
        for child in self.vercel_dialog_body.winfo_children():
            child.destroy()

    def render_vercel_dialog(self) -> None:
        if self.vercel_window is None or not hasattr(self, "vercel_dialog_total"):
            return
        if not str(self.vercel.get("apiToken") or "").strip():
            self.vercel_dialog_total.configure(text="—", fg=TEXT)
            self.vercel_dialog_meta.configure(text="Vercel API токен тохируулаагүй байна.")
            self.vercel_dialog_breakdown.configure(text="")
            for key in self.vercel_tile_value:
                self.vercel_tile_value[key].configure(text="—", fg=TEXT)
                self.vercel_tile_sub[key].configure(text="")
            self.clear_vercel_dialog_body()
            tk.Label(
                self.vercel_dialog_body,
                text="Vercel → Account settings → Tokens-оос токен үүсгэж, «Vercel тохиргоо»-д оруулна уу.",
                bg=BG,
                fg=MUTED,
                font=("Segoe UI", 9),
                anchor="w",
                wraplength=780,
                justify="left",
            ).pack(anchor="w")
            return
        if self.vercel_loading and self.vercel_billing is None:
            self.vercel_dialog_total.configure(text="…", fg=TEXT)
            self.vercel_dialog_meta.configure(text="Vercel billing өгөгдөл уншиж байна…")
            self.vercel_dialog_breakdown.configure(text="")
            self.clear_vercel_dialog_body()
            return
        data = self.vercel_billing
        if data is None:
            message = self.vercel_error or "Vercel billing өгөгдөл байхгүй."
            self.vercel_dialog_total.configure(text="—", fg=TEXT)
            self.vercel_dialog_meta.configure(text=message)
            self.vercel_dialog_breakdown.configure(text="")
            for key in self.vercel_tile_value:
                self.vercel_tile_value[key].configure(text="—", fg=TEXT)
                self.vercel_tile_sub[key].configure(text="")
            self.clear_vercel_dialog_body()
            tk.Label(
                self.vercel_dialog_body,
                text=message,
                bg=BG,
                fg=RED,
                font=("Segoe UI", 9),
                anchor="w",
                wraplength=780,
                justify="left",
            ).pack(anchor="w")
            return

        usage_usd = float(data.get("usageUsd", 0) or 0)
        credit_used = float(data.get("creditUsedUsd", 0) or 0)
        credit_total = float(data.get("creditAllocatedUsd", 20) or 20)
        credit_remaining = float(data.get("creditRemainingUsd", 0) or 0)
        credit_pct = float(data.get("creditUsedPct", 0) or 0)
        overage = float(data.get("creditOverageUsd", 0) or 0)
        projected_overage = float(data.get("projectedOverageUsd", 0) or 0)
        billing_usd = float(data.get("billingCostUsd", 0) or 0)
        billing_mnt = int(data.get("billingCostMnt", 0) or 0)
        paid = bool(data.get("invoicePaid"))
        prefix = "" if paid else "≈ "
        self.vercel_dialog_total.configure(
            text=f"{prefix}{fmt_usd_vercel(billing_usd)}",
            fg=AMBER if billing_usd > 0 else GREEN,
        )
        period_start = fmt_time(data.get("periodStart"))[:10].replace("-", ".")
        period_end = fmt_time(data.get("periodEnd"))[:10].replace("-", ".")
        self.vercel_dialog_meta.configure(
            text=(
                f"{prefix}{fmt_money(billing_mnt)} · {data.get('scope', '')} · {period_start} — {period_end} · "
                f"1 USD = {float(data.get('usdMntRate', 0)):g}₮"
            )
        )

        self.vercel_tile_value["month"].configure(text=fmt_usd_vercel(usage_usd), fg=TEXT)
        self.vercel_tile_sub["month"].configure(
            text=f"≈ {fmt_money(data.get('usageMnt', 0))} · {int(data.get('usageLines', 0) or 0)} charge"
        )
        self.vercel_tile_value["credit"].configure(
            text=fmt_usd_vercel(credit_used),
            fg=AMBER if credit_pct >= 100 else TEXT,
        )
        self.vercel_tile_sub["credit"].configure(text=f"of {fmt_usd_vercel(credit_total)} · {credit_pct:.0f}%")
        self.vercel_tile_value["remaining"].configure(
            text=fmt_usd_vercel(credit_remaining),
            fg=GREEN if credit_remaining > 0 else AMBER,
        )
        self.vercel_tile_sub["remaining"].configure(text="Pro credit үлдэгдэл")
        self.vercel_tile_value["overage"].configure(
            text=fmt_usd_vercel(overage),
            fg=AMBER if overage > 0 else GREEN,
        )
        self.vercel_tile_sub["overage"].configure(text=f"төсөөлөл {fmt_usd_vercel(projected_overage)}")
        latest_invoice = float(data.get("latestPlanInvoiceUsd", 0) or 0) if paid else billing_usd
        self.vercel_tile_value["invoice"].configure(
            text=f"{prefix}{fmt_usd_vercel(latest_invoice)}",
            fg=AMBER if latest_invoice > 0 else GREEN,
        )
        invoice_day = fmt_time(
            data.get("latestPlanInvoicePaidAt") or data.get("invoicePaidAt") or data.get("invoicePeriodStart")
        )[:10].replace("-", ".")
        if paid:
            tile_sub = "Pro subscription"
            if invoice_day:
                tile_sub += f" · {invoice_day}"
            self.vercel_tile_sub["invoice"].configure(text=tile_sub)
        else:
            self.vercel_tile_sub["invoice"].configure(text="тооцоолсон")

        paid_plan_total = float(data.get("paidPlanInvoiceTotalUsd", 0) or 0)
        paid_other_total = float(data.get("paidOtherInvoiceTotalUsd", 0) or 0)
        paid_total = float(data.get("paidInvoiceTotalUsd", billing_usd) or 0)
        if paid:
            self.vercel_dialog_breakdown.configure(
                text=(
                    f"Pro нэхэмжлэл {fmt_usd_vercel(paid_plan_total)} + "
                    f"бусад төлбөр {fmt_usd_vercel(paid_other_total)} = {fmt_usd_vercel(paid_total)}"
                )
            )
        else:
            self.vercel_dialog_breakdown.configure(
                text=f"Тооцоолсон нэхэмжлэл {fmt_usd_vercel(billing_usd)} · төлсөн нэхэмжлэл олдсонгүй"
            )

        details: list[str] = []
        if paid:
            paid_count = int(data.get("paidInvoiceCount", 0) or 0)
            plan_count = int(data.get("paidPlanInvoiceCount", 0) or 0)
            line = f"Төлсөн {paid_count} нэхэмжлэл · нийт {fmt_usd_vercel(paid_total)}"
            if plan_count:
                line += f" · Pro {plan_count}"
            details.append(line)
            invoice_number = str(data.get("latestPlanInvoiceNumber") or "").strip()
            parts: list[str] = []
            if invoice_number:
                part = f"Pro #{invoice_number} {fmt_usd_vercel(latest_invoice)}"
                if invoice_day:
                    part += f" ({invoice_day[5:]})"
                parts.append(part)
            others = [
                item
                for item in (data.get("invoiceBreakdown") or [])
                if float(item.get("otherUsd", 0) or 0) > 0
            ]
            for item in others[:2]:
                number = str(item.get("number") or "").strip()
                amount = float(item.get("usd", 0) or 0)
                day = fmt_time(item.get("paidAt"))[:10].replace("-", ".")
                part = f"Бусад {('#' + number + ' ') if number else ''}{fmt_usd_vercel(amount)}"
                if day:
                    part += f" ({day[5:]})"
                parts.append(part)
            if parts:
                details.append(" · ".join(parts))
        else:
            details.append("Төлсөн нэхэмжлэл олдсонгүй — credit хассан тооцоог харуулж байна.")
        source = "Vercel credit ledger" if data.get("creditSource") == "ledger" else "Pro $20 сарын кредит"
        details.append(
            f"Credit: {source} · өдрийн дундаж {fmt_usd_vercel(float(data.get('dailyAvgUsd', 0) or 0))}"
        )
        subscription = float(data.get("subscriptionUsd", 0) or 0)
        billed = float(data.get("nonCreditUsd", 0) or 0)
        if subscription > 0:
            details.append(
                f"FOCUS subscription {fmt_usd_vercel(subscription)} (credit-д ороогүй) · "
                f"BilledCost {fmt_usd_vercel(billed)}"
            )
        else:
            details.append(f"FOCUS BilledCost {fmt_usd_vercel(billed)} (credit хассан дүн)")
        invoice_error = str(data.get("invoiceError") or "").strip()
        if invoice_error:
            details.append(f"Нэхэмжлэлийн API: {invoice_error}")
        self.vercel_dialog_detail.configure(
            text="\n".join(details),
            fg=AMBER if invoice_error else MUTED,
        )

        self.clear_vercel_dialog_body()
        body = self.vercel_dialog_body
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        services_panel = tk.Frame(body, bg=BG)
        services_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        projects_panel = tk.Frame(body, bg=BG)
        projects_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        tk.Label(services_panel, text="ҮЙЛЧИЛГЭЭ", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w").pack(
            anchor="w", pady=(0, 6)
        )
        services = data.get("services") or []
        if not services:
            tk.Label(
                services_panel,
                text="Энэ сард Vercel billing charge алга.",
                bg=BG,
                fg=MUTED,
                font=("Segoe UI", 9),
                anchor="w",
            ).pack(anchor="w")
        for item in services[:4]:
            row = tk.Frame(services_panel, bg=PANEL_ALT, highlightbackground=BORDER, highlightthickness=1)
            row.pack(fill="x", pady=(0, 5))
            inner = tk.Frame(row, bg=PANEL_ALT)
            inner.pack(fill="x", padx=12, pady=5)
            head = tk.Frame(inner, bg=PANEL_ALT)
            head.pack(fill="x")
            tk.Label(
                head,
                text=str(item.get("name") or "Vercel"),
                bg=PANEL_ALT,
                fg=TEXT,
                font=("Segoe UI", 9, "bold"),
                anchor="w",
            ).pack(side="left")
            tk.Label(
                head,
                text=fmt_usd_vercel(float(item.get("usd", 0) or 0)),
                bg=PANEL_ALT,
                fg=TEXT,
                font=("Segoe UI", 9, "bold"),
                anchor="e",
            ).pack(side="right")
            tk.Label(
                inner,
                text=(
                    f"{item.get('category', '')} · {int(item.get('lines', 0) or 0)} charge · "
                    f"≈ {fmt_money(item.get('mnt', 0))}"
                ),
                bg=PANEL_ALT,
                fg=DIM,
                font=("Segoe UI", 8),
                anchor="w",
            ).pack(anchor="w", pady=(3, 0))
        if len(services) > 4:
            tk.Label(
                services_panel,
                text=f"… өөр {len(services) - 4} үйлчилгээ",
                bg=BG,
                fg=DIM,
                font=("Segoe UI", 8),
                anchor="w",
            ).pack(anchor="w")

        tk.Label(projects_panel, text="ТӨСЛҮҮД", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w").pack(
            anchor="w", pady=(0, 6)
        )
        projects = data.get("projects") or []
        if not projects:
            tk.Label(
                projects_panel,
                text="Project tag-тай charge алга.",
                bg=BG,
                fg=MUTED,
                font=("Segoe UI", 9),
                anchor="w",
            ).pack(anchor="w")
        for item in projects[:4]:
            row = tk.Frame(projects_panel, bg=PANEL_ALT, highlightbackground=BORDER, highlightthickness=1)
            row.pack(fill="x", pady=(0, 5))
            inner = tk.Frame(row, bg=PANEL_ALT)
            inner.pack(fill="x", padx=12, pady=5)
            head = tk.Frame(inner, bg=PANEL_ALT)
            head.pack(fill="x")
            tk.Label(
                head,
                text=str(item.get("name") or "Project"),
                bg=PANEL_ALT,
                fg=TEXT,
                font=("Segoe UI", 9, "bold"),
                anchor="w",
            ).pack(side="left")
            tk.Label(
                head,
                text=fmt_usd_vercel(float(item.get("usd", 0) or 0)),
                bg=PANEL_ALT,
                fg=TEXT,
                font=("Segoe UI", 9, "bold"),
                anchor="e",
            ).pack(side="right")
            tk.Label(
                inner,
                text=f"≈ {fmt_money(item.get('mnt', 0))}",
                bg=PANEL_ALT,
                fg=DIM,
                font=("Segoe UI", 8),
                anchor="w",
            ).pack(anchor="w", pady=(3, 0))
        if len(projects) > 4:
            tk.Label(
                projects_panel,
                text=f"… өөр {len(projects) - 4} төсөл",
                bg=BG,
                fg=DIM,
                font=("Segoe UI", 8),
                anchor="w",
            ).pack(anchor="w")

    def open_settings(self) -> None:
        if self.settings_window is not None:
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        self.settings_window = window
        window.title("Төслийн тохиргоо")
        window.configure(bg=BG)
        window.resizable(False, False)
        window.transient(self.root)
        window.grab_set()
        width, height = 660, 650
        center_toplevel(window, width, height)
        window.after(60, lambda: enable_dark_titlebar(window))

        style = ttk.Style(window)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Dark.TCombobox",
            fieldbackground=PANEL_ALT,
            background=PANEL_ALT,
            foreground=TEXT,
            arrowcolor=MUTED,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=7,
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", PANEL_ALT)],
            foreground=[("readonly", TEXT)],
            selectbackground=[("readonly", PANEL_ALT)],
            selectforeground=[("readonly", TEXT)],
        )

        panel = tk.Frame(window, bg=BG, padx=26, pady=22)
        panel.pack(fill="both", expand=True)
        tk.Label(
            panel,
            text="Төслийн тохиргоо",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 16, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            panel,
            text="Төсөл бүр өөрийн API хаяг, түлхүүртэй. Санхүүгийн нэгдсэн тооцоог уншина.",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(anchor="w", pady=(4, 16))

        tk.Label(panel, text="Төсөл", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w").pack(anchor="w")
        selector_row = tk.Frame(panel, bg=BG)
        selector_row.pack(fill="x", pady=(6, 0))
        selector_row.grid_columnconfigure(0, weight=1)
        self.settings_combo = ttk.Combobox(
            selector_row,
            state="readonly",
            style="Dark.TCombobox",
            font=("Segoe UI", 10),
        )
        self.settings_combo.grid(row=0, column=0, sticky="ew")
        self.settings_combo.bind("<<ComboboxSelected>>", self.load_settings_project)
        flat_button(selector_row, "Шинэ", self.new_settings_project).grid(row=0, column=1, padx=(8, 0))
        self.settings_delete_button = flat_button(selector_row, "Устгах", self.delete_settings_project)
        self.settings_delete_button.grid(row=0, column=2, padx=(8, 0))

        self.settings_name = self.add_settings_field(panel, "Төслийн нэр", "Жишээ: Lexlab эсвэл Миний сайт")
        self.settings_url = self.add_settings_field(
            panel,
            "API хаяг",
            f"Жишээ: {DEFAULT_API_URL} эсвэл http://127.0.0.1:3000",
        )
        self.settings_key = self.add_settings_field(
            panel,
            "API түлхүүр",
            "Тухайн төслийн /api/revenue хаягийн түлхүүр.",
        )
        self.settings_key.configure(show="•")

        self.settings_show_key = tk.BooleanVar(value=False)
        tk.Checkbutton(
            panel,
            text="Түлхүүрийг харуулах",
            variable=self.settings_show_key,
            command=lambda: self.settings_key.configure(show="" if self.settings_show_key.get() else "•"),
            bg=BG,
            fg=MUTED,
            activebackground=BG,
            activeforeground=TEXT,
            selectcolor=PANEL,
            font=("Segoe UI", 8),
            bd=0,
            highlightthickness=0,
        ).pack(anchor="w", pady=(6, 0))

        tk.Label(
            panel,
            text=f"Түлхүүрүүд зөвхөн энэ компьютерт хадгалагдана: {CONFIG_PATH.name}",
            bg=BG,
            fg=DIM,
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(anchor="w", pady=(10, 0))

        buttons = tk.Frame(panel, bg=BG)
        buttons.pack(side="bottom", fill="x", pady=(18, 0))
        flat_button(buttons, "Хадгалах", lambda: self.save_settings(window), True).pack(side="right")
        flat_button(buttons, "Болих", lambda: self.close_settings(window)).pack(side="right", padx=(0, 8))

        window.bind("<Return>", lambda _event: self.save_settings(window))
        window.bind("<Escape>", lambda _event: self.close_settings(window))
        window.protocol("WM_DELETE_WINDOW", lambda: self.close_settings(window))
        self.load_settings_projects(self.active_id)
        self.settings_name.focus_set()

    def add_settings_field(self, parent: tk.Misc, label: str, hint: str) -> tk.Entry:
        tk.Label(parent, text=label, bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold"), anchor="w").pack(
            anchor="w", pady=(14, 0)
        )
        entry = self.dark_entry(parent)
        entry.pack(fill="x", pady=(6, 0))
        tk.Label(
            parent,
            text=hint,
            bg=BG,
            fg=DIM,
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(anchor="w", pady=(4, 0))
        return entry

    def load_settings_projects(self, select_id: str | None) -> None:
        self.settings_combo.configure(values=[project["name"] for project in self.projects])
        project = next((item for item in self.projects if item["id"] == select_id), None)
        if project is None and self.projects:
            project = self.projects[0]
        if project is None:
            self.settings_combo.set("")
            self.new_settings_project()
            return
        self.settings_project_id = project["id"]
        self.settings_combo.set(project["name"])
        self.fill_settings_fields(project)

    def fill_settings_fields(self, project: dict[str, str]) -> None:
        for entry, value in (
            (self.settings_name, project["name"]),
            (self.settings_url, project["apiUrl"]),
            (self.settings_key, project["apiKey"]),
        ):
            entry.delete(0, "end")
            entry.insert(0, value)
        self.settings_show_key.set(False)
        self.settings_key.configure(show="•")
        self.settings_delete_button.configure(state="normal")

    def load_settings_project(self, _event: tk.Event | None = None) -> None:
        name = self.settings_combo.get()
        project = next((item for item in self.projects if item["name"] == name), None)
        if project is None:
            return
        self.settings_project_id = project["id"]
        self.fill_settings_fields(project)

    def new_settings_project(self) -> None:
        self.settings_project_id = None
        self.settings_combo.set("")
        for entry in (self.settings_name, self.settings_url, self.settings_key):
            entry.delete(0, "end")
        self.settings_show_key.set(False)
        self.settings_key.configure(show="•")
        self.settings_delete_button.configure(state="disabled")
        self.settings_name.focus_set()

    def delete_settings_project(self) -> None:
        project = next((item for item in self.projects if item["id"] == self.settings_project_id), None)
        if project is None:
            return
        window = self.settings_window
        if window is None:
            return
        if not messagebox.askyesno(
            "Төсөл устгах",
            f"«{project['name']}» төслийг устгах уу?",
            parent=window,
        ):
            return
        was_active = self.active_id == project["id"]
        self.projects = [item for item in self.projects if item["id"] != project["id"]]
        if was_active:
            self.active_id = self.projects[0]["id"] if self.projects else ""
            self.project_var.set(self.active_id)
            self.summary = self.summary_cache.get(self.active_id) if self.active_id else None
            self.loading = False
            self.refresh_project_menu()
            self.update_project_chrome()
            if self.summary is not None:
                self.render_summary()
            else:
                self.render_empty()
                self.updated_label.configure(text="Шинэчлэгдсэн: —")
        if not self.persist_config():
            messagebox.showerror("Тохиргоо", "Тохиргоог хадгалж чадсангүй.", parent=window)
        self.load_settings_projects(self.active_id)
        if was_active and self.active_id:
            active = self.current_project()
            if active is not None and active["apiKey"]:
                self.refresh()

    def dark_entry(self, parent: tk.Misc) -> tk.Entry:
        return tk.Entry(
            parent,
            bg=PANEL_ALT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            font=("Segoe UI", 10),
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )

    def save_settings(self, window: tk.Toplevel) -> None:
        name = self.settings_name.get().strip()
        clean_url = self.settings_url.get().strip().rstrip("/")
        clean_key = self.settings_key.get().strip()
        if not name:
            messagebox.showerror("Тохиргоо", "Төслийн нэр хоосон байна.", parent=window)
            return
        if len(name) > 60:
            messagebox.showerror("Тохиргоо", "Төслийн нэр 60 тэмдэгтээс урт байна.", parent=window)
            return
        parsed = urlparse(clean_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            messagebox.showerror("Тохиргоо", "API хаяг http:// эсвэл https://-ээр эхлэх ёстой.", parent=window)
            return
        if not clean_key:
            messagebox.showerror("Тохиргоо", "API түлхүүр хоосон байна.", parent=window)
            return
        duplicate = next(
            (
                item
                for item in self.projects
                if item["name"].casefold() == name.casefold() and item["id"] != self.settings_project_id
            ),
            None,
        )
        if duplicate is not None:
            messagebox.showerror("Тохиргоо", "Ийм нэртэй төсөл аль хэдийн байна.", parent=window)
            return

        project_id = self.settings_project_id or new_project_id()
        project = {"id": project_id, "name": name, "apiUrl": clean_url, "apiKey": clean_key}
        previous_projects = self.projects
        previous_active = self.active_id
        updated = list(self.projects)
        index = next((position for position, item in enumerate(updated) if item["id"] == project_id), None)
        if index is None:
            updated.append(project)
        else:
            updated[index] = project
        self.projects = updated
        self.active_id = project_id
        if not self.persist_config():
            self.projects = previous_projects
            self.active_id = previous_active
            messagebox.showerror("Тохиргоо", "Тохиргоог хадгалж чадсангүй.", parent=window)
            return

        self.config = {
            "projects": self.projects,
            "activeProjectId": self.active_id,
            "neon": self.neon,
            "vercel": self.vercel,
        }
        self.summary = self.summary_cache.get(project_id)
        self.loading = False
        self.project_var.set(project_id)
        self.refresh_project_menu()
        self.update_project_chrome()
        self.close_settings(window)
        if self.summary is not None:
            self.render_summary()
        else:
            self.render_empty()
            self.updated_label.configure(text="Шинэчлэгдсэн: —")
        self.refresh()

    def close_settings(self, window: tk.Toplevel) -> None:
        if self.settings_window is window:
            self.settings_window = None
            self.settings_project_id = None
        try:
            window.grab_release()
        except tk.TclError:
            pass
        window.destroy()

    def close(self) -> None:
        self.closed = True
        if self.auto_job is not None:
            try:
                self.root.after_cancel(self.auto_job)
            except tk.TclError:
                pass
        self.root.destroy()


def check_mode() -> int:
    config = load_config()
    project = active_project(config)
    if project is None:
        print("ERROR: Тохируулсан төсөл байхгүй.", file=sys.stderr)
        return 1
    try:
        data = fetch_summary(project["apiUrl"], project["apiKey"])
    except RevenueApiError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": data.get("ok"),
                "project": project["name"],
                "generatedAt": data.get("generatedAt"),
                "allTime": data.get("allTime"),
                "current": data.get("current"),
                "byCategory": data.get("byCategory"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    if "--check" in sys.argv:
        return check_mode()
    root = tk.Tk()
    RevenueApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

