"""
app.py — Główna klasa aplikacji BitrixApp.
"""
import json
import os
import re
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime, timezone, timedelta
from tkinter import messagebox, ttk

import io
import requests
from PIL import Image, ImageDraw, ImageTk

from config import (
    C, FONT_BODY, FONT_HEADING, FONT_MONO, FONT_SMALL, FONT_TITLE,
    STATUS_COLORS, STATUS_MAP, WEBHOOK_URL,
)
from card_view import TaskCardView
from helpers import (
    days_since, format_date, get_data_dir,
    parse_to_aware_datetime, seconds_to_readable,
)
from styles import ModernButton, ModernCheckbutton, apply_dark_style


class BitrixApp:
    """Główna aplikacja do zarządzania zadaniami Bitrix24."""

    # ── Kolumny tabel ─────────────────────────────────────────────────
    TASK_COLUMNS = (
        "ID", "TITLE", "REAL_STATUS", "TIME_SPENT",
        "CREATED_BY", "RESPONSIBLE", "PARTICIPANTS", "DEADLINE",
        "CREATED_DATE", "ACTIVITY_DATE", "CHANGED_DATE",
        "STATUS_CHANGED_DATE", "GROUP",
    )
    GROUP_COLUMNS = ("ID", "NAME", "DESCRIPTION", "OWNER_ID", "DATE_CREATE", "DATE_ACTIVITY")

    # ------------------------------------------------------------------
    # Inicjalizacja
    # ------------------------------------------------------------------

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Bitrix24 — Task Manager")
        self.root.geometry("1300x820")
        self.root.configure(bg=C["bg"])
        apply_dark_style(root)

        self.data_dir = get_data_dir()

        # Stan danych
        self.all_fetched_tasks:  list = []
        self.all_fetched_groups: list = []
        self.all_responsibles:   list = ["Wszyscy"]
        self.groups_map:  dict = {}
        self.users_map:   dict = {}
        self._photo_cache: dict = {}

        # Zmienne UI
        self.current_view         = tk.StringVar(value="tasks")
        self.current_filter       = tk.StringVar(value="W trakcie")
        self.current_resp_filter  = tk.StringVar(value="Wszyscy")
        self.search_var           = tk.StringVar()
        self.live_timer_var       = tk.BooleanVar(value=False)
        self.hide_inactive_var    = tk.BooleanVar(value=False)
        self.display_mode         = tk.StringVar(value=self._load_display_mode())

        # Stan sesji
        self.current_group_view_id   = None
        self.current_group_view_name = None
        self.is_fetching             = False
        self.active_tree_timers:     dict = {}
        self._card_mode              = False

        self._build_ui()
        self.load_local_data()
        self._run_live_timers()
        self._schedule_auto_refresh()

    # ==================================================================
    # Budowanie UI
    # ==================================================================

    def _build_ui(self) -> None:
        self._build_topbar()
        tk.Frame(self.root, bg=C["accent"], height=2).pack(fill="x")
        self._build_toolbar()
        self._build_count_bar()
        self._build_content_area()

    # ── Topbar ────────────────────────────────────────────────────────

    def _build_topbar(self) -> None:
        topbar     = tk.Frame(self.root, bg=C["header"], pady=0)
        topbar.pack(fill="x")
        logo_strip = tk.Frame(topbar, bg=C["header"])
        logo_strip.pack(fill="x")

        tk.Frame(logo_strip, bg=C["accent"], width=4).pack(side="left", fill="y", padx=(0, 12))
        tk.Label(logo_strip, text="BITRIX24", bg=C["header"], fg=C["accent"],
                 font=("Segoe UI Black", 16)).pack(side="left", pady=8)
        tk.Label(logo_strip, text="Task Manager", bg=C["header"], fg=C["text_muted"],
                 font=("Segoe UI Light", 12)).pack(side="left", padx=(6, 0), pady=8)

        self.status_var = tk.StringVar(value="")
        tk.Label(logo_strip, textvariable=self.status_var, bg=C["header"],
                 fg=C["accent"], font=("Segoe UI Italic", 9)).pack(side="right", padx=14)

    # ── Toolbar ───────────────────────────────────────────────────────

    def _build_toolbar(self) -> None:
        toolbar_container = tk.Frame(self.root, bg=C["sidebar"], pady=4)
        toolbar_container.pack(fill="x")

        # Wiersz 1 — akcje i przełącznik widoku
        row1 = tk.Frame(toolbar_container, bg=C["sidebar"])
        row1.pack(fill="x", padx=12, pady=2)
        self._build_toolbar_row1(row1)

        # Wiersz 2 — filtry
        row2 = tk.Frame(toolbar_container, bg=C["sidebar"])
        row2.pack(fill="x", padx=12, pady=2)
        self._build_toolbar_row2(row2)

    def _build_toolbar_row1(self, parent: tk.Frame) -> None:
        left = tk.Frame(parent, bg=C["sidebar"])
        left.pack(side="left")

        for val, lbl in [("tasks", "📋 Zadania"), ("groups", "🗂 Grupy")]:
            tk.Radiobutton(
                left, text=lbl, variable=self.current_view, value=val,
                command=self.switch_view,
                bg=C["sidebar"], fg=C["text"], selectcolor=C["accent"],
                activebackground=C["sidebar"], activeforeground=C["accent"],
                font=FONT_BODY, relief="flat", bd=0, cursor="hand2",
                indicatoron=False, padx=6, pady=4,
            ).pack(side="left", padx=1)

        tk.Frame(left, bg=C["card_border"], width=1).pack(side="left", fill="y", padx=6)

        self.btn_fetch = ModernButton(left, "⟳ Odśwież", command=self.fetch_data, color=C["btn_green"])
        self.btn_fetch.pack(side="left", padx=2)

        self.btn_action = ModernButton(left, "↗ Otwórz zadanie",
                                       command=self.handle_main_action, color=C["btn_blue"])
        self.btn_action.pack(side="left", padx=2)

        self.action_separator = tk.Frame(left, bg=C["card_border"], width=1)
        self.action_separator.pack(side="left", fill="y", padx=6)

        # Przełącznik Kafelki / Lista
        self.view_toggle_frame = tk.Frame(left, bg=C["sidebar"],
                                          highlightthickness=1,
                                          highlightbackground=C["card_border"])
        self.view_toggle_frame.pack(side="left", padx=2)

        self.btn_view_cards = self._toggle_btn(self.view_toggle_frame, "⊞ Kafelki", "cards")
        self.btn_view_list  = self._toggle_btn(self.view_toggle_frame, "☰ Lista",   "list")

        self.btn_view_cards.config(command=lambda: self._set_display_mode("cards"))
        self.btn_view_list.config(command=lambda:  self._set_display_mode("list"))

        self.btn_set_default = tk.Button(
            left, text="★ Domyślny",
            bg=C["sidebar"], fg=C["text_muted"],
            font=FONT_SMALL, relief="flat", bd=0, cursor="hand2",
            padx=6, pady=4,
            activebackground=C["tag_bg"], activeforeground=C["accent"],
            command=self._save_display_mode_as_default,
        )
        self.btn_set_default.pack(side="left", padx=(4, 0))

        # Zastosuj tryb z konfiguracji
        self._set_display_mode(self.display_mode.get())

    def _toggle_btn(self, parent: tk.Frame, text: str, mode_val: str) -> tk.Button:
        is_active = self.display_mode.get() == mode_val
        btn = tk.Button(
            parent, text=text,
            bg=C["accent"] if is_active else C["sidebar"],
            fg="#000"       if is_active else C["text_muted"],
            font=FONT_SMALL, relief="flat", bd=0, cursor="hand2",
            padx=8, pady=4,
            activebackground=C["accent"], activeforeground="#000",
        )
        btn.pack(side="left")
        return btn

    def _set_display_mode(self, mode: str) -> None:
        self.display_mode.set(mode)
        self.btn_view_cards.config(
            bg=C["accent"] if mode == "cards" else C["sidebar"],
            fg="#000"       if mode == "cards" else C["text_muted"],
        )
        self.btn_view_list.config(
            bg=C["accent"] if mode == "list" else C["sidebar"],
            fg="#000"       if mode == "list" else C["text_muted"],
        )

        if mode == "cards":
            self.btn_action.pack_forget()
            self.action_separator.pack_forget()
            if hasattr(self, "chk_live_timer"):
                self.chk_live_timer.pack_forget()
                self.chk_hide_inactive.pack_forget()
        else:
            self.btn_action.pack(side="left", padx=2, after=self.btn_fetch)
            self.action_separator.pack(side="left", fill="y", padx=6, after=self.btn_action)
            if hasattr(self, "chk_live_timer"):
                self.chk_live_timer.pack(side="left", padx=6)
                self.chk_hide_inactive.pack(side="left", padx=6)

        if hasattr(self, "tree_frame"):
            self.apply_filter()

    def _build_toolbar_row2(self, parent: tk.Frame) -> None:
        right = tk.Frame(parent, bg=C["sidebar"])
        right.pack(side="left")

        self.chk_live_timer = ModernCheckbutton(right, "⏱ Licz czas na żywo",
                                                variable=self.live_timer_var, command=self.apply_filter)
        self.chk_live_timer.pack(side="left", padx=4)

        self.chk_hide_inactive = ModernCheckbutton(right, "🔕 Ukryj nieaktywne >7d",
                                                   variable=self.hide_inactive_var, command=self.apply_filter)
        self.chk_hide_inactive.pack(side="left", padx=4)

        tk.Frame(right, bg=C["card_border"], width=1).pack(side="left", fill="y", padx=6)

        self.filter_frame = tk.Frame(right, bg=C["sidebar"])
        self.filter_frame.pack(side="left")

        self._lbl(self.filter_frame, "Status:").pack(side="left", padx=(0, 2))
        self.status_combobox = ttk.Combobox(
            self.filter_frame, textvariable=self.current_filter,
            values=["Wszystkie"] + list(STATUS_MAP.values()),
            state="readonly", width=12,
        )
        self.status_combobox.pack(side="left", padx=(0, 6))
        self.status_combobox.bind("<<ComboboxSelected>>", self.on_status_change)

        self._lbl(self.filter_frame, "Pracownik:").pack(side="left", padx=(0, 2))
        self.resp_combobox = ttk.Combobox(
            self.filter_frame, textvariable=self.current_resp_filter,
            values=["Wszyscy"], width=16,
        )
        self.resp_combobox.pack(side="left", padx=(0, 6))
        self.resp_combobox.bind("<<ComboboxSelected>>", self.apply_filter)
        self.resp_combobox.bind("<KeyRelease>",          self.on_resp_type)

        self._lbl(self.filter_frame, "🔍").pack(side="left", padx=(0, 2))
        self.search_entry = tk.Entry(
            self.filter_frame, textvariable=self.search_var,
            bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
            relief="flat", font=FONT_BODY, width=20,
            highlightthickness=1, highlightbackground=C["input_border"],
            highlightcolor=C["accent"],
        )
        self.search_entry.pack(side="left")
        self.search_entry.bind("<KeyRelease>", self.apply_filter)

        tk.Button(
            self.filter_frame, text="✖ Reset",
            bg=C["sidebar"], fg=C["text_muted"],
            font=FONT_SMALL, relief="flat", bd=0, cursor="hand2",
            padx=8, pady=2,
            activebackground=C["btn_red"], activeforeground="#FFF",
            command=self.reset_filters,
        ).pack(side="left", padx=(8, 0))

    # ── Pasek licznika ────────────────────────────────────────────────

    def _build_count_bar(self) -> None:
        count_bar = tk.Frame(self.root, bg=C["bg"], pady=4)
        count_bar.pack(fill="x")

        self.count_var = tk.StringVar(value="")
        tk.Label(count_bar, textvariable=self.count_var, bg=C["bg"],
                 fg=C["text_muted"], font=FONT_SMALL).pack(side="left", padx=14)

        self.view_label_var = tk.StringVar(value="")
        tk.Label(count_bar, textvariable=self.view_label_var, bg=C["bg"],
                 fg=C["accent2"], font=("Segoe UI Semibold", 9)).pack(side="right", padx=14)

    # ── Obszar treści ─────────────────────────────────────────────────

    def _build_content_area(self) -> None:
        self.content_frame = tk.Frame(self.root, bg=C["bg"])
        self.content_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Treeview
        self.tree_frame = tk.Frame(self.content_frame, bg=C["bg"])
        self.tree_frame.pack(fill="both", expand=True)

        tree_scroll   = ttk.Scrollbar(self.tree_frame, orient="vertical")
        tree_scroll.pack(side="right", fill="y")
        tree_scroll_x = ttk.Scrollbar(self.tree_frame, orient="horizontal")
        tree_scroll_x.pack(side="bottom", fill="x")

        self.tree = ttk.Treeview(
            self.tree_frame, columns=self.TASK_COLUMNS, show="headings",
            yscrollcommand=tree_scroll.set,
            xscrollcommand=tree_scroll_x.set,
            style="Treeview",
        )
        tree_scroll.config(command=self.tree.yview)
        tree_scroll_x.config(command=self.tree.xview)

        for col in self.TASK_COLUMNS:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_treeview(c, False))
            self.tree.column(col, width=100)
        self.tree.pack(side="left", fill="both", expand=True)

        # Kafelki
        self.card_view = TaskCardView(self.content_frame, app=self, on_open_cb=self._open_task_by_id)

    # ==================================================================
    # Helpers UI
    # ==================================================================

    def _lbl(self, parent, text: str) -> tk.Label:
        return tk.Label(parent, text=text, bg=C["sidebar"], fg=C["text_muted"], font=FONT_SMALL)

    def _show_cards(self, tasks: list) -> None:
        self._card_mode = True
        self.tree_frame.pack_forget()
        self.card_view.pack(fill="both", expand=True)
        self.card_view.load_tasks(tasks)
        self.count_var.set(f"{len(tasks)} zadań")

    def _show_tree(self) -> None:
        self._card_mode = False
        self.card_view.pack_forget()
        self.tree_frame.pack(fill="both", expand=True)

    # ==================================================================
    # Dane lokalne
    # ==================================================================

    def load_local_data(self) -> None:
        groups_path = os.path.join(self.data_dir, "groups_list.json")
        if os.path.exists(groups_path):
            try:
                with open(groups_path, "r", encoding="utf-8") as f:
                    self.all_fetched_groups = json.load(f)
                self.build_groups_map()
            except Exception:
                pass

        self.load_tasks_from_file_based_on_filter()

        users_path = os.path.join(self.data_dir, "users_list.json")
        if os.path.exists(users_path):
            try:
                with open(users_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # Obsługa starszego formatu {uid: "name"}
                if loaded and isinstance(list(loaded.values())[0], str):
                    self.users_map = {k: {"name": v, "photo": None} for k, v in loaded.items()}
                else:
                    self.users_map = loaded
            except Exception:
                self.fetch_all_users()
        else:
            self.fetch_all_users()

        self.switch_view()

    def load_tasks_from_file_based_on_filter(self) -> None:
        selected = self.current_filter.get()
        fname    = "tasks_in_progress.json" if selected == "W trakcie" else "tasks_list.json"
        fpath    = os.path.join(self.data_dir, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    self.all_fetched_tasks = json.load(f)
                self.update_resp_filter_options()
            except Exception as e:
                print(f"Nie udało się wczytać: {e}")
                self.all_fetched_tasks = []
        else:
            self.all_fetched_tasks = []

    def build_groups_map(self) -> None:
        self.groups_map = {str(g.get("ID")): g.get("NAME") for g in self.all_fetched_groups}

    # ==================================================================
    # Pobieranie użytkowników / awatarów
    # ==================================================================

    def fetch_all_users(self) -> None:
        full_url  = f"{WEBHOOK_URL}user.get.json"
        all_users: dict = {}
        start     = 0
        try:
            while True:
                resp = requests.get(f"{full_url}?start={start}", timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if "result" not in data:
                    break
                for u in data["result"]:
                    uid = str(u.get("ID"))
                    all_users[uid] = {
                        "name":  f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip(),
                        "photo": u.get("PERSONAL_PHOTO"),
                    }
                if "next" in data:
                    start = data["next"]
                else:
                    break
            self.users_map = all_users
            with open(os.path.join(self.data_dir, "users_list.json"), "w", encoding="utf-8") as f:
                json.dump(all_users, f, ensure_ascii=False, indent=4)
        except requests.exceptions.RequestException as e:
            print(f"Błąd pobierania użytkowników: {e}")

    def get_user_avatar(self, uid: str, url: str, size: int = 20):
        """Zwraca okrągłe zdjęcie profilowe jako PhotoImage lub None."""
        if not url:
            return None
        cache_key = f"{uid}_{size}"
        if cache_key in self._photo_cache:
            return self._photo_cache[cache_key]

        local_path = os.path.join(self.data_dir, "photos", f"{uid}.png")
        try:
            if os.path.exists(local_path):
                img = Image.open(local_path)
            else:
                r   = requests.get(url, timeout=3)
                img = Image.open(io.BytesIO(r.content))
                img.save(local_path)

            img    = img.resize((size, size), Image.Resampling.LANCZOS)
            mask   = Image.new("L", (size, size), 0)
            draw   = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, size, size), fill=255)
            output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            output.paste(img, (0, 0), mask)

            photo = ImageTk.PhotoImage(output)
            self._photo_cache[cache_key] = photo
            return photo
        except Exception:
            return None

    # ==================================================================
    # Pobieranie danych z API
    # ==================================================================

    def fetch_data(self, is_auto: bool = False) -> None:
        if self.is_fetching:
            return
        mode             = self.current_view.get()
        self.is_fetching = True
        self._toggle_buttons_state("disabled")

        if mode == "tasks":
            if not is_auto:
                self.current_group_view_id   = None
                self.current_group_view_name = None
            self.status_var.set("Automatyczne odświeżanie..." if is_auto else "Pobieranie zadań...")
            threading.Thread(target=self._bg_fetch_all_tasks, args=(is_auto,), daemon=True).start()
        elif mode == "groups":
            self.status_var.set("Pobieranie grup...")
            threading.Thread(target=self._bg_fetch_all_groups, args=(is_auto,), daemon=True).start()

    def _bg_fetch_all_tasks(self, is_auto: bool = False) -> None:
        if self.current_filter.get() == "W trakcie":
            self._fetch_in_progress_tasks(is_auto)
        else:
            self._fetch_standard_tasks(is_auto)

    def _fetch_in_progress_tasks(self, is_auto: bool) -> None:
        full_url  = f"{WEBHOOK_URL}tasks.task.list"
        all_tasks: list = []
        start     = 0
        date_str  = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00+01:00")
        try:
            while True:
                params = {
                    "filter[REAL_STATUS]":      3,
                    "filter[>=ACTIVITY_DATE]":  date_str,
                    "start":                    start,
                }
                resp = requests.get(full_url, params=params, timeout=10)
                resp.raise_for_status()
                data  = resp.json()
                tasks = data.get("result", {}).get("tasks", [])
                if not tasks:
                    break
                all_tasks.extend(tasks)
                self.root.after(0, lambda n=len(all_tasks): self.status_var.set(f"Pobrano {n} zadań 'W trakcie'..."))
                if "next" in data:
                    start = data["next"]
                else:
                    break
            with open(os.path.join(self.data_dir, "tasks_in_progress.json"), "w", encoding="utf-8") as f:
                json.dump(all_tasks, f, ensure_ascii=False, indent=4)
            self.root.after(0, self._on_fetch_tasks_success, all_tasks, is_auto)
        except requests.exceptions.RequestException as e:
            self.root.after(0, self._on_fetch_error, e, "zadań 'W trakcie'")

    def _fetch_standard_tasks(self, is_auto: bool) -> None:
        full_url  = f"{WEBHOOK_URL}task.item.list.json"
        all_tasks: list = []
        start     = 0
        try:
            while True:
                resp = requests.get(f"{full_url}?start={start}", timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if "result" not in data:
                    break
                all_tasks.extend(data["result"])
                self.root.after(0, lambda n=len(all_tasks): self.status_var.set(f"Pobrano {n} zadań..."))
                if "next" in data:
                    start = data["next"]
                else:
                    break
            with open(os.path.join(self.data_dir, "tasks_list.json"), "w", encoding="utf-8") as f:
                json.dump(all_tasks, f, ensure_ascii=False, indent=4)
            self.root.after(0, self._on_fetch_tasks_success, all_tasks, is_auto)
        except requests.exceptions.RequestException as e:
            self.root.after(0, self._on_fetch_error, e, "zadań")

    def _bg_fetch_all_groups(self, is_auto: bool = False) -> None:
        full_url   = f"{WEBHOOK_URL}sonet_group.get.json"
        all_groups: list = []
        start      = 0
        try:
            while True:
                resp = requests.get(f"{full_url}?start={start}", timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if "result" not in data:
                    break
                all_groups.extend(data["result"])
                self.root.after(0, lambda n=len(all_groups): self.status_var.set(f"Pobrano {n} grup..."))
                if "next" in data:
                    start = data["next"]
                else:
                    break
            with open(os.path.join(self.data_dir, "groups_list.json"), "w", encoding="utf-8") as f:
                json.dump(all_groups, f, ensure_ascii=False, indent=4)
            self.root.after(0, self._on_fetch_groups_success, all_groups, is_auto)
        except requests.exceptions.RequestException as e:
            self.root.after(0, self._on_fetch_error, e, "grup")

    def _bg_filter_tasks_by_group(self, group_id: str, group_name: str, is_auto: bool = False) -> None:
        full_url    = f"{WEBHOOK_URL}tasks.task.list.json?filter[GROUP_ID]={group_id}"
        group_tasks: list = []
        start       = 0
        try:
            while True:
                resp = requests.get(f"{full_url}&start={start}", timeout=10)
                resp.raise_for_status()
                data  = resp.json()
                tasks = data.get("result", {}).get("tasks", [])
                if not tasks:
                    break
                group_tasks.extend(tasks)
                self.root.after(0, lambda n=len(group_tasks): self.status_var.set(f"Pobrano {n} zadań grupy..."))
                if "next" in data:
                    start = data["next"]
                else:
                    break
            self.root.after(0, self._on_filter_tasks_success, group_tasks, group_name, is_auto)
        except Exception as e:
            self.root.after(0, self._on_filter_tasks_error, e, group_name)

    # ── Callbacki zakończenia pobierania ──────────────────────────────

    def _on_fetch_tasks_success(self, all_tasks: list, is_auto: bool = False) -> None:
        self.all_fetched_tasks = all_tasks
        self.update_resp_filter_options()
        self.apply_filter()
        if is_auto:
            self._reset_fetch_status(f"Odświeżono ({datetime.now().strftime('%H:%M')}).")
        else:
            self._reset_fetch_status("Pobrano zadania.")
            messagebox.showinfo("Sukces", "Zakończono pobieranie.")

    def _on_fetch_groups_success(self, all_groups: list, is_auto: bool = False) -> None:
        self.all_fetched_groups = all_groups
        self.build_groups_map()
        self.display_groups(all_groups)
        if is_auto:
            self._reset_fetch_status(f"Odświeżono ({datetime.now().strftime('%H:%M')}).")
        else:
            self._reset_fetch_status("Pobrano grupy.")
            messagebox.showinfo("Sukces", "Pobrano i zapisano grupy robocze.")

    def _on_filter_tasks_success(self, group_tasks: list, group_name: str, is_auto: bool = False) -> None:
        if not is_auto and not group_tasks:
            self._reset_fetch_status("Zakończono pobieranie.")
            messagebox.showinfo("Informacja", f"Brak zadań w grupie: {group_name}")
            return
        self.all_fetched_tasks = group_tasks
        self.current_view.set("tasks")
        self.switch_view()
        self.update_resp_filter_options()
        self.apply_filter()
        if is_auto:
            self._reset_fetch_status(f"Odświeżono ({datetime.now().strftime('%H:%M')}).")
        else:
            self._reset_fetch_status("Pobrano zadania grupy.")
            messagebox.showinfo("Sukces", f"Wyświetlono zadania: {group_name}")

    def _on_filter_tasks_error(self, e, group_name: str) -> None:
        self._reset_fetch_status("Błąd pobierania.", success=False)
        messagebox.showerror("Błąd", f"Nie udało się pobrać zadań {group_name}:\n{str(e)}")

    def _on_fetch_error(self, e, category: str) -> None:
        self._reset_fetch_status("Błąd pobierania.", success=False)
        messagebox.showwarning("Tryb Offline",
                               f"Nie udało się pobrać {category}.\nPrzeglądasz dane lokalne.\nBłąd: {e}")

    # ==================================================================
    # Zarządzanie stanem UI (przyciski, status)
    # ==================================================================

    def _toggle_buttons_state(self, state: str) -> None:
        self.btn_fetch.config(state=state)
        try:
            self.btn_action.config(state=state)
        except Exception:
            pass
        self.btn_view_cards.config(state=state)
        self.btn_view_list.config(state=state)
        self.btn_set_default.config(state=state)

    def _reset_fetch_status(self, message: str, success: bool = True) -> None:
        self.is_fetching = False
        self._toggle_buttons_state("normal")
        self.status_var.set(message)
        self.root.after(4000, lambda: self.status_var.set(""))

    def _schedule_auto_refresh(self) -> None:
        self.root.after(300_000, self._auto_refresh_trigger)

    def _auto_refresh_trigger(self) -> None:
        if not self.is_fetching:
            mode = self.current_view.get()
            if mode == "tasks" and self.current_group_view_id:
                self.is_fetching = True
                self._toggle_buttons_state("disabled")
                self.status_var.set("Automatyczne odświeżanie grupy...")
                threading.Thread(
                    target=self._bg_filter_tasks_by_group,
                    args=(self.current_group_view_id, self.current_group_view_name, True),
                    daemon=True,
                ).start()
            else:
                self.fetch_data(is_auto=True)
        self._schedule_auto_refresh()

    # ==================================================================
    # Konfiguracja trybu widoku
    # ==================================================================

    def _config_path(self) -> str:
        return os.path.join(self.data_dir, "ui_config.json")

    def _load_display_mode(self) -> str:
        try:
            p = os.path.join(get_data_dir(), "ui_config.json")
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f).get("display_mode", "cards")
        except Exception:
            pass
        return "cards"

    def _save_display_mode_as_default(self) -> None:
        try:
            p   = self._config_path()
            cfg = {}
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            cfg["display_mode"] = self.display_mode.get()
            with open(p, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            self.btn_set_default.config(text="✓ Zapisano!", fg=C["btn_green"])
            self.root.after(2000, lambda: self.btn_set_default.config(text="★ Domyślny", fg=C["text_muted"]))
        except Exception as e:
            messagebox.showerror("Błąd", f"Nie udało się zapisać konfiguracji:\n{e}")

    # ==================================================================
    # Przełączanie widoków
    # ==================================================================

    def switch_view(self) -> None:
        mode = self.current_view.get()
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.active_tree_timers.clear()

        if mode == "tasks":
            self.btn_fetch.config(text="⟳  Odśwież")
            self.filter_frame.pack(side="left")
            self.tree.config(columns=self.TASK_COLUMNS)
            for col in self.TASK_COLUMNS:
                self.tree.heading(col, text=col, command=lambda c=col: self.sort_treeview(c, False))
            self.view_toggle_frame.pack(side="left", padx=2)
            self.btn_set_default.pack(side="left", padx=(4, 0))
            if self.display_mode.get() == "cards":
                self.btn_action.pack_forget()
                self.action_separator.pack_forget()
            else:
                self.btn_action.pack(side="left", padx=2, after=self.btn_fetch)
                self.action_separator.pack(side="left", fill="y", padx=6, after=self.btn_action)
            self.apply_filter()

        elif mode == "groups":
            self.btn_fetch.config(text="⟳  Odśwież grupy")
            self.view_toggle_frame.pack_forget()
            self.btn_set_default.pack_forget()
            self.btn_action.config(text="↗  Otwórz / Filtruj zadania")
            self.btn_action.pack(side="left", padx=2, after=self.btn_fetch)
            self.action_separator.pack(side="left", fill="y", padx=6, after=self.btn_action)
            self.filter_frame.pack_forget()
            if self._card_mode:
                self._show_tree()
            self.tree.config(columns=self.GROUP_COLUMNS)
            for col in self.GROUP_COLUMNS:
                self.tree.heading(col, text=col, command=lambda c=col: self.sort_treeview(c, False))
            self.display_groups(self.all_fetched_groups)

    def display_groups(self, groups: list) -> None:
        if self.current_view.get() != "groups":
            return
        if self._card_mode:
            self._show_tree()
        selected_ids = [self.tree.item(i, "values")[0] for i in self.tree.selection()]
        for row in self.tree.get_children():
            self.tree.delete(row)
        for group in groups:
            self.tree.insert("", "end", values=(
                group.get("ID"), group.get("NAME"), group.get("DESCRIPTION"),
                group.get("OWNER_ID"),
                format_date(group.get("DATE_CREATE")),
                format_date(group.get("DATE_ACTIVITY")),
            ))
        for item in self.tree.get_children():
            if self.tree.item(item, "values")[0] in selected_ids:
                self.tree.selection_add(item)
        self.sort_treeview("DATE_ACTIVITY", reverse=True)
        self.auto_fit_columns()
        self.count_var.set(f"{len(groups)} grup")
        self.view_label_var.set("Widok: Grupy robocze")

    # ==================================================================
    # Filtry
    # ==================================================================

    def on_status_change(self, _event=None) -> None:
        if self.current_group_view_id is None:
            self.load_tasks_from_file_based_on_filter()
        self.apply_filter()

    def on_resp_type(self, event) -> None:
        if event.keysym in ("Up", "Down", "Left", "Right", "Return", "Tab"):
            return
        typed = self.current_resp_filter.get().lower()
        self.resp_combobox.config(
            values=self.all_responsibles if not typed
            else [n for n in self.all_responsibles if typed in n.lower()]
        )
        self.apply_filter()

    def update_resp_filter_options(self) -> None:
        workers: set = set()
        for task in self.all_fetched_tasks:
            resp = f"{task.get('RESPONSIBLE_NAME', '')} {task.get('RESPONSIBLE_LAST_NAME', '')}".strip()
            if not resp and "responsible" in task:
                r    = task["responsible"]
                resp = f"{r.get('name', '')} {r.get('lastName', '')}".strip()
            if resp:
                workers.add(resp)
            creator = f"{task.get('CREATED_BY_NAME', '')} {task.get('CREATED_BY_LAST_NAME', '')}".strip()
            if not creator and "creator" in task:
                creator = f"{task['creator'].get('name', '')} {task['creator'].get('lastName', '')}".strip()
            if creator:
                workers.add(creator)
            for p in self._extract_participants(task):
                workers.add(p)
        self.all_responsibles = ["Wszyscy"] + sorted(workers)
        self.resp_combobox.config(values=self.all_responsibles)
        self.current_resp_filter.set("Wszyscy")

    def apply_filter(self, _event=None) -> None:
        if self.current_view.get() != "tasks":
            return
        selected_status  = self.current_filter.get()
        typed_worker     = self.current_resp_filter.get().strip().lower()
        search_term      = self.search_var.get().strip().lower()
        hide_inactive    = self.hide_inactive_var.get()
        threshold_date   = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")

        filtered: list = []
        for task in self.all_fetched_tasks:
            real_status = str(task.get("REAL_STATUS") or task.get("status", ""))
            mapped      = STATUS_MAP.get(real_status, real_status)
            resp        = f"{task.get('RESPONSIBLE_NAME', '')}{task.get('RESPONSIBLE_LAST_NAME', '')}".strip()
            if not resp and "responsible" in task:
                r    = task["responsible"]
                resp = f"{r.get('name', '')}{r.get('lastName', '')}".strip()
            creator = f"{task.get('CREATED_BY_NAME', '')}{task.get('CREATED_BY_LAST_NAME', '')}".strip()
            if not creator and "creator" in task:
                creator = f"{task['creator'].get('name', '')}{task['creator'].get('lastName', '')}".strip()
            participants = " ".join(self._extract_participants(task))
            worker_pool  = f"{resp} {creator} {participants}".lower()
            task_title   = (task.get("TITLE") or task.get("title", "")).lower()
            activity_str = format_date(task.get("ACTIVITY_DATE") or task.get("activityDate") or "")

            ok_status   = selected_status == "Wszystkie" or mapped == selected_status
            ok_title    = not search_term or search_term in task_title
            ok_worker   = typed_worker in ("wszyscy", "") or typed_worker in worker_pool
            ok_activity = not (hide_inactive and real_status == "3" and
                               (not activity_str or activity_str < threshold_date))

            if ok_status and ok_worker and ok_title and ok_activity:
                filtered.append(task)

        mode = self.display_mode.get()
        if mode == "cards":
            self.view_label_var.set(f"⊞ Kafelki — {selected_status}")
            self._show_cards(filtered)
        else:
            self.view_label_var.set(f"☰ Lista — {selected_status}")
            if self._card_mode:
                self._show_tree()
            self.display_data(filtered)

    def reset_filters(self) -> None:
        self.current_group_view_id   = None
        self.current_group_view_name = None
        self.current_filter.set("W trakcie")
        self.current_resp_filter.set("Wszyscy")
        self.search_var.set("")
        self.live_timer_var.set(False)
        self.hide_inactive_var.set(False)
        self.load_tasks_from_file_based_on_filter()
        self.apply_filter()
        self.status_var.set("Zresetowano filtry i widok grupy.")

    # ==================================================================
    # Wyświetlanie danych w Treeview
    # ==================================================================

    def display_data(self, tasks: list) -> None:
        selected_ids = [self.tree.item(i, "values")[0] for i in self.tree.selection()]
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.active_tree_timers.clear()

        for task in tasks:
            t_id        = task.get("ID") or task.get("id")
            title       = task.get("TITLE") or task.get("title")
            r_s         = str(task.get("REAL_STATUS") or task.get("status", ""))
            status_txt  = STATUS_MAP.get(r_s, r_s)
            raw_time    = task.get("TIME_SPENT_IN_LOGS") or task.get("timeSpentInLogs")
            try:
                base_time = int(raw_time) if raw_time not in (None, "None", "null", "") else 0
            except (TypeError, ValueError):
                base_time = 0

            creator = f"{task.get('CREATED_BY_NAME', '')}{task.get('CREATED_BY_LAST_NAME', '')}".strip()
            if not creator and "creator" in task:
                creator = f"{task['creator'].get('name', '')}{task['creator'].get('lastName', '')}".strip()
            resp = f"{task.get('RESPONSIBLE_NAME', '')}{task.get('RESPONSIBLE_LAST_NAME', '')}".strip()
            if not resp and "responsible" in task:
                resp = f"{task['responsible'].get('name', '')}{task['responsible'].get('lastName', '')}".strip()

            deadline      = format_date(task.get("DEADLINE") or task.get("deadline"))
            created       = format_date(task.get("CREATED_DATE") or task.get("createdDate"))
            changed       = format_date(task.get("CHANGED_DATE") or task.get("changedDate"))
            status_chgd   = format_date(task.get("STATUS_CHANGED_DATE") or task.get("statusChangedDate"))
            g_id          = str(task.get("GROUP_ID") or task.get("groupId") or "")
            group_name    = self.groups_map.get(g_id, g_id) if g_id else ""
            raw_act       = task.get("ACTIVITY_DATE") or task.get("activityDate")
            activity_date = format_date(raw_act)
            participants  = ", ".join(self._extract_participants(task))

            item_id = self.tree.insert("", "end", values=(
                t_id, title, status_txt, seconds_to_readable(base_time),
                creator, resp, participants, deadline, created,
                activity_date, changed, status_chgd, group_name,
            ))

            if self.live_timer_var.get() and r_s == "3":
                act_dt = parse_to_aware_datetime(raw_act)
                if act_dt and act_dt.date() == datetime.now(timezone(timedelta(hours=1))).date():
                    self.active_tree_timers[item_id] = {"base_time": base_time, "activity_dt": act_dt}

        for item in self.tree.get_children():
            if self.tree.item(item, "values")[0] in selected_ids:
                self.tree.selection_add(item)

        self.sort_treeview("ACTIVITY_DATE", reverse=True)
        self.auto_fit_columns()
        self.count_var.set(f"{len(tasks)} zadań")

    def _run_live_timers(self) -> None:
        if self.current_view.get() == "tasks" and self.live_timer_var.get():
            now = datetime.now(timezone.utc)
            for item_id, data in self.active_tree_timers.items():
                if self.tree.exists(item_id):
                    elapsed = (now - data["activity_dt"]).total_seconds()
                    if elapsed > 0:
                        total = data["base_time"] + int(elapsed)
                        vals  = list(self.tree.item(item_id, "values"))
                        if vals:
                            vals[3] = seconds_to_readable(total)
                            self.tree.item(item_id, values=vals)
        self.root.after(1000, self._run_live_timers)

    # ==================================================================
    # Sortowanie Treeview
    # ==================================================================

    def sort_treeview(self, col: str, reverse: bool) -> None:
        data = [(self.tree.set(child, col), child) for child in self.tree.get_children("")]

        def _key(item):
            val = item[0]
            if not val:
                return (4 if reverse else 0, "")
            if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", val):
                return (1, val)
            try:
                if col == "TIME_SPENT" and val.count(":") == 2:
                    h, m, s = val.split(":")
                    return (2, int(h) * 3600 + int(m) * 60 + int(s))
                return (2, float(val))
            except ValueError:
                return (3, val.lower())

        data.sort(key=_key, reverse=reverse)
        for index, (_, child) in enumerate(data):
            self.tree.move(child, "", index)
        self.tree.heading(col, command=lambda c=col: self.sort_treeview(c, not reverse))

    def auto_fit_columns(self) -> None:
        font = tkfont.nametofont("TkDefaultFont")
        for col in self.tree["columns"]:
            max_w = font.measure(col) + 30
            for item in self.tree.get_children():
                val = self.tree.set(item, col)
                if val:
                    w = font.measure(str(val)) + 30
                    if w > max_w:
                        max_w = w
            if col in ("TITLE", "NAME", "DESCRIPTION", "GROUP"):
                max_w = min(max_w, 500)
                self.tree.column(col, width=max_w, minwidth=max_w, stretch=True)
            else:
                max_w = min(max_w, 250)
                self.tree.column(col, width=max_w, minwidth=max_w, stretch=False)

    # ==================================================================
    # Obsługa akcji (otwieranie zadań, grup)
    # ==================================================================

    def handle_main_action(self) -> None:
        if self.current_view.get() == "tasks":
            if self._card_mode:
                messagebox.showinfo("Info", "Kliknij kafelek zadania, aby je otworzyć.")
            else:
                self.open_task()
        elif self.current_view.get() == "groups":
            self.filter_tasks_by_group()

    def open_task(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Uwaga", "Proszę wybrać zadanie z tabeli.")
            return
        task_id = self.tree.item(selected[0], "values")[0]
        self._open_task_direct(task_id)

    def filter_tasks_by_group(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Uwaga", "Proszę wybrać grupę z tabeli.")
            return
        if self.is_fetching:
            return
        vals                         = self.tree.item(selected[0], "values")
        self.current_group_view_id   = vals[0]
        self.current_group_view_name = vals[1]
        self.is_fetching             = True
        self._toggle_buttons_state("disabled")
        self.status_var.set(f"Pobieranie zadań: {vals[1]}...")
        threading.Thread(
            target=self._bg_filter_tasks_by_group,
            args=(vals[0], vals[1]),
            daemon=True,
        ).start()

    def _open_task_by_id(self, task_id: str) -> None:
        self._open_task_direct(task_id)

    def _open_task_direct(self, task_id: str) -> None:
        task_file  = os.path.join(self.data_dir, "details", f"task_{task_id}.json")
        task_data  = {}
        try:
            resp = requests.get(f"{WEBHOOK_URL}tasks.task.get?taskId={task_id}", timeout=5)
            resp.raise_for_status()
            task_data = resp.json().get("result", {}).get("task", {})
            if task_data:
                with open(task_file, "w", encoding="utf-8") as f:
                    json.dump(task_data, f, ensure_ascii=False, indent=4)
        except Exception:
            if os.path.exists(task_file):
                with open(task_file, "r", encoding="utf-8") as f:
                    task_data = json.load(f)
            else:
                messagebox.showerror("Błąd", "Brak internetu i brak lokalnej kopii zadania.")
                return

        chat_id       = task_data.get("chatId") or task_data.get("CHAT_ID")
        chat_file     = os.path.join(self.data_dir, "chats", f"chat_{chat_id}.json") if chat_id else None
        local_messages: list = []
        if chat_file and os.path.exists(chat_file):
            try:
                with open(chat_file, "r", encoding="utf-8") as f:
                    local_messages = json.load(f)
            except Exception:
                pass

        self._check_and_fetch_missing_users(task_data, local_messages)
        top_window = self.create_task_window()
        self._build_task_window_ui(top_window, task_data, local_messages, chat_id)

        if chat_id:
            threading.Thread(
                target=self.bg_fetch_messages,
                args=(task_data, chat_id, chat_file, top_window),
                daemon=True,
            ).start()

    # ==================================================================
    # Okno zadania
    # ==================================================================

    def create_task_window(self) -> tk.Toplevel:
        top = tk.Toplevel(self.root)
        top.geometry("960x760")
        top.configure(bg=C["bg"])
        top.current_cycle = 0
        return top

    def reload_task_window(self, window: tk.Toplevel, task_data: dict,
                           messages: list, chat_id) -> None:
        if not window.winfo_exists():
            return
        window.current_cycle += 1
        for widget in window.winfo_children():
            widget.destroy()
        self._build_task_window_ui(window, task_data, messages, chat_id)

    def _build_task_window_ui(self, window: tk.Toplevel, task_data: dict,
                              messages: list, chat_id) -> None:
        t_id  = task_data.get("id", "")
        title = task_data.get("title", "")
        window.title(f"#{t_id} — {title}")

        # Header
        header = tk.Frame(window, bg=C["sidebar"], pady=10, padx=14)
        header.pack(fill="x")
        tk.Frame(header, bg=STATUS_COLORS.get("W trakcie", C["accent"]), width=4).pack(
            side="left", fill="y", padx=(0, 12))
        tk.Label(header, text=f"#{t_id}", bg=C["sidebar"], fg=C["text_muted"], font=FONT_SMALL).pack(anchor="w")
        tk.Label(header, text=title, bg=C["sidebar"], fg=C["text"], font=FONT_HEADING,
                 wraplength=800, justify="left").pack(anchor="w")
        tk.Frame(window, bg=C["accent"], height=2).pack(fill="x")

        main = tk.Frame(window, bg=C["bg"], padx=14, pady=12)
        main.pack(fill="both", expand=True)

        # Opis
        tk.Label(main, text="Opis zadania", bg=C["bg"], fg=C["accent2"], font=FONT_TITLE).pack(anchor="w")
        desc_bg = tk.Frame(main, bg=C["card"], padx=10, pady=8,
                           highlightthickness=1, highlightbackground=C["card_border"])
        desc_bg.pack(fill="both", expand=True, pady=(4, 12))
        desc_scroll = ttk.Scrollbar(desc_bg, orient="vertical")
        desc_scroll.pack(side="right", fill="y")
        desc_text = tk.Text(desc_bg, height=12, wrap="word", yscrollcommand=desc_scroll.set,
                            bg=C["card"], fg=C["text"], font=FONT_BODY, bd=0,
                            relief="flat", insertbackground=C["text"])
        desc_text.insert("1.0", task_data.get("description", "Brak opisu."))
        desc_text.config(state="disabled")
        desc_text.pack(side="left", fill="both", expand=True)
        desc_scroll.config(command=desc_text.yview)

        # Sekcja czasu pracy
        self._build_time_section(main, task_data, messages, window)

        # Chat
        self._build_chat_section(main, messages, chat_id, window)

    def _build_time_section(self, parent: tk.Frame, task_data: dict,
                            messages: list, window: tk.Toplevel) -> None:
        time_lf = tk.LabelFrame(parent, text=" ⏱  Raport czasu pracy ",
                                bg=C["bg"], fg=C["accent"], font=FONT_TITLE,
                                padx=10, pady=8, bd=1, relief="groove")
        time_lf.pack(fill="x", pady=(0, 12))

        task_time = int(task_data.get("TIME_SPENT_IN_LOGS") or task_data.get("timeSpentInLogs") or 0)
        tracker: dict = {}
        today_date    = datetime.now(timezone(timedelta(hours=1))).date()

        for msg in reversed(messages):
            text     = msg.get("text", "")
            raw_date = msg.get("date")
            if not raw_date:
                continue
            try:
                dt_obj = datetime.fromisoformat(raw_date)
                dt     = dt_obj.astimezone(timezone(timedelta(hours=1))) if dt_obj.tzinfo else \
                         dt_obj.replace(tzinfo=timezone(timedelta(hours=1)))
            except Exception:
                continue

            start_m  = re.search(r"\[USER=\d+\](.*?)\[/USER\]\s+włączył[a]?\s+śledzenie\s+czasu",
                                  text, re.IGNORECASE)
            stop_m   = re.search(r"\[USER=\d+\](.*?)\[/USER\]\s+wyłączył[a]?\s+śledzenie\s+czasu",
                                  text, re.IGNORECASE)
            finish_m = re.search(r"(ukończył|zakończył)[a]?\s+zadanie", text, re.IGNORECASE)

            if start_m:
                user = start_m.group(1).strip()
                tracker.setdefault(user, {"total": 0, "today": 0, "start_dt": None})
                tracker[user]["start_dt"] = dt
            elif stop_m:
                user = stop_m.group(1).strip()
                tracker.setdefault(user, {"total": 0, "today": 0, "start_dt": None})
                if tracker[user]["start_dt"]:
                    elapsed               = (dt - tracker[user]["start_dt"]).total_seconds()
                    tracker[user]["total"] += max(0, elapsed)
                    if dt.date() == today_date or tracker[user]["start_dt"].date() == today_date:
                        tracker[user]["today"] += max(0, elapsed)
                tracker[user]["start_dt"] = None
            elif finish_m:
                for user, data in tracker.items():
                    if data["start_dt"]:
                        elapsed        = (dt - data["start_dt"]).total_seconds()
                        data["total"] += max(0, elapsed)
                        if dt.date() == today_date or data["start_dt"].date() == today_date:
                            data["today"] += max(0, elapsed)
                        data["start_dt"] = None

        total_time_var = tk.StringVar()
        tk.Label(time_lf, textvariable=total_time_var, bg=C["bg"],
                 fg=C["accent"], font=("Segoe UI Semibold", 12)).pack(anchor="w", pady=(0, 8))

        active_timers: dict = {}
        if not tracker and task_time == 0:
            total_time_var.set("Razem: 00:00:00")
            tk.Label(time_lf, text="Brak historii czasu.", bg=C["bg"],
                     fg=C["text_muted"], font=FONT_BODY).pack(anchor="w")
        else:
            for user, data in tracker.items():
                lbl_var   = tk.StringVar()
                tk.Label(time_lf, textvariable=lbl_var, bg=C["bg"], fg=C["text"],
                         font=FONT_BODY).pack(anchor="w")
                is_active = bool(data["start_dt"] and data["start_dt"].date() == today_date)
                today_str = f"  (dziś: {seconds_to_readable(data['today'])})" if data["today"] > 0 else ""
                if is_active:
                    active_timers[user] = {**data, "var": lbl_var}
                else:
                    lbl_var.set(f"👤 {user}  {seconds_to_readable(data['total'])}{today_str}")
            if not active_timers:
                total_time_var.set(f"Razem: {seconds_to_readable(task_time)}")

        if active_timers:
            self.update_live_timers(window, active_timers, total_time_var, task_time, window.current_cycle)

    def _build_chat_section(self, parent: tk.Frame, messages: list,
                            chat_id, window: tk.Toplevel) -> None:
        hdr = f"💬 Wiadomości (Chat ID: {chat_id})" if chat_id else "💬 Wiadomości (brak czatu)"
        if not messages and chat_id:
            hdr += " — synchronizowanie..."
        tk.Label(parent, text=hdr, bg=C["bg"], fg=C["accent2"], font=FONT_TITLE).pack(anchor="w")

        chat_frame = tk.Frame(parent, bg=C["bg"])
        chat_frame.pack(fill="both", expand=True, pady=(4, 0))
        chat_scroll = ttk.Scrollbar(chat_frame, orient="vertical")
        chat_scroll.pack(side="right", fill="y")
        chat_text = tk.Text(chat_frame, wrap="word", yscrollcommand=chat_scroll.set,
                            bg=C["card"], fg=C["text"], font=FONT_BODY,
                            bd=0, relief="flat", insertbackground=C["text"],
                            selectbackground=C["accent2"])
        chat_text.pack(side="left", fill="both", expand=True)
        chat_scroll.config(command=chat_text.yview)

        if not hasattr(window, "chat_images"):
            window.chat_images = []

        if messages:
            for msg in reversed(messages):
                author_id   = str(msg.get("author_id", ""))
                author_name = "System"
                author_photo = None
                if author_id and author_id != "0":
                    ud = self.users_map.get(author_id)
                    if isinstance(ud, dict):
                        author_name  = ud.get("name", f"ID {author_id}")
                        author_photo = self.get_user_avatar(author_id, ud.get("photo"), size=18)
                    elif isinstance(ud, str):
                        author_name = ud
                    else:
                        author_name = f"ID {author_id}"

                clean_text = re.sub(r"\[USER=\d+\](.*?)\[/USER\]", r"\1", msg.get("text", ""))
                date       = format_date(msg.get("date"))

                chat_text.insert("end", f" [{date}]  ", "header")
                if author_photo:
                    window.chat_images.append(author_photo)
                    chat_text.image_create("end", image=author_photo)
                    chat_text.insert("end", " ")
                else:
                    chat_text.insert("end", "👤 ")
                chat_text.insert("end", f"{author_name}\n", "header")
                chat_text.insert("end", f"  {clean_text}\n\n", "body")
        else:
            chat_text.insert("end", "Brak wiadomości. Jeśli to pierwsze otwarcie, wiadomości pojawią się za chwilę.")

        chat_text.tag_config("header", foreground=C["accent"],
                             font=("Segoe UI Semibold", 9), background=C["sidebar"])
        chat_text.tag_config("body", foreground=C["text"])
        chat_text.config(state="disabled")

    # ==================================================================
    # Live timery w oknie zadania
    # ==================================================================

    def update_live_timers(self, window: tk.Toplevel, active_timers: dict,
                           total_time_var: tk.StringVar, task_time: int, cycle_id: int) -> None:
        if not window.winfo_exists() or getattr(window, "current_cycle", None) != cycle_id:
            return
        now        = datetime.now(timezone(timedelta(hours=1)))
        live_total = 0.0
        for user, data in active_timers.items():
            elapsed    = max(0, (now - data["start_dt"]).total_seconds())
            live_total += elapsed
            total_user  = data["total"] + elapsed
            today_user  = data["today"] + elapsed
            data["var"].set(
                f"👤 {user}  {seconds_to_readable(total_user)}"
                f"  (dziś: {seconds_to_readable(today_user)})  🔴 aktywny"
            )
        base_str = seconds_to_readable(task_time)
        if live_total > 0:
            grand = task_time + live_total
            total_time_var.set(
                f"Razem: {base_str}  +  {seconds_to_readable(live_total)}"
                f"  =  {seconds_to_readable(grand)}"
            )
        else:
            total_time_var.set(f"Razem: {base_str}")
        window.after(
            1000,
            lambda: self.update_live_timers(window, active_timers, total_time_var, task_time, cycle_id),
        )

    # ==================================================================
    # Pobieranie wiadomości (wątek)
    # ==================================================================

    def bg_fetch_messages(self, task_data: dict, chat_id, chat_file: str,
                          window: tk.Toplevel) -> None:
        messages: list = []
        last_id        = None
        timeout        = 5
        try:
            while True:
                url = f"{WEBHOOK_URL}im.dialog.messages.get?DIALOG_ID=chat{chat_id}&LIMIT=50"
                if last_id is not None:
                    url += f"&LAST_ID={last_id}"
                try:
                    resp = requests.get(url, timeout=timeout)
                    resp.raise_for_status()
                    fetched = resp.json().get("result", {}).get("messages", [])
                    if not fetched:
                        break
                    messages.extend(fetched)
                    valid_ids = [m.get("id") for m in fetched if m.get("id")]
                    if not valid_ids:
                        break
                    last_id = min(valid_ids)
                    time.sleep(0.5)
                    timeout = 5
                except requests.exceptions.Timeout:
                    timeout += 10
                    if timeout > 45:
                        break
                    time.sleep(1)

            if messages:
                with open(chat_file, "w", encoding="utf-8") as f:
                    json.dump(messages, f, ensure_ascii=False, indent=4)
                self._check_and_fetch_missing_users(task_data, messages)
                self.root.after(0, lambda: self.reload_task_window(window, task_data, messages, chat_id))
        except requests.exceptions.RequestException as e:
            print(f"Błąd pobierania wiadomości: {e}")

    # ==================================================================
    # Pomocnicze
    # ==================================================================

    def _extract_participants(self, task: dict) -> list[str]:
        result: list = []
        acc = task.get("accomplicesData")
        if isinstance(acc, dict):
            for udata in acc.values():
                if isinstance(udata, dict) and udata.get("name"):
                    result.append(udata["name"])
        elif isinstance(acc, list):
            for udata in acc:
                if isinstance(udata, dict) and udata.get("name"):
                    result.append(udata["name"])
        return result

    def _check_and_fetch_missing_users(self, task_data: dict, messages: list) -> None:
        required: set = set()
        for key in ("createdBy", "responsibleId"):
            if task_data.get(key):
                required.add(str(task_data[key]))
        for msg in messages:
            if msg.get("author_id"):
                required.add(str(msg["author_id"]))
        missing = [uid for uid in required if uid not in self.users_map and uid != "0"]
        if missing:
            self.fetch_all_users()
