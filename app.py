import json
import os
import re
import threading
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime, timezone, timedelta
from tkinter import messagebox, ttk

import requests

from config import (
    C, FONT_BODY, FONT_HEADING, FONT_MONO, FONT_SMALL, FONT_TITLE,
    STATUS_COLORS, STATUS_MAP, apply_theme as _config_apply_theme,
)

from view.task_utils import (
    get_responsible, get_creator, get_base_time,
    get_participants, get_participants_names,
)

from model.api_model import BitrixApiClient
from model.local_storage import LocalStorage
from view.card_view import TaskCardView
from view.kanban_view import KanbanView
from view.summary_view import SummaryView
from helpers import (
    format_date, get_data_dir,
    parse_to_aware_datetime, seconds_to_readable,
)
from styles import ModernButton, ModernCheckbutton, apply_theme_style


def _group_tasks_by_group_id(tasks: list) -> dict:
    """Grupuje zadania po GROUP_ID → {group_id_str: [task, ...]}."""
    result: dict = {}
    for t in tasks:
        gid = str(t.get("GROUP_ID") or t.get("groupId") or "")
        if gid and gid != "0":
            result.setdefault(gid, []).append(t)
    return result


def _calc_row_heights(visible_groups: list, tasks_by_group: dict) -> dict:
    """
    Stała wysokość wiersza w trybie rozszerzonym:
      - Z zadaniami:    pasek grupy (22) + pasek timeline (18) + podsumowanie (14) + pad (14) = 68px
      - Bez zadań:      pasek grupy (22) + info (14) + pad (8) = 44px
    """
    heights = {}
    for pg in visible_groups:
        has_tasks = bool(tasks_by_group.get(pg["id"]))
        heights[pg["id"]] = 68 if has_tasks else 44
    return heights

class BitrixApp:
    """Główna aplikacja do zarządzania zadaniami Bitrix24."""

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
        self._TASK_STATUS_DONE = {"5", "4", "completed", "supposedly_done"}
        self._TASK_STATUS_ACTIVE = {"3"}
        self.root = root
        self.root.title("Bitrix24 — Task Manager")
        self.root.geometry("1300x820")

        self.data_dir = get_data_dir()

        # ── Warstwa modelu ─────────────────────────────────────────────
        self.storage = LocalStorage(self.data_dir)
        self.api     = BitrixApiClient(self.data_dir)

        # Motyw
        saved_cfg        = self.storage.load_config()
        self._theme_name = saved_cfg.get("theme", "dark")
        _config_apply_theme(self._theme_name)
        self.root.configure(bg=C["bg"])
        apply_theme_style(root)

        # Stan danych
        self.all_fetched_tasks:  list = []
        self.all_fetched_groups: list = []
        self.all_responsibles:   list = ["Wszyscy"]
        self.groups_map:  dict = {}
        self.users_map:   dict = {}

        # Licznik przebudowy UI
        self._ui_generation: int = 0

        # Zmienne UI
        self.current_view         = tk.StringVar(value="tasks")
        self.current_filter       = tk.StringVar(value=saved_cfg.get("filter", "W trakcie"))
        self.current_resp_filter  = tk.StringVar(value=saved_cfg.get("resp_filter", "Wszyscy"))
        self.search_var           = tk.StringVar(value=saved_cfg.get("search", ""))
        self.live_timer_var       = tk.BooleanVar(value=False)
        self.hide_inactive_var    = tk.BooleanVar(value=False)
        self.display_mode         = tk.StringVar(value=saved_cfg.get("display_mode", "cards"))

        self._group_cal_mode      = False
        self.current_group_view_id   = None
        self.current_group_view_name = None
        self.is_fetching             = False
        self.active_tree_timers:     dict = {}
        self._card_mode              = False

        self._ui_ready = False
        self._build_ui()
        self._ui_ready = True
        self.load_local_data()
        self._run_live_timers(self._ui_generation)
        self._schedule_auto_refresh()

    # ==================================================================
    # Właściwość — cache zdjęć delegowany do api_client
    # ==================================================================

    def get_user_avatar(self, uid: str, url: str, size: int = 20):
        """Proxy do api_client — zachowuje kompatybilność z widokami."""
        return self.api.get_user_avatar(uid, url, size)

    # ==================================================================
    # Budowanie UI  (bez zmian względem oryginału)
    # ==================================================================

    def _build_ui(self) -> None:
        self._build_topbar()
        tk.Frame(self.root, bg=C["accent"], height=2).pack(fill="x")
        self._build_toolbar()
        self._build_count_bar()
        self._build_content_area()

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

        theme_icon = "Motyw jasny ☀️" if self._theme_name == "dark" else "Motyw ciemny 🌙"
        self.btn_theme = tk.Button(
            logo_strip, text=theme_icon,
            bg=C["header"], fg="#94A3B8",
            font=("Segoe UI", 11), relief="flat", bd=0, cursor="hand2",
            padx=8, pady=4,
            activebackground=C["header"], activeforeground=C["accent"],
            command=self._toggle_theme,
        )
        self.btn_theme.pack(side="right", padx=(0, 4))

    def _build_toolbar(self) -> None:
        toolbar_container = tk.Frame(self.root, bg=C["sidebar"], pady=4)
        toolbar_container.pack(fill="x")
        row1 = tk.Frame(toolbar_container, bg=C["sidebar"])
        row1.pack(fill="x", padx=12, pady=2)
        self._build_toolbar_row1(row1)
        row2 = tk.Frame(toolbar_container, bg=C["sidebar"])
        row2.pack(fill="x", padx=12, pady=2)
        self._build_toolbar_row2(row2)

    def _build_toolbar_row1(self, parent: tk.Frame) -> None:
        left = tk.Frame(parent, bg=C["sidebar"])
        left.pack(side="left")

        for val, lbl in [("tasks", "📋 Zadania"), ("groups", "🗂 Grupy"), ("summary", "📊 Podsumowanie")]:
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

        self.btn_group_calendar = tk.Button(
            left, text="📅 Kalendarz życia grup",
            bg=C.get("btn_blue", "#3B82F6"), fg="#FFFFFF",
            font=("Segoe UI", 10, "bold"), relief="flat", bd=0, cursor="hand2",
            padx=14, pady=4, activebackground=C["accent"], activeforeground="#000",
            command=self.toggle_groups_calendar
        )

        self.view_toggle_frame = tk.Frame(left, bg=C["sidebar"],
                                          highlightthickness=1,
                                          highlightbackground=C["card_border"])
        self.view_toggle_frame.pack(side="left", padx=2)

        self.btn_view_cards  = self._toggle_btn(self.view_toggle_frame, "⊞ Kafelki", "cards")
        self.btn_view_list   = self._toggle_btn(self.view_toggle_frame, "☰ Lista",   "list")
        self.btn_view_kanban = self._toggle_btn(self.view_toggle_frame, "⬛ Kanban",  "kanban")

        self.btn_view_cards.config(command=lambda:  self._set_display_mode("cards"))
        self.btn_view_list.config(command=lambda:   self._set_display_mode("list"))
        self.btn_view_kanban.config(command=lambda: self._set_display_mode("kanban"))

        self.btn_set_default = tk.Button(
            left, text="★ Domyślny",
            bg=C["sidebar"], fg=C["text_muted"],
            font=FONT_SMALL, relief="flat", bd=0, cursor="hand2",
            padx=6, pady=4,
            activebackground=C["tag_bg"], activeforeground=C["accent"],
            command=self._save_display_mode_as_default,
        )
        self.btn_set_default.pack(side="left", padx=(4, 0))
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
        prev_mode = self.display_mode.get()
        self.display_mode.set(mode)

        if not getattr(self, "_ui_ready", False):
            return

        for btn, val in (
                (self.btn_view_cards,  "cards"),
                (self.btn_view_list,   "list"),
                (self.btn_view_kanban, "kanban"),
        ):
            btn.config(
                bg=C["accent"] if mode == val else C["sidebar"],
                fg="#000"       if mode == val else C["text_muted"],
            )

        if mode in ("cards", "kanban"):
            self.btn_action.pack_forget()
            self.action_separator.pack_forget()
            if hasattr(self, "chk_live_timer"):
                try:
                    self.chk_live_timer.pack_forget()
                    self.chk_hide_inactive.pack_forget()
                except tk.TclError:
                    pass
        else:
            try:
                self.btn_action.pack(side="left", padx=2, after=self.btn_fetch)
                self.action_separator.pack(side="left", fill="y", padx=6, after=self.btn_action)
            except tk.TclError:
                pass
            if hasattr(self, "chk_live_timer"):
                try:
                    self.chk_live_timer.pack(side="left", padx=6)
                    self.chk_hide_inactive.pack(side="left", padx=6)
                except tk.TclError:
                    pass

        if hasattr(self, "status_label") and hasattr(self, "status_combobox"):
            if mode == "kanban":
                self.status_label.pack_forget()
                self.status_combobox.pack_forget()
            else:
                try:
                    self.status_label.pack(side="left", padx=(0, 2), before=self.resp_combobox)
                    self.status_combobox.pack(side="left", padx=(0, 6), before=self.resp_combobox)
                except tk.TclError:
                    pass

        if not hasattr(self, "tree_frame") or not hasattr(self, "card_view"):
            return

        needs_reload = False
        if mode == "kanban":
            if prev_mode != "kanban":
                self._pre_kanban_filter = self.current_filter.get()
            self.current_filter.set("Wszystkie")
            needs_reload = True
        elif prev_mode == "kanban":
            restored = getattr(self, "_pre_kanban_filter", "W trakcie")
            self.current_filter.set(restored)
            needs_reload = True

        if needs_reload:
            self._reload_tasks_from_disk()

        self.apply_filter()

    def _build_toolbar_row2(self, parent: tk.Frame) -> None:
        right = tk.Frame(parent, bg=C["sidebar"])
        right.pack(side="left")

        self.chk_live_timer = ModernCheckbutton(right, "⏱ Licz czas na żywo",
                                                variable=self.live_timer_var, command=self.apply_filter)
        self.chk_live_timer.pack(side="left", padx=4)

        self.chk_hide_inactive = ModernCheckbutton(right, "🔕 Ukryj starsze >14d",
                                                   variable=self.hide_inactive_var, command=self.apply_filter)
        self.chk_hide_inactive.pack(side="left", padx=4)

        tk.Frame(right, bg=C["card_border"], width=1).pack(side="left", fill="y", padx=6)

        self.filter_frame = tk.Frame(right, bg=C["sidebar"])
        self.filter_frame.pack(side="left")

        self.status_label = self._lbl(self.filter_frame, "Status:")
        self.status_label.pack(side="left", padx=(0, 2))
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

    def _build_count_bar(self) -> None:
        count_bar = tk.Frame(self.root, bg=C["bg"], pady=4)
        count_bar.pack(fill="x")

        self.count_var = tk.StringVar(value="")
        tk.Label(count_bar, textvariable=self.count_var, bg=C["bg"],
                 fg=C["text_muted"], font=FONT_SMALL).pack(side="left", padx=14)

        self.view_label_var = tk.StringVar(value="")
        tk.Label(count_bar, textvariable=self.view_label_var, bg=C["bg"],
                 fg=C["accent2"], font=("Segoe UI Semibold", 9)).pack(side="right", padx=14)

    def _build_content_area(self) -> None:
        self.content_frame = tk.Frame(self.root, bg=C["bg"])
        self.content_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

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

        self.card_view   = TaskCardView(self.content_frame, app=self, on_open_cb=self._open_task_by_id)
        self.kanban_view = KanbanView(self.content_frame, app=self, on_open_cb=self._open_task_by_id)
        self.summary_view = SummaryView(self.content_frame, app=self)

    # ==================================================================
    # Helpers UI
    # ==================================================================

    def _lbl(self, parent, text: str) -> tk.Label:
        return tk.Label(parent, text=text, bg=C["sidebar"], fg=C["text_muted"], font=FONT_SMALL)

    def _show_cards(self, tasks: list) -> None:
        self._card_mode = True
        self.tree_frame.pack_forget()
        self.kanban_view.pack_forget()
        if hasattr(self, "summary_view"): self.summary_view.pack_forget()
        if hasattr(self, "group_cal_frame"): self.group_cal_frame.pack_forget()
        self.card_view.pack(fill="both", expand=True)
        self.card_view.load_tasks(tasks)
        self.count_var.set(f"{len(tasks)} zadań")

    def _show_tree(self) -> None:
        self._card_mode = False
        self.card_view.pack_forget()
        self.kanban_view.pack_forget()
        if hasattr(self, "summary_view"): self.summary_view.pack_forget()
        if hasattr(self, "group_cal_frame"): self.group_cal_frame.pack_forget()
        self.tree_frame.pack(fill="both", expand=True)

    def _show_kanban(self, visible: bool) -> None:
        if visible:
            self._card_mode = False
            self.card_view.pack_forget()
            self.tree_frame.pack_forget()
            if hasattr(self, "summary_view"): self.summary_view.pack_forget()
            if hasattr(self, "group_cal_frame"): self.group_cal_frame.pack_forget()
            self.kanban_view.pack(fill="both", expand=True)
        else:
            self.kanban_view.pack_forget()

    # ==================================================================
    # Dane lokalne
    # ==================================================================

    def load_local_data(self) -> None:
        """Wczytuje wszystkie dane z dysku przy starcie aplikacji."""
        groups = self.storage.load_groups()
        if groups:
            self.all_fetched_groups = groups
            self.build_groups_map()

        self._reload_tasks_from_disk()

        users = self.storage.load_users()
        if users:
            self.users_map = users
        else:
            # Brak lokalnego pliku → pobierz z API w tle
            threading.Thread(target=self._bg_fetch_users, daemon=True).start()

        self.switch_view()

    def _reload_tasks_from_disk(self) -> None:
        """Wczytuje zadania z dysku zgodnie z aktualnym filtrem statusu."""
        in_progress = self.current_filter.get() == "W trakcie"
        self.all_fetched_tasks = self.storage.load_tasks(in_progress)
        self.update_resp_filter_options()

    def build_groups_map(self) -> None:
        self.groups_map = {str(g.get("ID")): g.get("NAME") for g in self.all_fetched_groups}

    # ==================================================================
    # Wątki tła — API
    # Każda metoda _bg_* działa w osobnym wątku i na koniec
    # wywołuje root.after(0, callback) aby wrócić do wątku UI.
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
            label = "Automatyczne odświeżanie..." if is_auto else "Pobieranie zadań..."
            self.status_var.set(label)
            threading.Thread(target=self._bg_fetch_tasks, args=(is_auto,), daemon=True).start()
        elif mode == "groups":
            self.status_var.set("Pobieranie grup...")
            threading.Thread(target=self._bg_fetch_groups, args=(is_auto,), daemon=True).start()
        elif mode == "summary":
            self.btn_group_calendar.pack_forget()
            self.view_toggle_frame.pack_forget()
            self.btn_set_default.pack_forget()
            self.filter_frame.pack_forget()
            self.kanban_view.pack_forget()
            self.card_view.pack_forget()
            self.tree_frame.pack_forget()
            if hasattr(self, "group_cal_frame"):
                self.group_cal_frame.pack_forget()
            self.summary_view.refresh_persons()
            self.summary_view.pack(fill="both", expand=True)

    # -- Użytkownicy ---------------------------------------------------

    def _bg_fetch_users(self) -> None:
        try:
            users = self.api.fetch_all_users()
            self.root.after(0, self._on_users_fetched, users)
        except requests.RequestException as e:
            print(f"Błąd pobierania użytkowników: {e}")

    def _on_users_fetched(self, users: dict) -> None:
        self.users_map = users

    # -- Zadania -------------------------------------------------------

    def _bg_fetch_tasks(self, is_auto: bool) -> None:
        try:
            if self.current_filter.get() == "W trakcie":
                tasks = self.api.fetch_in_progress_tasks(
                    on_progress=lambda n: self.root.after(
                        0, lambda: self.status_var.set(f"Pobrano {n} zadań 'W trakcie'...")
                    )
                )
            else:
                file_exists = self.storage.tasks_list_exists()
                tasks = self.api.fetch_standard_tasks(
                    file_exists=file_exists,
                    on_progress=lambda n: self.root.after(
                        0, lambda: self.status_var.set(f"Pobrano {n} zadań...")
                    ),
                )
            self.root.after(0, self._on_fetch_tasks_success, tasks, is_auto)
        except requests.RequestException as e:
            self.root.after(0, self._on_fetch_error, e, "zadań")

    # -- Grupy ---------------------------------------------------------

    def _bg_fetch_groups(self, is_auto: bool) -> None:
        try:
            groups = self.api.fetch_all_groups(
                on_progress=lambda n: self.root.after(
                    0, lambda: self.status_var.set(f"Pobrano {n} grup...")
                )
            )
            self.root.after(0, self._on_fetch_groups_success, groups, is_auto)
        except requests.RequestException as e:
            self.root.after(0, self._on_fetch_error, e, "grup")

    def _bg_filter_tasks_by_group(self, group_id: str, group_name: str, is_auto: bool = False) -> None:
        try:
            tasks = self.api.fetch_tasks_by_group(
                group_id,
                on_progress=lambda n: self.root.after(
                    0, lambda: self.status_var.set(f"Pobrano {n} zadań grupy...")
                ),
            )
            self.root.after(0, self._on_filter_tasks_success, tasks, group_name, is_auto)
        except Exception as e:
            self.root.after(0, self._on_filter_tasks_error, e, group_name)

    # ── Callbacki (wątek UI) ──────────────────────────────────────────

    def _on_fetch_tasks_success(self, tasks: list, is_auto: bool = False) -> None:
        self.all_fetched_tasks = tasks
        self.update_resp_filter_options()
        self.apply_filter()
        if is_auto:
            self._reset_fetch_status(f"Odświeżono ({datetime.now().strftime('%H:%M')}).")
        else:
            self._reset_fetch_status("Pobrano zadania.")
            messagebox.showinfo("Sukces", "Zakończono pobieranie.")

    def _on_fetch_groups_success(self, groups: list, is_auto: bool = False) -> None:
        self.all_fetched_groups = groups
        self.build_groups_map()
        if getattr(self, "_group_cal_mode", False):
            self.display_groups_calendar(groups)
        else:
            self.display_groups(groups)
        if is_auto:
            self._reset_fetch_status(f"Odświeżono ({datetime.now().strftime('%H:%M')}).")
        else:
            self._reset_fetch_status("Pobrano grupy.")
            messagebox.showinfo("Sukces", "Pobrano i zapisano grupy robocze.")

    def _on_filter_tasks_success(self, tasks: list, group_name: str, is_auto: bool = False) -> None:
        if not is_auto and not tasks:
            self._reset_fetch_status("Zakończono pobieranie.")
            messagebox.showinfo("Informacja", f"Brak zadań w grupie: {group_name}")
            return
        self.all_fetched_tasks = tasks
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
    # Stan UI
    # ==================================================================

    def _toggle_buttons_state(self, state: str) -> None:
        self.btn_fetch.config(state=state)
        try:
            self.btn_action.config(state=state)
        except Exception:
            pass
        self.btn_view_cards.config(state=state)
        self.btn_view_list.config(state=state)
        self.btn_view_kanban.config(state=state)
        self.btn_set_default.config(state=state)

    def _reset_fetch_status(self, message: str, success: bool = True) -> None:
        self.is_fetching = False
        self._toggle_buttons_state("normal")
        self.status_var.set(message)
        self.root.after(4000, lambda: self.status_var.set(""))

    def _schedule_auto_refresh(self) -> None:
        self.root.after(300_000, self._auto_refresh_trigger)

    def _auto_refresh_trigger(self) -> None:
        mode = self.current_view.get()
        # Odświeżanie automatyczne tylko w widoku zadań
        if mode != "tasks":
            self._schedule_auto_refresh()
            return

        if not self.is_fetching:
            if self.current_group_view_id:
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
    # Konfiguracja
    # ==================================================================

    def _save_config(self) -> None:
        cfg = self.storage.load_config()
        cfg.update({
            "display_mode": self.display_mode.get(),
            "theme":        self._theme_name,
            "filter":       self.current_filter.get(),
            "resp_filter":  self.current_resp_filter.get(),
            "search":       self.search_var.get(),
        })
        self.storage.save_config(cfg)

    def _toggle_theme(self) -> None:
        new_name = "light" if self._theme_name == "dark" else "dark"
        self._apply_theme(new_name)

    def _apply_theme(self, theme_name: str) -> None:
        state = self._capture_ui_state()
        self._theme_name = theme_name
        _config_apply_theme(theme_name)
        self._save_config()

        self._ui_generation += 1
        self._ui_ready = False
        for w in self.root.winfo_children():
            w.destroy()
        self.root.configure(bg=C["bg"])
        apply_theme_style(self.root)
        self._build_ui()
        self._ui_ready = True

        self._restore_ui_state(state)
        self.switch_view()
        self._run_live_timers(self._ui_generation)

    def _capture_ui_state(self) -> dict:
        return {
            "view":           self.current_view.get(),
            "filter":         self.current_filter.get(),
            "resp_filter":    self.current_resp_filter.get(),
            "search":         self.search_var.get(),
            "live_timer":     self.live_timer_var.get(),
            "hide_inactive":  self.hide_inactive_var.get(),
            "display_mode":   self.display_mode.get(),
            "group_id":       self.current_group_view_id,
            "group_name":     self.current_group_view_name,
            "group_cal_mode": getattr(self, "_group_cal_mode", False),
        }

    def _restore_ui_state(self, state: dict) -> None:
        self.current_view.set(state["view"])
        self.current_filter.set(state["filter"])
        self.current_resp_filter.set(state["resp_filter"])
        self.search_var.set(state["search"])
        self.live_timer_var.set(state["live_timer"])
        self.hide_inactive_var.set(state["hide_inactive"])
        self.display_mode.set(state["display_mode"])
        self.current_group_view_id   = state["group_id"]
        self.current_group_view_name = state["group_name"]
        self._group_cal_mode = state.get("group_cal_mode", False)

        mode = state["display_mode"]
        try:
            for btn, val in (
                (self.btn_view_cards,  "cards"),
                (self.btn_view_list,   "list"),
                (self.btn_view_kanban, "kanban"),
            ):
                btn.config(
                    bg=C["accent"] if mode == val else C["sidebar"],
                    fg="#000"       if mode == val else C["text_muted"],
                )
        except tk.TclError:
            pass

    def _save_display_mode_as_default(self) -> None:
        self._save_config()
        self.btn_set_default.config(text="✓ Zapisano!", fg=C["btn_green"])
        self.root.after(2000, lambda: self.btn_set_default.config(text="★ Domyślny", fg=C["text_muted"]))

    # ==================================================================
    # Przełączanie widoków
    # ==================================================================

    def switch_view(self) -> None:
        mode = self.current_view.get()
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.active_tree_timers.clear()

        if mode == "tasks":
            self.btn_group_calendar.pack_forget()
            self.btn_fetch.config(text="⟳  Odśwież")
            self.filter_frame.pack(side="left")
            self.tree.config(columns=self.TASK_COLUMNS)
            for col in self.TASK_COLUMNS:
                self.tree.heading(col, text=col, command=lambda c=col: self.sort_treeview(c, False))
            self.view_toggle_frame.pack(side="left", padx=2)
            self.btn_set_default.pack(side="left", padx=(4, 0))
            self._set_display_mode(self.display_mode.get())

        elif mode == "groups":
            self.view_toggle_frame.pack_forget()
            self.btn_set_default.pack_forget()
            self.filter_frame.pack_forget()
            self.kanban_view.pack_forget()
            self.btn_fetch.config(text="⟳  Odśwież grupy")
            self.btn_action.config(text="↗  Otwórz / Filtruj zadania")
            self.btn_action.pack(side="left", padx=2, after=self.btn_fetch)
            self.action_separator.pack(side="left", fill="y", padx=6, after=self.btn_action)
            self.btn_group_calendar.pack(side="left", padx=10, after=self.action_separator)

            if self._group_cal_mode:
                self.btn_group_calendar.config(text="☰ Wróć do listy grup", bg=C["sidebar"], fg=C["accent"])
                self.display_groups_calendar(self.all_fetched_groups)
            else:
                self.btn_group_calendar.config(text="📅 Kalendarz życia grup",
                                               bg=C.get("btn_blue", "#3B82F6"), fg="#FFFFFF")
                if hasattr(self, "group_cal_frame"):
                    self.group_cal_frame.pack_forget()

                self._show_tree()

                self.tree.config(columns=self.GROUP_COLUMNS)
                for col in self.GROUP_COLUMNS:
                    self.tree.heading(col, text=col, command=lambda c=col: self.sort_treeview(c, False))
                self.display_groups(self.all_fetched_groups)

        elif mode == "summary":
            self.btn_group_calendar.pack_forget()
            self.view_toggle_frame.pack_forget()
            self.btn_set_default.pack_forget()
            self.filter_frame.pack_forget()
            self.card_view.pack_forget()
            self.kanban_view.pack_forget()
            self.tree_frame.pack_forget()
            if hasattr(self, "group_cal_frame"):
                self.group_cal_frame.pack_forget()
            self.summary_view.refresh_persons()
            self.summary_view.pack(fill="both", expand=True)

    def display_groups(self, groups: list) -> None:
        if self.current_view.get() != "groups" or self._group_cal_mode:
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
        self.view_label_var.set("Widok: Lista grup roboczych")

    # ==================================================================
    # Kalendarz grup  (bez zmian)
    # ==================================================================

    def toggle_groups_calendar(self) -> None:
        self._group_cal_mode = not getattr(self, "_group_cal_mode", False)
        if self._group_cal_mode:
            self.btn_group_calendar.config(
                text="☰ Wróć do listy grup", bg=C["sidebar"], fg=C["accent"])
            self.display_groups_calendar(self.all_fetched_groups)
        else:
            self.btn_group_calendar.config(
                text="📅 Kalendarz życia grup",
                bg=C.get("btn_blue", "#3B82F6"), fg="#FFFFFF")
            if hasattr(self, "group_cal_frame"):
                self.group_cal_frame.pack_forget()
            self._show_tree()
            self.display_groups(self.all_fetched_groups)

    def _toggle_cal_sort(self) -> None:
        current_mode = getattr(self, "_group_cal_sort_mode", "activity")
        self._group_cal_sort_mode = "start" if current_mode == "activity" else "activity"
        self.display_groups_calendar(self.all_fetched_groups)

    def _get_cal_active_filters(self) -> set:
        """Lazy init zestawu aktywnych filtrów kalendarza."""
        if not hasattr(self, "_cal_active_filters"):
            self._cal_active_filters = {"7", "30", "60", "old"}
        return self._cal_active_filters

    def _cal_bar_colors(self, days_inactive: int) -> tuple[str, str, str]:
        """Zwraca (bar_color, outline_color, text_color) dla danej liczby dni."""
        if days_inactive <= 7:
            return "#10B981", "#059669", C["text"]
        elif days_inactive <= 30:
            return "#F59E0B", "#D97706", C["text"]
        elif days_inactive <= 60:
            return "#EF4444", "#B91C1C", C["text_muted"]
        else:
            return C.get("card_border", "#475569"), C.get("text_muted", "#64748B"), C.get("text_muted", "#64748B")

    def _cal_bucket(self, days_inactive: int) -> str:
        """Zwraca klucz kubełka dla danej liczby dni nieaktywności."""
        if days_inactive <= 7:   return "7"
        if days_inactive <= 30:  return "30"
        if days_inactive <= 60:  return "60"
        return "old"


    def display_groups_calendar(self, groups: list) -> None:
        self.tree_frame.pack_forget()
        if hasattr(self, "card_view"):   self.card_view.pack_forget()
        if hasattr(self, "kanban_view"): self.kanban_view.pack_forget()

        if not hasattr(self, "_group_cal_sort_mode"):
            self._group_cal_sort_mode = "activity"
        if not hasattr(self, "_extended_view"):
            self._extended_view = False

        if not hasattr(self, "group_cal_frame"):
            self.group_cal_frame = tk.Frame(self.content_frame, bg=C["bg"])

            # ── Pasek górny ────────────────────────────────────────────────
            self.cal_top_frame = tk.Frame(self.group_cal_frame, bg=C["bg"])
            self.cal_top_frame.pack(side="top", fill="x", pady=(0, 5))

            self.btn_cal_sort = tk.Button(
                self.cal_top_frame, text="",
                bg=C["sidebar"], fg=C["text"], font=FONT_SMALL,
                relief="flat", cursor="hand2", padx=12, pady=4,
                activebackground=C["accent"], activeforeground="#000",
                command=self._toggle_cal_sort,
            )
            self.btn_cal_sort.pack(side="left")

            # Przycisk widoku rozszerzonego
            self.btn_extended = tk.Button(
                self.cal_top_frame,
                text="📊 Widok rozszerzony",
                bg=C["sidebar"], fg=C["text_muted"], font=FONT_SMALL,
                relief="flat", cursor="hand2", padx=12, pady=4,
                activebackground=C["card_hover"], activeforeground=C["accent"],
                command=self._toggle_extended_view,
            )
            self.btn_extended.pack(side="left", padx=(6, 0))

            # Status ładowania raportu
            self._extended_status_var = tk.StringVar(value="")
            tk.Label(
                self.cal_top_frame,
                textvariable=self._extended_status_var,
                bg=C["bg"], fg=C["text_muted"], font=FONT_SMALL,
            ).pack(side="left", padx=(8, 0))

            # ── Legenda z filtrowaniem ─────────────────────────────────────
            self.cal_legend_frame = tk.Frame(self.cal_top_frame, bg=C["bg"])
            self.cal_legend_frame.pack(side="right", padx=10)

            tk.Label(
                self.cal_legend_frame, text="Filtruj:",
                bg=C["bg"], fg=C["text_muted"], font=FONT_SMALL,
            ).pack(side="left", padx=(0, 6))

            self._cal_legend_buckets = [
                ("7", "#10B981", "< 7 dni"),
                ("30", "#F59E0B", "8–30 dni"),
                ("60", "#EF4444", "1–2 mies."),
                ("old", C.get("card_border", "#475569"), "> 2 mies."),
            ]
            self._cal_legend_btns: dict = {}

            for bucket_key, color, label in self._cal_legend_buckets:
                btn = tk.Button(
                    self.cal_legend_frame,
                    text=f"■  {label}", fg=color, font=FONT_SMALL,
                    relief="flat", bd=0, cursor="hand2", padx=10, pady=4,
                    activeforeground=color,
                )
                btn.pack(side="left", padx=2)
                self._cal_legend_btns[bucket_key] = btn

                def _make_toggle(key=bucket_key):
                    def _toggle():
                        filters = self._get_cal_active_filters()
                        if key in filters:
                            filters.discard(key)
                        else:
                            filters.add(key)
                        self._refresh_cal_legend_btns()
                        self._redraw_cal_canvas(getattr(self, "_cal_last_parsed", []))

                    return _toggle

                btn.config(command=_make_toggle())

            # ── Canvas ────────────────────────────────────────────────────
            self.cal_canvas = tk.Canvas(self.group_cal_frame, bg=C["bg"], highlightthickness=0)
            self.cal_vsb = ttk.Scrollbar(self.group_cal_frame, orient="vertical", command=self.cal_canvas.yview)
            self.cal_hsb = ttk.Scrollbar(self.group_cal_frame, orient="horizontal", command=self.cal_canvas.xview)
            self.cal_canvas.configure(yscrollcommand=self.cal_vsb.set, xscrollcommand=self.cal_hsb.set)
            self.cal_vsb.pack(side="right", fill="y")
            self.cal_hsb.pack(side="bottom", fill="x")
            self.cal_canvas.pack(side="left", fill="both", expand=True)
            self.cal_canvas.bind(
                "<MouseWheel>",
                lambda e: self.cal_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
            )

        self._refresh_cal_legend_btns()

        self.btn_cal_sort.config(
            text="🔄 Przełącz: Teraz sortujesz po NAJNOWSZEJ AKTYWNOŚCI"
            if self._group_cal_sort_mode == "activity"
            else "🔄 Przełącz: Teraz sortujesz CHRONOLOGICZNIE (Utworzenie)"
        )

        self.group_cal_frame.pack(fill="both", expand=True)

        # ── Parsowanie grup ────────────────────────────────────────────────
        now = datetime.now(timezone.utc)
        min_date = now
        parsed_groups = []

        for g in groups:
            c_raw = g.get("DATE_CREATE")
            a_raw = g.get("DATE_ACTIVITY") or c_raw
            if not c_raw:
                continue
            c_dt = parse_to_aware_datetime(c_raw)
            a_dt = parse_to_aware_datetime(a_raw)
            if not c_dt or not a_dt:
                continue
            if c_dt < min_date:
                min_date = c_dt
            parsed_groups.append({
                "id": str(g.get("ID", "")),
                "name": g.get("NAME", "Bez nazwy"),
                "start": c_dt,
                "end": a_dt,
            })

        if self._group_cal_sort_mode == "activity":
            parsed_groups.sort(key=lambda x: x["end"], reverse=True)
        else:
            parsed_groups.sort(key=lambda x: x["start"])

        self._cal_last_parsed = parsed_groups
        self._cal_min_date = min_date
        self._cal_now = now

        self._redraw_cal_canvas(parsed_groups)

    def _toggle_extended_view(self) -> None:
        """Włącza/wyłącza widok rozszerzony z timelinami zadań grup."""
        self._extended_view = not getattr(self, "_extended_view", False)

        if self._extended_view:
            self.btn_extended.config(
                text="📊 Widok podstawowy",
                bg=C["accent"], fg="#000",
                activebackground=C["accent"],
            )
            # Sprawdź czy mamy cache
            cached = self._load_cached_group_tasks_report()
            if cached:
                self._group_tasks_report = cached
                self._extended_status_var.set(f"✓ Załadowano {len(cached)} zadań z cache")
                self._redraw_cal_canvas(getattr(self, "_cal_last_parsed", []))
            else:
                self._start_fetch_group_tasks_report()
        else:
            self.btn_extended.config(
                text="📊 Widok rozszerzony",
                bg=C["sidebar"], fg=C["text_muted"],
                activebackground=C["card_hover"],
            )
            self._extended_status_var.set("")
            self._redraw_cal_canvas(getattr(self, "_cal_last_parsed", []))

    def _load_cached_group_tasks_report(self) -> list | None:
        """Wczytuje zapisany raport z dysku (jeśli istnieje)."""
        import json, os
        path = os.path.join(self.data_dir, "group_tasks_report.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def _start_fetch_group_tasks_report(self) -> None:
        """Uruchamia pobieranie zadań grup w wątku tła."""
        self._extended_status_var.set("⏳ Pobieranie zadań grup...")
        self.btn_extended.config(state="disabled")

        def _bg():
            try:
                tasks = self.api.fetch_tasks_for_groups_report(
                    on_progress=lambda n: self.root.after(
                        0, lambda: self._extended_status_var.set(f"⏳ Pobrano {n} zadań...")
                    )
                )
                self.root.after(0, self._on_group_tasks_report_ready, tasks)
            except Exception as e:
                self.root.after(
                    0,
                    lambda: self._extended_status_var.set(f"❌ Błąd: {e}"),
                )
                self.root.after(0, lambda: self.btn_extended.config(state="normal"))

        threading.Thread(target=_bg, daemon=True).start()

    def _refresh_cal_legend_btns(self) -> None:
        if not hasattr(self, "_cal_legend_btns"):
            return
        active = self._get_cal_active_filters()
        for key, color, _label in self._cal_legend_buckets:
            btn = self._cal_legend_btns[key]
            is_active = key in active
            btn.config(
                bg=C["card_hover"] if is_active else C["bg"],
                activebackground=C["card_hover"] if is_active else C["bg"],
                fg=color if is_active else C["text_muted"],
            )

    def _on_group_tasks_report_ready(self, tasks: list) -> None:
        """Callback po zakończeniu pobierania raportu."""
        self._group_tasks_report = tasks
        self._extended_status_var.set(f"✓ {len(tasks)} zadań")
        self.btn_extended.config(state="normal")
        self._redraw_cal_canvas(getattr(self, "_cal_last_parsed", []))

    def _redraw_cal_canvas(self, parsed_groups: list) -> None:
        """Przerysowuje canvas — tryb podstawowy lub rozszerzony."""
        self.cal_canvas.delete("all")

        now = getattr(self, "_cal_now", datetime.now(timezone.utc))
        min_date = getattr(self, "_cal_min_date", now)
        active_filters = self._get_cal_active_filters()
        extended = getattr(self, "_extended_view", False)

        # Filtruj grupy wg legendy
        visible = [
            pg for pg in parsed_groups
            if self._cal_bucket((now - pg["end"]).days) in active_filters
        ]

        if not parsed_groups:
            self.cal_canvas.create_text(20, 20, text="Brak danych do wyświetlenia.",
                                        fill=C["text"], anchor="nw")
            self.count_var.set("0 grup")
            return

        if not visible:
            self.cal_canvas.create_text(20, 20, text="Żadna grupa nie pasuje do wybranych filtrów.",
                                        fill=C["text_muted"], anchor="nw")
            self.count_var.set(f"0 z {len(parsed_groups)} grup")
            return

        # ── Parametry układu ───────────────────────────────────────────────
        label_width = 300
        day_width = 3
        total_days = (now - min_date).days + 1
        axis_y = 40

        if extended:
            # W trybie rozszerzonym każda grupa zajmuje więcej miejsca
            tasks_by_group = _group_tasks_by_group_id(
                getattr(self, "_group_tasks_report", [])
            )
            row_heights = _calc_row_heights(visible, tasks_by_group)
            canvas_height = axis_y + 10 + sum(row_heights.values()) + 20
        else:
            row_height = 40
            canvas_height = len(visible) * row_height + 80

        canvas_width = label_width + (total_days * day_width) + 200
        self.cal_canvas.configure(scrollregion=(0, 0, canvas_width, canvas_height))

        # Linia "DZIŚ"
        today_x = label_width + (now - min_date).days * day_width
        self.cal_canvas.create_line(today_x, axis_y, today_x, canvas_height,
                                    fill="#10B981", dash=(2, 2))
        self.cal_canvas.create_text(today_x, axis_y - 10, text="DZIŚ",
                                    fill="#10B981", font=("Segoe UI", 8, "bold"))

        # ── Rysuj wiersze ──────────────────────────────────────────────────
        y_cursor = axis_y + 10

        for pg in visible:
            days_inactive = (now - pg["end"]).days
            bar_color, outline_color, text_color = self._cal_bar_colors(days_inactive)

            name_disp = pg["name"][:32] + "..." if len(pg["name"]) > 35 else pg["name"]

            if extended:
                row_h = row_heights.get(pg["id"], 40)
            else:
                row_h = 40

            y0 = y_cursor
            y1 = y0 + 22  # wysokość głównego paska grupy

            # Etykieta grupy
            self.cal_canvas.create_text(10, y0 + 10, text=name_disp,
                                        fill=text_color, anchor="w", font=FONT_BODY)

            # Pasek grupy
            start_offset = (pg["start"] - min_date).days
            end_offset = (pg["end"] - min_date).days
            x0 = label_width + start_offset * day_width
            x1 = label_width + end_offset * day_width
            if x1 - x0 < 8:
                x1 = x0 + 8

            self.cal_canvas.create_rectangle(x0, y0, x1, y1,
                                             fill=bar_color, outline=outline_color, width=1)

            date_txt = f"{pg['start'].strftime('%d.%m.%y')} – {pg['end'].strftime('%d.%m.%y')}"
            self.cal_canvas.create_text(x1 + 10, y0 + 10, text=date_txt,
                                        fill=C["text_muted"], anchor="w", font=("Segoe UI", 7))

            if extended:
                g_tasks = tasks_by_group.get(pg["id"], [])
                if g_tasks:
                    y_cursor = self._build_extended_timeline(
                        pg, g_tasks, y1 + 4, min_date, now,
                        label_width, day_width, row_h,
                    )
                else:
                    # Brak zadań — pokaż info
                    self.cal_canvas.create_text(
                        label_width + 6, y1 + 10,
                        text="brak zadań w raporcie",
                        fill=C["text_muted"], anchor="w",
                        font=("Segoe UI", 7),
                    )
                    y_cursor = y1 + 24
            else:
                y_cursor += row_h

        # Separator między grupami
        # (rysowany jako cienka linia po każdym wierszu)
        # — już widoczny przez odstępy y_cursor

        label = (
            "Widok: Kalendarz aktywności — Rozszerzony (zadania)"
            if extended
            else (
                "Widok: Kalendarz aktywności (Najnowsze na górze)"
                if self._group_cal_sort_mode == "activity"
                else "Widok: Kalendarz aktywności (Chronologicznie)"
            )
        )
        self.view_label_var.set(label)
        self.count_var.set(
            f"{len(visible)} grup"
            if len(visible) == len(parsed_groups)
            else f"{len(visible)} z {len(parsed_groups)} grup"
        )


    def _build_extended_timeline(
            self,
            pg: dict,
            tasks: list,
            y_start: int,
            min_date,
            now,
            label_width: int,
            day_width: int,
            row_h: int,
    ) -> int:
        """
        Rysuje timeline grupy jako ciągły pasek segmentowy.

        Segmenty (odcienie zieleni):
          + zakończone  → ciemny zielony   #10B981
          = aktywne     → jasny zielony    #6EE7B7
          # przerwa     → czerwony         #EF4444  z etykietą dni

        Dane z API (tasks.task.list zwraca camelCase):
          createdDate  — start zadania
          closedDate   — koniec zadania zakończonego
          status       — "5"=zakończona, "4"=do kontroli, "3"=w trakcie
        """
        BAR_H = 18
        ROW_PAD = 10
        INDENT = 16

        # ── 1. Wyznacz przedziały każdego zadania ─────────────────────
        # tasks.task.list → camelCase; tasks_list.json może mieć oba
        def _get(task, *keys):
            """Pobiera wartość z task po pierwszym kluczu który istnieje."""
            for k in keys:
                v = task.get(k)
                if v:
                    return v
            return ""

        segments: list[tuple[int, int, str]] = []
        total_tasks = len(tasks)
        done_tasks = 0

        for task in tasks:
            # Status — camelCase API zwraca "status", REAL_STATUS z tasks.task.list
            # NOWE:
            status_raw = str(_get(task, "status", "REAL_STATUS") or "")
            closed_raw = _get(task, "closedDate", "CLOSED_DATE") or ""
            closed_dt = parse_to_aware_datetime(closed_raw) if closed_raw else None

            # Jeśli status dostępny — użyj go; jeśli nie — wnioskuj z closedDate
            if status_raw:
                is_done = status_raw in self._TASK_STATUS_DONE
                is_active = status_raw in self._TASK_STATUS_ACTIVE
            else:
                is_done = closed_dt is not None  # ma datę zamknięcia → zakończone
                is_active = not is_done  # brak daty zamknięcia → traktuj jako aktywne

            # DIAGNOSTYKA
            title_dbg = _get(task, "title", "TITLE", "name") or f"id={task.get('id', '?')}"
            closed_dbg = _get(task, "closedDate", "CLOSED_DATE") or "BRAK"
            activity_dbg = _get(task, "activityDate", "ACTIVITY_DATE") or "BRAK"
            # print(f"  [Task] '{str(title_dbg)[:40]}' status={status_raw!r} "
            #       f"is_done={is_done} closedDate={closed_dbg!r} activityDate={activity_dbg!r}")

            if is_done:
                done_tasks += 1

            # Data startu — createdDate (camelCase) lub CREATED_DATE
            raw_start = _get(task, "createdDate", "CREATED_DATE", "dateStart", "DATE_START")
            t_start = parse_to_aware_datetime(raw_start)
            if not t_start:
                continue

            if is_done:
                # closed_dt już mamy z góry, nie parsuj ponownie
                t_end = closed_dt or now
                kind = "done"
            elif is_active:
                t_end = now
                kind = "active"
            else:
                raw_end = _get(task, "activityDate", "ACTIVITY_DATE", "changedDate", "CHANGED_DATE")
                t_end = parse_to_aware_datetime(raw_end) or now
                kind = "other"

            s_off = max(0, (t_start - min_date).days)
            e_off = max(s_off + 1, (t_end - min_date).days)
            segments.append((s_off, e_off, kind))

        if not segments:
            self.cal_canvas.create_text(
                INDENT, y_start + 4,
                text="brak dat zadań",
                fill=C["text_muted"], anchor="w", font=("Segoe UI", 7),
            )
            return y_start + 20

        # ── 2. Mapa pokrycia dzień po dniu ────────────────────────────
        KIND_PRIORITY = {"done": 3, "active": 2, "other": 1}
        day_kind: dict[int, str] = {}

        for s_off, e_off, kind in segments:
            for d in range(s_off, e_off):
                if d not in day_kind or KIND_PRIORITY[kind] > KIND_PRIORITY.get(day_kind[d], 0):
                    day_kind[d] = kind

        if not day_kind:
            return y_start + 20

        # ── 3. Scal kolejne dni w bloki + wykryj przerwy ──────────────
        all_days = sorted(day_kind.keys())
        first_day = all_days[0]
        last_day = all_days[-1]

        full_coverage: list[tuple[int, int, str]] = []

        for d in range(first_day, last_day + 1):
            kind = day_kind.get(d, "gap")
            if not full_coverage or full_coverage[-1][2] != kind:
                full_coverage.append([d, d + 1, kind])
            else:
                full_coverage[-1][1] = d + 1  # rozszerz blok

        # ── 4. Kolory ─────────────────────────────────────────────────
        KIND_COLORS = {
            "done": ("#10B981", "#059669"),  # ciemny zielony
            "active": ("#6EE7B7", "#34D399"),  # jasny zielony
            "other": ("#A7F3D0", "#6EE7B7"),  # bardzo jasny
            "gap": ("#EF4444", "#B91C1C"),  # czerwony
        }

        # ── 5. Rysuj pełny pasek ──────────────────────────────────────
        bar_y0 = y_start
        bar_y1 = y_start + BAR_H

        for seg in full_coverage:
            s, e, kind = seg
            fill, outline = KIND_COLORS.get(kind, ("#475569", "#334155"))
            x0 = label_width + s * day_width
            x1 = label_width + e * day_width
            if x1 - x0 < 2:
                x1 = x0 + 2

            self.cal_canvas.create_rectangle(
                x0, bar_y0, x1, bar_y1,
                fill=fill, outline=outline, width=1,
            )

            # Etykieta dni przerwy
            if kind == "gap" and (x1 - x0) > 18:
                self.cal_canvas.create_text(
                    (x0 + x1) // 2, (bar_y0 + bar_y1) // 2,
                    text=f"{e - s}d",
                    fill="#fff", font=("Segoe UI", 6, "bold"), anchor="center",
                )

        # ── 6. Podsumowanie ───────────────────────────────────────────
        total_gap_days = sum(e - s for s, e, k in full_coverage if k == "gap")

        y_sum = bar_y1 + 3
        summary_color = "#10B981" if done_tasks == total_tasks else C["accent"]
        summary = f"✓ {done_tasks}/{total_tasks} zakończonych"
        if total_gap_days > 0:
            summary += f"   ⚠ przerwy: {total_gap_days} dni"

        self.cal_canvas.create_text(
            INDENT, y_sum,
            text=summary,
            fill=summary_color, anchor="w",
            font=("Segoe UI", 7, "bold"),
        )

        y_end = y_sum + 11

        # Separator
        self.cal_canvas.create_line(
            0, y_end + 2,
               label_width + (now - min_date).days * day_width + 100, y_end + 2,
            fill=C.get("card_border", "#334155"), dash=(1, 4),
        )

        return y_end + ROW_PAD

    # ==================================================================
    # Filtry
    # ==================================================================

    def on_status_change(self, _event=None) -> None:
        if self.current_group_view_id is None:
            self._reload_tasks_from_disk()
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
        prev_resp = self.current_resp_filter.get()
        workers: set = set()
        for task in self.all_fetched_tasks:
            resp = get_responsible(task)
            if resp:
                workers.add(resp)
            creator = get_creator(task)
            if creator:
                workers.add(creator)
            for p in self._extract_participants(task):
                workers.add(p)
        self.all_responsibles = ["Wszyscy"] + sorted(workers)
        self.resp_combobox.config(values=self.all_responsibles)
        if prev_resp in self.all_responsibles:
            self.current_resp_filter.set(prev_resp)
        else:
            self.current_resp_filter.set("Wszyscy")

    def apply_filter(self, _event=None) -> None:
        if self.current_view.get() != "tasks":
            return
        selected_status = self.current_filter.get()
        typed_worker    = self.current_resp_filter.get().strip().lower()
        search_term     = self.search_var.get().strip().lower()
        hide_inactive   = self.hide_inactive_var.get()
        threshold_date  = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d %H:%M")

        filtered: list = []
        for task in self.all_fetched_tasks:
            real_status  = str(task.get("REAL_STATUS") or task.get("status", ""))
            mapped       = STATUS_MAP.get(real_status, real_status)

            creator = get_creator(task)
            resp = get_responsible(task)
            participants = ", ".join(get_participants_names(task))

            worker_pool  = f"{resp} {creator} {participants}".lower()
            task_title   = (task.get("TITLE") or task.get("title", "")).lower()
            activity_str = format_date(task.get("ACTIVITY_DATE") or task.get("activityDate") or "")

            ok_status   = selected_status == "Wszystkie" or mapped == selected_status
            ok_title    = not search_term or search_term in task_title
            ok_worker   = typed_worker in ("wszyscy", "") or typed_worker in worker_pool
            ok_activity = not (hide_inactive and (not activity_str or activity_str < threshold_date))

            if ok_status and ok_worker and ok_title and ok_activity:
                filtered.append(task)

        mode = self.display_mode.get()
        if mode == "cards":
            self.view_label_var.set(f"⊞ Kafelki — {selected_status}")
            self._show_kanban(False)
            self._show_cards(filtered)
        elif mode == "kanban":
            self.view_label_var.set(f"⬛ Kanban — {selected_status}")
            self._show_kanban(True)
            self.kanban_view.load_tasks(filtered)
            self.count_var.set(f"{len(filtered)} zadań")
        else:
            self.view_label_var.set(f"☰ Lista — {selected_status}")
            self._show_kanban(False)
            self._show_tree()
            self.display_data(filtered)
        self._save_config()

    def reset_filters(self) -> None:
        self.current_group_view_id   = None
        self.current_group_view_name = None
        if self.display_mode.get() == "kanban":
            self._pre_kanban_filter = "W trakcie"
            self.current_filter.set("Wszystkie")
        else:
            self.current_filter.set("W trakcie")
        self.current_resp_filter.set("Wszyscy")
        self.search_var.set("")
        self.live_timer_var.set(False)
        self.hide_inactive_var.set(False)
        self._reload_tasks_from_disk()
        self.apply_filter()
        self._save_config()
        self.status_var.set("Zresetowano filtry i widok grupy.")

    # ==================================================================
    # Wyświetlanie danych (Treeview)
    # ==================================================================

    def display_data(self, tasks: list) -> None:
        selected_ids = [self.tree.item(i, "values")[0] for i in self.tree.selection()]
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.active_tree_timers.clear()

        for task in tasks:
            t_id       = task.get("ID") or task.get("id")
            title      = task.get("TITLE") or task.get("title")
            r_s        = str(task.get("REAL_STATUS") or task.get("status", ""))
            status_txt = STATUS_MAP.get(r_s, r_s)
            raw_time   = task.get("TIME_SPENT_IN_LOGS") or task.get("timeSpentInLogs")
            try:
                base_time = int(raw_time) if raw_time not in (None, "None", "null", "") else 0
            except (TypeError, ValueError):
                base_time = 0

            creator = get_creator(task)
            resp = get_responsible(task)
            participants = ", ".join(get_participants_names(task))

            deadline     = format_date(task.get("DEADLINE") or task.get("deadline"))
            created      = format_date(task.get("CREATED_DATE") or task.get("createdDate"))
            changed      = format_date(task.get("CHANGED_DATE") or task.get("changedDate"))
            status_chgd  = format_date(task.get("STATUS_CHANGED_DATE") or task.get("statusChangedDate"))
            g_id         = str(task.get("GROUP_ID") or task.get("groupId") or "")
            group_name   = self.groups_map.get(g_id, g_id) if g_id else ""
            raw_act      = task.get("ACTIVITY_DATE") or task.get("activityDate")
            activity_date = format_date(raw_act)


            item_id = self.tree.insert("", "end", values=(
                t_id, title, status_txt, seconds_to_readable(base_time),
                creator, resp, participants, deadline, created,
                activity_date, changed, status_chgd, group_name,
            ))

            if self.live_timer_var.get() and r_s == "3":
                act_dt = parse_to_aware_datetime(raw_act)
                if act_dt and act_dt.date() == datetime.now(timezone(timedelta(hours=1))).date():
                    self.active_tree_timers[item_id] = {
                        "base_time":   base_time,
                        "activity_dt": act_dt,
                        "resp":        resp,
                        "has_participants": bool(participants.strip())
                    }

        for item in self.tree.get_children():
            if self.tree.item(item, "values")[0] in selected_ids:
                self.tree.selection_add(item)

        self.sort_treeview("ACTIVITY_DATE", reverse=True)
        self.auto_fit_columns()
        self.count_var.set(f"{len(tasks)} zadań")

    def _run_live_timers(self, generation: int) -> None:
        if generation != self._ui_generation:
            return
        if self.current_view.get() == "tasks" and self.live_timer_var.get():
            now = datetime.now(timezone.utc)
            latest_for_resp = {}
            for item_id, data in self.active_tree_timers.items():
                if not data.get("has_participants"):
                    resp = data.get("resp")
                    dt   = data["activity_dt"]
                    if resp not in latest_for_resp or dt > latest_for_resp[resp]:
                        latest_for_resp[resp] = dt

            for item_id, data in self.active_tree_timers.items():
                if self.tree.exists(item_id):
                    should_tick = (
                        data.get("has_participants") or
                        data["activity_dt"] == latest_for_resp.get(data.get("resp"))
                    )
                    if should_tick:
                        elapsed = (now - data["activity_dt"]).total_seconds()
                        if elapsed > 0:
                            total = data["base_time"] + int(elapsed)
                            vals  = list(self.tree.item(item_id, "values"))
                            if vals:
                                vals[3] = seconds_to_readable(total)
                                self.tree.item(item_id, values=vals)

        self.root.after(1000, lambda: self._run_live_timers(generation))

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
    # Obsługa akcji
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
        # 1. Pobierz szczegóły zadania (sieć → lokalny fallback)
        task_data = {}
        try:
            task_data = self.api.fetch_task_detail(task_id)
        except Exception:
            task_data = self.storage.load_task_detail(task_id) or {}
            if not task_data:
                messagebox.showerror("Błąd", "Brak internetu i brak lokalnej kopii zadania.")
                return

        # 2. Wczytaj lokalne wiadomości czatu
        chat_id        = task_data.get("chatId") or task_data.get("CHAT_ID")
        local_messages = self.storage.load_chat_messages(chat_id) if chat_id else []

        # 3. Uzupełnij brakujących użytkowników
        self._check_and_fetch_missing_users(task_data, local_messages)

        # 4. Otwórz okno
        top_window = self.create_task_window()
        self._build_task_window_ui(top_window, task_data, local_messages, chat_id)

        # 5. Pobierz wiadomości czatu w tle
        if chat_id:
            chat_file = self.storage.chat_file_path(chat_id)
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

        header = tk.Frame(window, bg=C["sidebar"], pady=10, padx=14)
        header.pack(fill="x")
        tk.Frame(header, bg=STATUS_COLORS.get("W trakcie", C["accent"]), width=4).pack(
            side="left", fill="y", padx=(0, 12))
        tk.Label(header, text=f"#{t_id}", bg=C["sidebar"],
                 fg=C["text_muted"], font=FONT_SMALL).pack(anchor="w")
        tk.Label(header, text=title, bg=C["sidebar"], fg=C["text"], font=FONT_HEADING,
                 wraplength=800, justify="left").pack(anchor="w")
        tk.Frame(window, bg=C["accent"], height=2).pack(fill="x")

        outer = tk.Frame(window, bg=C["bg"])
        outer.pack(fill="both", expand=True)

        vsb    = ttk.Scrollbar(outer, orient="vertical")
        vsb.pack(side="right", fill="y")
        canvas = tk.Canvas(outer, bg=C["bg"], highlightthickness=0, yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.config(command=canvas.yview)

        main = tk.Frame(canvas, bg=C["bg"], padx=14, pady=12)
        cw   = canvas.create_window((0, 0), window=main, anchor="nw")

        main.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        window._scroll_canvas = canvas

        tk.Label(main, text="Opis zadania", bg=C["bg"],
                 fg=C["accent2"], font=FONT_TITLE).pack(anchor="w")
        desc_bg = tk.Frame(main, bg=C["card"], padx=10, pady=8,
                           highlightthickness=1, highlightbackground=C["card_border"])
        desc_bg.pack(fill="x", pady=(4, 12))

        desc_scroll = ttk.Scrollbar(desc_bg, orient="vertical")
        desc_scroll.pack(side="right", fill="y")
        desc_text = tk.Text(desc_bg, height=6, wrap="word",
                            bg=C["card"], fg=C["text"], font=FONT_BODY, bd=0,
                            relief="flat", insertbackground=C["text"],
                            yscrollcommand=desc_scroll.set)
        desc_text.pack(side="left", fill="x", expand=True)
        desc_scroll.config(command=desc_text.yview)
        desc_text.insert("1.0", task_data.get("description", "Brak opisu."))
        desc_text.config(state="disabled")
        desc_text.bind("<MouseWheel>", lambda e: desc_text.yview_scroll(
            int(-1 * (e.delta / 120)), "units") or "break")

        self._build_time_section(main, task_data, messages, window)
        self._build_chat_section(main, messages, chat_id, window)

    def _build_time_section(self, parent: tk.Frame, task_data: dict,
                            messages: list, window: tk.Toplevel) -> None:
        import re as _re
        time_lf = tk.LabelFrame(parent, text=" ⏱  Raport czasu pracy ",
                                bg=C["bg"], fg=C["accent"], font=FONT_TITLE,
                                padx=10, pady=8, bd=1, relief="groove")
        time_lf.pack(fill="x", pady=(0, 12))

        task_time  = int(task_data.get("TIME_SPENT_IN_LOGS") or
                         task_data.get("timeSpentInLogs") or 0)
        today_date = datetime.now(timezone(timedelta(hours=1))).date()

        user_sessions: dict = {}
        open_starts:   dict = {}

        for msg in reversed(messages):
            text     = msg.get("text", "")
            raw_date = msg.get("date")
            if not raw_date:
                continue
            try:
                dt_obj = datetime.fromisoformat(raw_date)
                dt = (dt_obj.astimezone(timezone(timedelta(hours=1)))
                      if dt_obj.tzinfo else
                      dt_obj.replace(tzinfo=timezone(timedelta(hours=1))))
            except Exception:
                continue

            start_m = _re.search(
                r"\[USER=\d+\](.*?)\[/USER\]\s+(?:włączył[a]?\s+śledzenie\s+czasu|enabled\s+personal\s+task\s+time\s+tracker)",
                text, _re.IGNORECASE)
            stop_m = _re.search(
                r"\[USER=\d+\](.*?)\[/USER\]\s+(?:wyłączył[a]?\s+śledzenie\s+czasu|stopped\s+task\s+time\s+tracker)",
                text, _re.IGNORECASE)
            finish_m = _re.search(
                r"(?:ukończył|zakończył)[a]?\s+zadanie|completed\s+the\s+task",
                text, _re.IGNORECASE)
            total_m = _re.search(
                r"total\s+task\s+time[:\s]",
                text, _re.IGNORECASE,
            )

            if start_m:
                user = start_m.group(1).strip()
                open_starts[user] = dt
                user_sessions.setdefault(user, []).append([dt, None])
            elif stop_m:
                user = stop_m.group(1).strip()
                for sess in reversed(user_sessions.get(user, [])):
                    if sess[1] is None:
                        sess[1] = dt
                        break
                open_starts.pop(user, None)
            elif finish_m or total_m:
                for user in list(open_starts.keys()):
                    for sess in reversed(user_sessions.get(user, [])):
                        if sess[1] is None:
                            sess[1] = dt
                            break
                open_starts.clear()

        tracker: dict = {}
        for user, sessions in user_sessions.items():
            if not sessions:
                continue
            total_elapsed = today_elapsed = 0.0
            is_active = False
            active_start = None
            daily_map: dict = {}

            for start_dt, stop_dt in sessions:
                if stop_dt is None:
                    is_active    = True
                    active_start = start_dt
                else:
                    elapsed = max(0.0, (stop_dt - start_dt).total_seconds())
                    total_elapsed += elapsed
                    day = start_dt.date()
                    daily_map[day] = daily_map.get(day, 0.0) + elapsed
                    if start_dt.date() == today_date or stop_dt.date() == today_date:
                        today_elapsed += elapsed

            tracker[user] = {
                "total":        total_elapsed,
                "today":        today_elapsed,
                "is_active":    is_active,
                "active_start": active_start,
                "daily_map":    daily_map,
            }

        total_time_var = tk.StringVar()
        tk.Label(time_lf, textvariable=total_time_var, bg=C["bg"],
                 fg=C["accent"], font=("Segoe UI Semibold", 12)).pack(anchor="w", pady=(0, 4))

        active_timers: dict = {}

        if not tracker and task_time == 0:
            total_time_var.set("Razem: 00:00:00")
            tk.Label(time_lf, text="Brak historii czasu.", bg=C["bg"],
                     fg=C["text_muted"], font=FONT_BODY).pack(anchor="w")
        else:
            for user, data in tracker.items():
                lbl_var = tk.StringVar()
                tk.Label(time_lf, textvariable=lbl_var, bg=C["bg"],
                         fg=C["text"], font=FONT_BODY).pack(anchor="w")
                is_act   = (data["is_active"] and data["active_start"] and
                            data["active_start"].date() == today_date)
                today_str = (f"  (dziś: {seconds_to_readable(data['today'])})"
                             if data["today"] > 0 else "")
                if is_act:
                    active_timers[user] = {
                        "total":    data["total"],
                        "today":    data["today"],
                        "start_dt": data["active_start"],
                        "var":      lbl_var,
                    }
                else:
                    lbl_var.set(f"👤 {user}  {seconds_to_readable(data['total'])}{today_str}")
            if not active_timers:
                total_time_var.set(f"Razem: {seconds_to_readable(task_time)}")

        if active_timers:
            self.update_live_timers(window, active_timers, total_time_var,
                                    task_time, window.current_cycle)

        has_daily = any(data["daily_map"] for data in tracker.values())
        if has_daily:
            toggle_var   = tk.BooleanVar(value=False)
            btn_row      = tk.Frame(time_lf, bg=C["bg"])
            btn_row.pack(anchor="w", pady=(6, 0))
            detail_frame = tk.Frame(time_lf, bg=C["bg"])

            def _toggle_details():
                if toggle_var.get():
                    detail_frame.pack(fill="x", pady=(6, 0))
                    btn_toggle.config(text="▲ Ukryj zestawienie dzienne")
                else:
                    detail_frame.pack_forget()
                    btn_toggle.config(text="▼ Pokaż zestawienie dzienne")
                try:
                    cv = getattr(window, "_scroll_canvas", None)
                    if cv:
                        cv.update_idletasks()
                        cv.configure(scrollregion=cv.bbox("all"))
                except Exception:
                    pass

            btn_toggle = tk.Button(
                btn_row, text="▼ Pokaż zestawienie dzienne",
                bg=C["sidebar"], fg=C["accent"],
                font=FONT_SMALL, relief="flat", bd=0, cursor="hand2",
                padx=8, pady=4,
                activebackground=C["card_hover"], activeforeground=C["accent"],
                command=lambda: (toggle_var.set(not toggle_var.get()), _toggle_details()),
            )
            btn_toggle.pack(side="left")
            self._build_daily_breakdown(detail_frame, tracker)

    def _build_daily_breakdown(self, parent: tk.Frame, tracker: dict) -> None:
        all_days: set = set()
        for data in tracker.values():
            all_days.update(data["daily_map"].keys())
        if not all_days:
            return

        sorted_days = sorted(all_days, reverse=True)
        users       = list(tracker.keys())
        show_sum    = len(users) > 1
        today       = datetime.now(timezone(timedelta(hours=1))).date()

        tk.Label(parent, text="📅 Zestawienie dzienne", bg=C["bg"],
                 fg=C["accent2"], font=FONT_TITLE).pack(anchor="w", pady=(0, 6))

        tbl = tk.Frame(parent, bg=C["bg"])
        tbl.pack(anchor="w")

        def cell(row, col, text, fg, bg=C["card"], bold=False):
            font = ("Segoe UI Semibold", 8) if bold else FONT_SMALL
            tk.Label(tbl, text=text, bg=bg, fg=fg, font=font,
                     width=13, anchor="center" if col > 0 else "w",
                     padx=6, pady=3,
                     highlightthickness=1, highlightbackground=C["card_border"],
                     ).grid(row=row, column=col, sticky="nsew", padx=(0, 1), pady=(0, 1))

        cell(0, 0, "Data", C["text_muted"], bold=True)
        for ci, u in enumerate(users, 1):
            disp = u if len(u) <= 16 else u[:13] + "…"
            cell(0, ci, disp, C["text_muted"], bold=True)
        if show_sum:
            cell(0, len(users) + 1, "Suma", C["accent"], bold=True)

        for ri, day in enumerate(sorted_days, 1):
            if day == today:
                day_str, day_fg, row_bg = f"Dziś  {day.strftime('%d.%m')}", C["accent"], C["card_hover"]
            elif day == today - timedelta(days=1):
                day_str, day_fg, row_bg = f"Wczoraj {day.strftime('%d.%m')}", C["text"], C["card"]
            else:
                day_str, day_fg, row_bg = day.strftime("%d.%m.%Y"), C["text_muted"], C["card"]

            cell(ri, 0, day_str, day_fg, row_bg)
            day_total = 0.0
            for ci, u in enumerate(users, 1):
                secs      = tracker[u]["daily_map"].get(day, 0.0)
                day_total += secs
                txt = seconds_to_readable(secs) if secs > 0 else "—"
                fg  = C["text"] if secs > 0 else C["text_muted"]
                tk.Label(tbl, text=txt, bg=row_bg, fg=fg,
                         font=FONT_MONO, width=13, anchor="center",
                         padx=6, pady=3,
                         highlightthickness=1, highlightbackground=C["card_border"],
                         ).grid(row=ri, column=ci, sticky="nsew", padx=(0, 1), pady=(0, 1))
            if show_sum:
                cell(ri, len(users) + 1, seconds_to_readable(day_total), C["accent"], row_bg)

        sr = len(sorted_days) + 1
        cell(sr, 0, "Łącznie", C["accent"], C["sidebar"], bold=True)
        grand = 0.0
        for ci, u in enumerate(users, 1):
            ut     = tracker[u]["total"]
            grand += ut
            cell(sr, ci, seconds_to_readable(ut), C["accent"], C["sidebar"], bold=True)
        if show_sum:
            cell(sr, len(users) + 1, seconds_to_readable(grand), C["btn_green"], C["sidebar"], bold=True)

    def _build_chat_section(self, parent: tk.Frame, messages: list,
                            chat_id, window: tk.Toplevel) -> None:
        hdr = f"💬 Wiadomości (Chat ID: {chat_id})" if chat_id else "💬 Wiadomości (brak czatu)"
        if not messages and chat_id:
            hdr += " — synchronizowanie..."
        tk.Label(parent, text=hdr, bg=C["bg"], fg=C["accent2"], font=FONT_TITLE).pack(anchor="w")

        chat_frame  = tk.Frame(parent, bg=C["bg"])
        chat_frame.pack(fill="both", expand=True, pady=(4, 0))
        chat_scroll = ttk.Scrollbar(chat_frame, orient="vertical")
        chat_scroll.pack(side="right", fill="y")
        chat_text   = tk.Text(chat_frame, wrap="word", yscrollcommand=chat_scroll.set,
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

    def bg_fetch_messages(self, task_data: dict, chat_id, chat_file: str,
                          window: tk.Toplevel) -> None:
        try:
            messages = self.api.fetch_chat_messages(chat_id, chat_file)
            if messages:
                self._check_and_fetch_missing_users(task_data, messages)
                self.root.after(0, lambda: self.reload_task_window(window, task_data, messages, chat_id))
        except requests.RequestException as e:
            print(f"Błąd pobierania wiadomości: {e}")

    # ==================================================================
    # Pomocnicze
    # ==================================================================

    def _extract_participants(self, task: dict) -> list[str]:
        return get_participants_names(task)

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
            threading.Thread(target=self._bg_fetch_users, daemon=True).start()