import os
import sys
import json
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import tkinter.font as tkfont
import requests
import time
from datetime import datetime, timezone, timedelta

# Konfiguracja zmiennych
WEBHOOK_URL = os.environ.get("BITRIX_WEBHOOK", "https://jenaeuropa.bitrix24.pl/rest/223/8cd46qmskggzo81m/")

STATUS_MAP = {
    "1": "Nowe",
    "2": "Oczekujące",
    "3": "W trakcie",
    "4": "Do kontroli",
    "5": "Zakończone",
    "6": "Odłożone"
}


def get_data_dir():
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    data_dir = os.path.join(base_dir, "bitrix_data")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.join(data_dir, "details"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "chats"), exist_ok=True)

    return data_dir


def seconds_to_readable(seconds):
    try:
        seconds = int(seconds)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02}:{minutes:02}:{secs:02}"
    except (ValueError, TypeError):
        return "00:00:00"


def format_date(date_string):
    if not date_string:
        return ""
    try:
        dt = datetime.fromisoformat(date_string)
        if dt.tzinfo is not None:
            target_tz = timezone(timedelta(hours=1))
            dt = dt.astimezone(target_tz)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        try:
            return datetime.fromisoformat(date_string.split("+")[0]).strftime("%Y-%m-%d %H:%M")
        except:
            return date_string


def parse_to_aware_datetime(date_string):
    """Zwraca obiekt datetime ze strefą czasową na potrzeby obliczeń czasu rzeczywistego."""
    if not date_string:
        return None
    try:
        dt = datetime.fromisoformat(date_string)
        if dt.tzinfo is None:
            # Jeśli brak strefy, zakładamy offset uzywany w programie (+1h)
            dt = dt.replace(tzinfo=timezone(timedelta(hours=1)))
        return dt
    except Exception:
        try:
            dt = datetime.fromisoformat(date_string.split("+")[0])
            dt = dt.replace(tzinfo=timezone(timedelta(hours=1)))
            return dt
        except:
            return None


class BitrixApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Bitrix Task & Group Viewer")
        self.root.geometry("1450x700")

        self.data_dir = get_data_dir()
        self.all_fetched_tasks = []
        self.all_fetched_groups = []
        self.all_responsibles = ["Wszyscy"]

        self.groups_map = {}
        self.users_map = {}

        self.current_view = tk.StringVar(value="tasks")
        self.current_filter = tk.StringVar(value="W trakcie")
        self.current_resp_filter = tk.StringVar(value="Wszyscy")
        self.search_var = tk.StringVar()
        self.activity_date_var = tk.StringVar()

        # Zmienne do śledzenia wybranej grupy (dla auto-odświeżania)
        self.current_group_view_id = None
        self.current_group_view_name = None

        # Flagi dla dodatkowych funkcji
        self.live_timer_var = tk.BooleanVar(value=False)
        self.hide_inactive_var = tk.BooleanVar(value=False)  # Flaga ukrywania starych zadań
        self.active_tree_timers = {}  # Przechowuje logikę stoperów w widoku Treeview

        # Flaga blokująca wielokrotne pobieranie
        self.is_fetching = False

        self.task_columns = (
            "ID", "TITLE", "REAL_STATUS", "TIME_SPENT",
            "CREATED_BY", "RESPONSIBLE", "PARTICIPANTS", "DEADLINE", "CREATED_DATE", "ACTIVITY_DATE",
            "CHANGED_DATE", "STATUS_CHANGED_DATE", "GROUP"
        )
        self.group_columns = ("ID", "NAME", "DESCRIPTION", "OWNER_ID", "DATE_CREATE", "DATE_ACTIVITY")

        self.create_widgets()
        self.load_local_data()

        # Uruchomienie pętli odświeżającej czas w tabeli co sekundę
        self._run_live_timers()

        # Uruchomienie cyklicznego odświeżania danych co 5 minut (300 000 ms)
        self._schedule_auto_refresh()

    def create_widgets(self):
        mode_frame = tk.Frame(self.root, bg="#e0e0e0", pady=5)
        mode_frame.pack(fill="x")

        tk.Label(mode_frame, text="Wyświetlaj:", bg="#e0e0e0", font=("Arial", 10, "bold")).pack(side="left",
                                                                                                padx=(10, 5))
        tk.Radiobutton(mode_frame, text="Zadania", variable=self.current_view, value="tasks", command=self.switch_view,
                       bg="#e0e0e0").pack(side="left")
        tk.Radiobutton(mode_frame, text="Grupy robocze", variable=self.current_view, value="groups",
                       command=self.switch_view, bg="#e0e0e0").pack(side="left", padx=10)

        # Checkbox do liczenia czasu na żywo
        tk.Checkbutton(mode_frame, text="Licz czas na żywo",
                       variable=self.live_timer_var, command=self.apply_filter,
                       bg="#e0e0e0").pack(side="left", padx=(10, 5))

        # Nowy Checkbox do ukrywania zadań nieaktywnych od tygodnia
        tk.Checkbutton(mode_frame, text="Ukryj 'W trakcie' nieaktywne > 7 dni",
                       variable=self.hide_inactive_var, command=self.apply_filter,
                       bg="#e0e0e0").pack(side="left", padx=(5, 10))

        frame_top = tk.Frame(self.root)
        frame_top.pack(pady=10, fill="x", padx=10)

        self.btn_frame = tk.Frame(frame_top)
        self.btn_frame.pack(side="left")

        self.btn_fetch = tk.Button(self.btn_frame, text="Pobierz / Odśwież zadania", command=self.fetch_data, width=25,
                                   bg="#4CAF50", fg="white")
        self.btn_fetch.grid(row=0, column=0, padx=5)

        self.btn_action = tk.Button(self.btn_frame, text="Otwórz zadanie", command=self.handle_main_action, width=20,
                                    bg="#2196F3", fg="white")
        self.btn_action.grid(row=0, column=1, padx=5)

        # Dodanie etykiety statusu obok przycisków
        self.status_var = tk.StringVar(value="")
        self.status_label = tk.Label(self.btn_frame, textvariable=self.status_var, fg="#0052cc",
                                     font=("Arial", 10, "italic"))
        self.status_label.grid(row=0, column=2, padx=10)

        self.filter_frame = tk.Frame(frame_top)
        self.filter_frame.pack(side="right")

        tk.Label(self.filter_frame, text="Status:").grid(row=0, column=0, padx=(10, 2))
        filter_options = ["Wszystkie"] + list(STATUS_MAP.values())
        self.status_combobox = ttk.Combobox(self.filter_frame, textvariable=self.current_filter, values=filter_options,
                                            state="readonly", width=15)
        self.status_combobox.grid(row=0, column=1, padx=2)

        self.status_combobox.bind("<<ComboboxSelected>>", self.on_status_change)

        # Zmiana etykiety na "Pracownik"
        tk.Label(self.filter_frame, text="Pracownik:").grid(row=0, column=2, padx=(15, 2))
        self.resp_combobox = ttk.Combobox(self.filter_frame, textvariable=self.current_resp_filter, values=["Wszyscy"],
                                          width=20)
        self.resp_combobox.grid(row=0, column=3, padx=2)
        self.resp_combobox.bind("<<ComboboxSelected>>", self.apply_filter)
        self.resp_combobox.bind("<KeyRelease>", self.on_resp_type)

        tk.Label(self.filter_frame, text="Szukaj (tytuł):").grid(row=0, column=4, padx=(15, 2))
        self.search_entry = tk.Entry(self.filter_frame, textvariable=self.search_var, width=25)
        self.search_entry.grid(row=0, column=5, padx=2)
        self.search_entry.bind("<KeyRelease>", self.apply_filter)

        tree_frame = tk.Frame(self.root)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=10)

        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical")
        tree_scroll.pack(side="right", fill="y")

        tree_scroll_x = ttk.Scrollbar(tree_frame, orient="horizontal")
        tree_scroll_x.pack(side="bottom", fill="x")

        self.tree = ttk.Treeview(tree_frame, columns=self.task_columns, show="headings", yscrollcommand=tree_scroll.set,
                                 xscrollcommand=tree_scroll_x.set)

        tree_scroll.config(command=self.tree.yview)
        tree_scroll_x.config(command=self.tree.xview)

        for col in self.task_columns:
            self.tree.heading(col, text=col, command=lambda _col=col: self.sort_treeview(_col, False))
            self.tree.column(col, width=100)

        self.tree.pack(side="left", fill="both", expand=True)

    def on_status_change(self, event=None):
        """Ładuje dane z odpowiedniego pliku jeśli to możliwe, a następnie odświeża widok."""
        if self.current_group_view_id is None:
            self.load_tasks_from_file_based_on_filter()
        self.apply_filter()

    def load_tasks_from_file_based_on_filter(self):
        """Załaduj plik na podstawie wybranego statusu."""
        selected_status = self.current_filter.get()
        if selected_status == "W trakcie":
            file_name = "tasks_in_progress.json"
        else:
            file_name = "tasks_list.json"

        file_path = os.path.join(self.data_dir, file_name)
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self.all_fetched_tasks = json.load(f)
                self.update_resp_filter_options()
            except Exception as e:
                print(f"Nie udało się wczytać zadań z {file_path}: {e}")
                self.all_fetched_tasks = []
        else:
            self.all_fetched_tasks = []

    def auto_fit_columns(self):
        font = tkfont.nametofont("TkDefaultFont")
        columns = self.tree["columns"]

        for col in columns:
            max_width = font.measure(col) + 30
            for item in self.tree.get_children():
                val = self.tree.set(item, col)
                if val:
                    val_width = font.measure(str(val)) + 30
                    if val_width > max_width:
                        max_width = val_width

            if col in ["TITLE", "NAME", "DESCRIPTION", "GROUP"]:
                max_width = min(max_width, 500)
                self.tree.column(col, width=max_width, minwidth=max_width, stretch=True)
            else:
                max_width = min(max_width, 250)
                self.tree.column(col, width=max_width, minwidth=max_width, stretch=False)

    def switch_view(self):
        mode = self.current_view.get()

        for row in self.tree.get_children():
            self.tree.delete(row)

        self.active_tree_timers.clear()

        if mode == "tasks":
            self.btn_fetch.config(text="Pobierz / Odśwież zadania")
            self.btn_action.config(text="Otwórz zadanie")
            self.filter_frame.pack(side="right")

            self.tree.config(columns=self.task_columns)
            for col in self.task_columns:
                self.tree.heading(col, text=col, command=lambda _col=col: self.sort_treeview(_col, False))

            self.apply_filter()

        elif mode == "groups":
            self.btn_fetch.config(text="Pobierz / Odśwież grupy")
            self.btn_action.config(text="Otwórz / Filtruj zadania")
            self.filter_frame.pack_forget()

            self.tree.config(columns=self.group_columns)
            for col in self.group_columns:
                self.tree.heading(col, text=col, command=lambda _col=col: self.sort_treeview(_col, False))

            self.display_groups(self.all_fetched_groups)

    def build_groups_map(self):
        self.groups_map = {str(g.get("ID")): g.get("NAME") for g in self.all_fetched_groups}

    def fetch_all_users(self):
        full_url = f"{WEBHOOK_URL}user.get.json"
        all_users = {}
        start = 0

        try:
            while True:
                response = requests.get(f"{full_url}?start={start}", timeout=10)
                response.raise_for_status()
                data = response.json()

                if "result" not in data:
                    break

                for u in data["result"]:
                    uid = str(u.get("ID"))
                    name = f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip()
                    all_users[uid] = name

                if "next" in data:
                    start = data["next"]
                else:
                    break

            self.users_map = all_users
            users_path = os.path.join(self.data_dir, "users_list.json")
            with open(users_path, "w", encoding="utf-8") as f:
                json.dump(all_users, f, ensure_ascii=False, indent=4)

        except requests.exceptions.RequestException as e:
            print(f"Nie udało się pobrać użytkowników: {e}")

    def load_local_data(self):
        groups_path = os.path.join(self.data_dir, "groups_list.json")
        if os.path.exists(groups_path):
            try:
                with open(groups_path, "r", encoding="utf-8") as f:
                    self.all_fetched_groups = json.load(f)
                self.build_groups_map()
            except Exception as e:
                print(f"Nie udało się wczytać grup: {e}")

        self.load_tasks_from_file_based_on_filter()

        users_path = os.path.join(self.data_dir, "users_list.json")
        if os.path.exists(users_path):
            try:
                with open(users_path, "r", encoding="utf-8") as f:
                    self.users_map = json.load(f)
            except Exception as e:
                self.fetch_all_users()
        else:
            self.fetch_all_users()

        self.switch_view()

    def sort_treeview(self, col, reverse):
        data = [(self.tree.set(child, col), child) for child in self.tree.get_children("")]

        def custom_sort(item):
            val = item[0]
            if not val:
                return (4 if reverse else 0, "")
            if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", val):
                return (1, val)
            try:
                if col == "TIME_SPENT" and val.count(':') == 2:
                    parts = val.split(':')
                    return (2, int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]))
                return (2, float(val))
            except ValueError:
                return (3, val.lower())

        data.sort(key=custom_sort, reverse=reverse)
        for index, (_, child) in enumerate(data):
            self.tree.move(child, "", index)
        self.tree.heading(col, command=lambda _col=col: self.sort_treeview(_col, not reverse))

    def _schedule_auto_refresh(self):
        self.root.after(300000, self._auto_refresh_trigger)

    def _auto_refresh_trigger(self):
        if not self.is_fetching:
            mode = self.current_view.get()
            if mode == "tasks":
                if self.current_group_view_id:
                    self.is_fetching = True
                    self._toggle_buttons_state("disabled")
                    self.status_var.set(f"Automatyczne odświeżanie zadań grupy w tle...")
                    threading.Thread(
                        target=self._bg_filter_tasks_by_group,
                        args=(self.current_group_view_id, self.current_group_view_name, True),
                        daemon=True
                    ).start()
                else:
                    self.fetch_data(is_auto=True)
            elif mode == "groups":
                self.fetch_data(is_auto=True)

        self._schedule_auto_refresh()

    def fetch_data(self, is_auto=False):
        if self.is_fetching:
            return

        mode = self.current_view.get()
        self.is_fetching = True
        self._toggle_buttons_state("disabled")

        if mode == "tasks":
            if not is_auto:
                self.current_group_view_id = None
                self.current_group_view_name = None

            self.status_var.set(
                "Automatyczne odświeżanie zadań w tle..." if is_auto else "Inicjowanie pobierania zadań...")
            threading.Thread(target=self._bg_fetch_all_tasks, args=(is_auto,), daemon=True).start()

        elif mode == "groups":
            self.status_var.set(
                "Automatyczne odświeżanie grup w tle..." if is_auto else "Inicjowanie pobierania grup...")
            threading.Thread(target=self._bg_fetch_all_groups, args=(is_auto,), daemon=True).start()

    def _toggle_buttons_state(self, state):
        self.btn_fetch.config(state=state)
        self.btn_action.config(state=state)

    def _reset_fetch_status(self, message, success=True):
        self.is_fetching = False
        self._toggle_buttons_state("normal")
        self.status_var.set(message)
        self.root.after(4000, lambda: self.status_var.set(""))

    def _bg_fetch_all_groups(self, is_auto=False):
        full_url = f"{WEBHOOK_URL}sonet_group.get.json"
        all_groups = []
        start = 0

        try:
            while True:
                response = requests.get(f"{full_url}?start={start}", timeout=10)
                response.raise_for_status()
                data = response.json()

                if "result" not in data:
                    break

                groups = data["result"]
                all_groups.extend(groups)

                status_msg = f"Odświeżono w tle {len(all_groups)} grup..." if is_auto else f"Pobrano {len(all_groups)} grup..."
                self.root.after(0, lambda msg=status_msg: self.status_var.set(msg))

                if "next" in data:
                    start = data["next"]
                else:
                    break

            file_path = os.path.join(self.data_dir, "groups_list.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(all_groups, f, ensure_ascii=False, indent=4)

            self.root.after(0, self._on_fetch_groups_success, all_groups, is_auto)

        except requests.exceptions.RequestException as e:
            self.root.after(0, self._on_fetch_error, e, "grup")

    def _on_fetch_groups_success(self, all_groups, is_auto=False):
        self.all_fetched_groups = all_groups
        self.build_groups_map()
        self.display_groups(all_groups)

        if is_auto:
            self._reset_fetch_status(f"Zakończono automatyczne odświeżanie ({datetime.now().strftime('%H:%M')}).")
        else:
            self._reset_fetch_status("Pomyślnie pobrano grupy.")
            messagebox.showinfo("Sukces", "Pobrano i zapisano grupy robocze.")

    def _bg_fetch_all_tasks(self, is_auto=False):
        current_status = self.current_filter.get()
        if current_status == "W trakcie":
            self._fetch_in_progress_tasks(is_auto)
        else:
            self._fetch_standard_tasks(is_auto)

    def _fetch_in_progress_tasks(self, is_auto):
        full_url = f"{WEBHOOK_URL}tasks.task.list"
        all_tasks = []
        start = 0
        date_str = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00+01:00")

        try:
            while True:
                params = {
                    "filter[REAL_STATUS]": 3,
                    "filter[>=ACTIVITY_DATE]": date_str,
                    "start": start
                }

                response = requests.get(full_url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()

                if "result" not in data or not data["result"]:
                    break

                tasks = data["result"].get("tasks", [])
                all_tasks.extend(tasks)

                status_msg = f"Odświeżono w tle {len(all_tasks)} zadań 'W trakcie'..." if is_auto else f"Pobrano {len(all_tasks)} zadań 'W trakcie'..."
                self.root.after(0, lambda msg=status_msg: self.status_var.set(msg))

                if "next" in data:
                    start = data["next"]
                else:
                    break

            file_path = os.path.join(self.data_dir, "tasks_in_progress.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(all_tasks, f, ensure_ascii=False, indent=4)

            self.root.after(0, self._on_fetch_tasks_success, all_tasks, is_auto)

        except requests.exceptions.RequestException as e:
            self.root.after(0, self._on_fetch_error, e, "zadań 'W trakcie'")

    def _fetch_standard_tasks(self, is_auto):
        full_url = f"{WEBHOOK_URL}task.item.list.json"
        all_tasks = []
        start = 0

        try:
            while True:
                response = requests.get(f"{full_url}?start={start}", timeout=10)
                response.raise_for_status()
                data = response.json()

                if "result" not in data:
                    break

                tasks = data["result"]
                all_tasks.extend(tasks)

                status_msg = f"Odświeżono w tle {len(all_tasks)} zadań..." if is_auto else f"Pobrano {len(all_tasks)} zadań..."
                self.root.after(0, lambda msg=status_msg: self.status_var.set(msg))

                if "next" in data:
                    start = data["next"]
                else:
                    break

            file_path = os.path.join(self.data_dir, "tasks_list.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(all_tasks, f, ensure_ascii=False, indent=4)

            self.root.after(0, self._on_fetch_tasks_success, all_tasks, is_auto)

        except requests.exceptions.RequestException as e:
            self.root.after(0, self._on_fetch_error, e, "zadań")

    def _on_fetch_tasks_success(self, all_tasks, is_auto=False):
        self.all_fetched_tasks = all_tasks
        self.update_resp_filter_options()
        self.apply_filter()

        if is_auto:
            self._reset_fetch_status(f"Zakończono automatyczne odświeżanie ({datetime.now().strftime('%H:%M')}).")
        else:
            self._reset_fetch_status("Pomyślnie pobrano zadania.")
            messagebox.showinfo("Sukces", "Zakończono i zapisano pobieranie.")

    def _on_fetch_error(self, e, category):
        self._reset_fetch_status("Wystąpił błąd pobierania.", success=False)
        messagebox.showwarning("Tryb Offline",
                               f"Nie udało się pobrać {category}. Przeglądasz dane zapisane lokalnie.\nSzczegóły błędu: {e}")

    def display_groups(self, groups):
        if self.current_view.get() != "groups":
            return

        selected_ids = [self.tree.item(item, "values")[0] for item in self.tree.selection()]

        for row in self.tree.get_children():
            self.tree.delete(row)

        for group in groups:
            self.tree.insert("", "end", values=(
                group.get("ID"),
                group.get("NAME"),
                group.get("DESCRIPTION"),
                group.get("OWNER_ID"),
                format_date(group.get("DATE_CREATE")),
                format_date(group.get("DATE_ACTIVITY"))
            ))

        for item in self.tree.get_children():
            if self.tree.item(item, "values")[0] in selected_ids:
                self.tree.selection_add(item)

        self.sort_treeview("DATE_ACTIVITY", reverse=True)
        self.auto_fit_columns()

    def handle_main_action(self):
        mode = self.current_view.get()
        if mode == "tasks":
            self.open_task()
        elif mode == "groups":
            self.filter_tasks_by_group()

    def filter_tasks_by_group(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Uwaga", "Proszę wybrać grupę z tabeli.")
            return

        if self.is_fetching:
            return

        item_values = self.tree.item(selected_item[0], "values")
        group_id = item_values[0]
        group_name = item_values[1]

        self.current_group_view_id = group_id
        self.current_group_view_name = group_name

        self.is_fetching = True
        self._toggle_buttons_state("disabled")
        self.status_var.set(f"Pobieranie zadań grupy: {group_name}...")
        threading.Thread(target=self._bg_filter_tasks_by_group, args=(group_id, group_name), daemon=True).start()

    def _bg_filter_tasks_by_group(self, group_id, group_name, is_auto=False):
        full_url = f"{WEBHOOK_URL}tasks.task.list.json?filter[GROUP_ID]={group_id}"
        group_tasks = []
        start = 0

        try:
            while True:
                response = requests.get(f"{full_url}&start={start}", timeout=10)
                response.raise_for_status()
                data = response.json()

                if "result" not in data or not data["result"]:
                    break

                tasks = data["result"].get("tasks", [])
                group_tasks.extend(tasks)

                status_msg = f"Odświeżono w tle {len(group_tasks)} zadań grupy..." if is_auto else f"Pobrano {len(group_tasks)} zadań grupy..."
                self.root.after(0, lambda msg=status_msg: self.status_var.set(msg))

                if "next" in data:
                    start = data["next"]
                else:
                    break

            self.root.after(0, self._on_filter_tasks_success, group_tasks, group_name, is_auto)

        except Exception as e:
            self.root.after(0, self._on_filter_tasks_error, e, group_name)

    def _on_filter_tasks_success(self, group_tasks, group_name, is_auto=False):
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
            self._reset_fetch_status(f"Zakończono automatyczne odświeżanie ({datetime.now().strftime('%H:%M')}).")
        else:
            self._reset_fetch_status("Pobrano zadania dla grupy.")
            messagebox.showinfo("Sukces", f"Wyświetlono zadania dla projektu: {group_name}")

    def _on_filter_tasks_error(self, e, group_name):
        self._reset_fetch_status("Błąd pobierania zadań grupy.", success=False)
        messagebox.showerror("Błąd", f"Nie udało się pobrać zadań dla {group_name}:\n{str(e)}")

    def _extract_participants(self, task):
        """Metoda pomocnicza: wyciąga wszystkich uczestników jako listę stringów"""
        participants_list = []
        for key in ["accomplicesData"]:
            data = task.get(key)
            if isinstance(data, dict):
                for uid, udata in data.items():
                    if isinstance(udata, dict) and udata.get("name"):
                        participants_list.append(udata.get("name"))
            elif isinstance(data, list):
                for udata in data:
                    if isinstance(udata, dict) and udata.get("name"):
                        participants_list.append(udata.get("name"))
        return participants_list

    def update_resp_filter_options(self):
        """Zbiera wszystkich możliwych pracowników zaangażowanych w zadania (twórca, odpowiedialny, uczestnicy)"""
        all_workers = set()

        for task in self.all_fetched_tasks:
            # 1. Odpowiedzialny
            resp_name = f"{task.get('RESPONSIBLE_NAME', '')} {task.get('RESPONSIBLE_LAST_NAME', '')}".strip()
            if not resp_name and 'responsible' in task:
                resp = task['responsible']
                resp_name = f"{resp.get('name', '')} {resp.get('lastName', '')}".strip()
            if resp_name:
                all_workers.add(resp_name)

            # 2. Twórca (Created by)
            c_by = f"{task.get('CREATED_BY_NAME', '')} {task.get('CREATED_BY_LAST_NAME', '')}".strip()
            if not c_by and 'creator' in task:
                c_by = f"{task['creator'].get('name', '')} {task['creator'].get('lastName', '')}".strip()
            if c_by:
                all_workers.add(c_by)

            # 3. Uczestnicy
            for p_name in self._extract_participants(task):
                all_workers.add(p_name)

        self.all_responsibles = ["Wszyscy"] + sorted(list(all_workers))
        self.resp_combobox.config(values=self.all_responsibles)
        self.current_resp_filter.set("Wszyscy")

    def on_resp_type(self, event):
        if event.keysym in ("Up", "Down", "Left", "Right", "Return", "Tab"):
            return
        typed_text = self.current_resp_filter.get().lower()

        if not typed_text:
            self.resp_combobox.config(values=self.all_responsibles)
        else:
            suggestions = [name for name in self.all_responsibles if typed_text in name.lower()]
            self.resp_combobox.config(values=suggestions)
        self.apply_filter()

    def apply_filter(self, event=None):
        if self.current_view.get() != "tasks":
            return

        selected_status = self.current_filter.get()
        typed_worker = self.current_resp_filter.get().strip().lower()
        search_term = self.search_var.get().strip().lower()
        filter_date = self.activity_date_var.get().strip()

        hide_inactive = self.hide_inactive_var.get()
        threshold_date_str = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")

        filtered_tasks = []
        for task in self.all_fetched_tasks:
            real_status = str(task.get("REAL_STATUS") or task.get("status", ""))
            mapped_status = STATUS_MAP.get(real_status, real_status)

            # Zbieramy wszystkie powiązane z zadaniem osoby w jeden ciąg znaków (do weryfikacji filtra)
            resp_name = f"{task.get('RESPONSIBLE_NAME', '')} {task.get('RESPONSIBLE_LAST_NAME', '')}".strip()
            if not resp_name and 'responsible' in task:
                resp = task['responsible']
                resp_name = f"{resp.get('name', '')} {resp.get('lastName', '')}".strip()

            c_by = f"{task.get('CREATED_BY_NAME', '')} {task.get('CREATED_BY_LAST_NAME', '')}".strip()
            if not c_by and 'creator' in task:
                c_by = f"{task['creator'].get('name', '')} {task['creator'].get('lastName', '')}".strip()

            participants_str = " ".join(self._extract_participants(task))

            # Łączymy w jedną "pulę" do przeszukiwania
            worker_pool_str = f"{resp_name} {c_by} {participants_str}".lower()

            task_title = (task.get("TITLE") or task.get("title", "")).lower()
            activity_date_str = format_date(task.get("ACTIVITY_DATE") or task.get("activityDate") or "")

            match_status = (selected_status == "Wszystkie" or mapped_status == selected_status)
            match_title = (not search_term) or (search_term in task_title)

            # Nowy warunek uwzględniający każdego pracownika podpiętego pod zadanie
            match_worker = True if typed_worker in ("wszyscy", "") else (typed_worker in worker_pool_str)

            match_activity = True
            if filter_date and len(filter_date) >= 4:
                match_activity = activity_date_str >= filter_date

            if hide_inactive and real_status == "3":
                if not activity_date_str or activity_date_str < threshold_date_str:
                    match_activity = False

            if match_status and match_worker and match_title and match_activity:
                filtered_tasks.append(task)

        self.display_data(filtered_tasks)

    def display_data(self, tasks):
        selected_ids = [self.tree.item(item, "values")[0] for item in self.tree.selection()]

        for row in self.tree.get_children():
            self.tree.delete(row)

        self.active_tree_timers.clear()

        for task in tasks:
            t_id = task.get("ID") or task.get("id")
            title = task.get("TITLE") or task.get("title")

            r_status = str(task.get("REAL_STATUS") or task.get("status", ""))
            real_status_text = STATUS_MAP.get(r_status, r_status)

            raw_time = task.get("TIME_SPENT_IN_LOGS") or task.get("timeSpentInLogs")
            try:
                base_time_spent = int(raw_time) if raw_time not in (None, "None", "null", "") else 0
            except (ValueError, TypeError):
                base_time_spent = 0

            c_by = f"{task.get('CREATED_BY_NAME', '')} {task.get('CREATED_BY_LAST_NAME', '')}".strip()
            if not c_by and 'creator' in task:
                c_by = f"{task['creator'].get('name', '')} {task['creator'].get('lastName', '')}".strip()

            resp = f"{task.get('RESPONSIBLE_NAME', '')} {task.get('RESPONSIBLE_LAST_NAME', '')}".strip()
            if not resp and 'responsible' in task:
                resp = f"{task['responsible'].get('name', '')} {task['responsible'].get('lastName', '')}".strip()

            deadline = format_date(task.get("DEADLINE") or task.get("deadline"))
            created = format_date(task.get("CREATED_DATE") or task.get("createdDate"))
            changed = format_date(task.get("CHANGED_DATE") or task.get("changedDate"))
            status_changed = format_date(task.get("STATUS_CHANGED_DATE") or task.get("statusChangedDate"))

            g_id = str(task.get("GROUP_ID") or task.get("groupId") or "")
            group_name = self.groups_map.get(g_id, g_id) if g_id else ""

            raw_activity_date = task.get("ACTIVITY_DATE") or task.get("activityDate")
            activity_date = format_date(raw_activity_date)

            time_spent_str = seconds_to_readable(base_time_spent)

            # Używamy nowej metody pomocniczej
            participants_str = ", ".join(self._extract_participants(task))

            item_id = self.tree.insert("", "end", values=(
                t_id, title, real_status_text, time_spent_str,
                c_by, resp, participants_str, deadline, created, changed, status_changed, activity_date, group_name
            ))

            if self.live_timer_var.get() and r_status == "3":
                act_dt = parse_to_aware_datetime(raw_activity_date)
                if act_dt:
                    self.active_tree_timers[item_id] = {
                        "base_time": base_time_spent,
                        "activity_dt": act_dt
                    }

        for item in self.tree.get_children():
            if self.tree.item(item, "values")[0] in selected_ids:
                self.tree.selection_add(item)

        if self.current_view.get() == "tasks":
            self.sort_treeview("ACTIVITY_DATE", reverse=True)
        self.auto_fit_columns()

    def _run_live_timers(self):
        if self.current_view.get() == "tasks" and self.live_timer_var.get():
            now = datetime.now(timezone.utc)
            for item_id, data in self.active_tree_timers.items():
                if self.tree.exists(item_id):
                    elapsed = (now - data["activity_dt"]).total_seconds()
                    if elapsed > 0:
                        total_time = data["base_time"] + int(elapsed)
                        current_values = list(self.tree.item(item_id, "values"))
                        if current_values:
                            current_values[3] = seconds_to_readable(total_time)
                            self.tree.item(item_id, values=current_values)

        self.root.after(1000, self._run_live_timers)

    def _check_and_fetch_missing_users(self, task_data, messages):
        required_ids = set()
        if task_data.get("createdBy"): required_ids.add(str(task_data.get("createdBy")))
        if task_data.get("responsibleId"): required_ids.add(str(task_data.get("responsibleId")))

        for msg in messages:
            if msg.get("author_id"):
                required_ids.add(str(msg.get("author_id")))

        missing_ids = [uid for uid in required_ids if uid not in self.users_map and uid != "0"]
        if missing_ids:
            self.fetch_all_users()

    def open_task(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Uwaga", "Proszę wybrać zadanie z tabeli.")
            return

        item_values = self.tree.item(selected_item[0], "values")
        task_id = item_values[0]

        task_file_path = os.path.join(self.data_dir, "details", f"task_{task_id}.json")
        task_data = {}

        try:
            task_resp = requests.get(f"{WEBHOOK_URL}tasks.task.get?taskId={task_id}", timeout=5)
            task_resp.raise_for_status()
            task_data = task_resp.json().get("result", {}).get("task", {})
            if task_data:
                with open(task_file_path, "w", encoding="utf-8") as f:
                    json.dump(task_data, f, ensure_ascii=False, indent=4)
        except Exception:
            if os.path.exists(task_file_path):
                with open(task_file_path, "r", encoding="utf-8") as f:
                    task_data = json.load(f)
            else:
                messagebox.showerror("Błąd", "Brak internetu i brak lokalnej kopii zadania.")
                return

        chat_id = task_data.get("chatId") or task_data.get("CHAT_ID")
        chat_file_path = os.path.join(self.data_dir, "chats", f"chat_{chat_id}.json") if chat_id else None

        local_messages = []

        if chat_file_path and os.path.exists(chat_file_path):
            try:
                with open(chat_file_path, "r", encoding="utf-8") as f:
                    local_messages = json.load(f)
            except Exception:
                pass

        self._check_and_fetch_missing_users(task_data, local_messages)

        top_window = self.create_task_window()
        self._build_task_window_ui(top_window, task_data, local_messages, chat_id)

        if chat_id:
            thread = threading.Thread(target=self.bg_fetch_messages,
                                      args=(task_data, chat_id, chat_file_path, top_window), daemon=True)
            thread.start()

    def bg_fetch_messages(self, task_data, chat_id, chat_file_path, window):
        messages = []
        last_id = None
        current_timeout = 5

        try:
            while True:
                url = f"{WEBHOOK_URL}im.dialog.messages.get?DIALOG_ID=chat{chat_id}&LIMIT=50"
                if last_id is not None:
                    url += f"&LAST_ID={last_id}"

                try:
                    chat_resp = requests.get(url, timeout=current_timeout)
                    chat_resp.raise_for_status()
                    chat_data_json = chat_resp.json()

                    fetched_messages = chat_data_json.get("result", {}).get("messages", [])

                    if not fetched_messages:
                        break

                    messages.extend(fetched_messages)

                    valid_ids = [msg.get("id") for msg in fetched_messages if msg.get("id")]
                    if not valid_ids:
                        break

                    last_id = min(valid_ids)
                    time.sleep(0.5)
                    current_timeout = 5

                except requests.exceptions.Timeout:
                    current_timeout += 10
                    if current_timeout > 45:
                        break
                    time.sleep(1)

            if messages:
                with open(chat_file_path, "w", encoding="utf-8") as f:
                    json.dump(messages, f, ensure_ascii=False, indent=4)

                self._check_and_fetch_missing_users(task_data, messages)
                self.root.after(0, lambda: self.reload_task_window(window, task_data, messages, chat_id))

        except requests.exceptions.RequestException as e:
            print(f"Błąd podczas pobierania wiadomości czatu w tle: {e}")

    def create_task_window(self):
        top = tk.Toplevel(self.root)
        top.geometry("900x700")
        top.current_cycle = 0
        return top

    def reload_task_window(self, window, task_data, messages, chat_id):
        if not window.winfo_exists():
            return

        window.current_cycle += 1

        for widget in window.winfo_children():
            widget.destroy()

        self._build_task_window_ui(window, task_data, messages, chat_id)

    def _build_task_window_ui(self, window, task_data, messages, chat_id):
        window.title(f"Zadanie #{task_data.get('id')} - {task_data.get('title')}")

        main_frame = tk.Frame(window, padx=10, pady=10)
        main_frame.pack(fill="both", expand=True)

        info_label = tk.Label(main_frame, text="Szczegóły zadania:", font=("Arial", 12, "bold"))
        info_label.pack(anchor="w", pady=(0, 5))

        desc_text = tk.Text(main_frame, height=4, wrap="word", bg="#f0f0f0")
        desc_text.insert("1.0", task_data.get('description', 'Brak opisu.'))
        desc_text.config(state="disabled")
        desc_text.pack(fill="x", pady=(0, 10))

        time_frame = tk.LabelFrame(main_frame, text="Raport czasu pracy", font=("Arial", 11, "bold"), padx=10, pady=5)
        time_frame.pack(fill="x", pady=(0, 15))

        task_time_spent = int(task_data.get("TIME_SPENT_IN_LOGS") or task_data.get("timeSpentInLogs") or 0)

        tracker = {}
        today_date = datetime.now(timezone(timedelta(hours=1))).date()

        for msg in reversed(messages):
            text = msg.get("text", "")
            raw_date = msg.get("date")
            if not raw_date: continue

            try:
                dt_obj = datetime.fromisoformat(raw_date)
                if dt_obj.tzinfo is not None:
                    dt = dt_obj.astimezone(timezone(timedelta(hours=1)))
                else:
                    dt = dt_obj.replace(tzinfo=timezone(timedelta(hours=1)))
            except Exception:
                continue

            start_match = re.search(r"\[USER=\d+\](.*?)\[/USER\]\s+włączył[a]?\s+śledzenie\s+czasu", text,
                                    re.IGNORECASE)
            stop_match = re.search(r"\[USER=\d+\](.*?)\[/USER\]\s+wyłączył[a]?\s+śledzenie\s+czasu", text,
                                   re.IGNORECASE)
            finish_match = re.search(r"(ukończył|zakończył)[a]?\s+zadanie", text, re.IGNORECASE)

            if start_match:
                user = start_match.group(1).strip()
                if user not in tracker:
                    tracker[user] = {"total": 0, "today": 0, "start_dt": None}
                tracker[user]["start_dt"] = dt

            elif stop_match:
                user = stop_match.group(1).strip()
                if user not in tracker:
                    tracker[user] = {"total": 0, "today": 0, "start_dt": None}

                if tracker[user]["start_dt"]:
                    elapsed = (dt - tracker[user]["start_dt"]).total_seconds()
                    tracker[user]["total"] += max(0, elapsed)
                    if dt.date() == today_date or tracker[user]["start_dt"].date() == today_date:
                        tracker[user]["today"] += max(0, elapsed)
                tracker[user]["start_dt"] = None

            elif finish_match:
                for user, data in tracker.items():
                    if data["start_dt"]:
                        elapsed = (dt - data["start_dt"]).total_seconds()
                        data["total"] += max(0, elapsed)
                        if dt.date() == today_date or data["start_dt"].date() == today_date:
                            data["today"] += max(0, elapsed)
                        data["start_dt"] = None

        active_timers = {}
        total_time_var = tk.StringVar()
        total_time_lbl = tk.Label(time_frame, textvariable=total_time_var, font=("Arial", 11, "bold"), fg="#2c3e50")
        total_time_lbl.pack(anchor="w", pady=(0, 10))

        if not tracker and task_time_spent == 0:
            total_time_var.set("Razem czas na to zadanie: 00:00:00")
            tk.Label(time_frame, text="Brak historii czasu dla tego zadania.").pack(anchor="w")
        else:
            for user, data in tracker.items():
                lbl_var = tk.StringVar()
                lbl = tk.Label(time_frame, textvariable=lbl_var, font=("Arial", 10))
                lbl.pack(anchor="w")

                is_active_today = False
                if data["start_dt"]:
                    if data["start_dt"].date() == today_date:
                        is_active_today = True

                today_str = f" (w tym dzisiaj: {seconds_to_readable(data['today'])})" if data['today'] > 0 else ""

                if is_active_today:
                    active_timers[user] = {
                        "total": data["total"],
                        "today": data["today"],
                        "start_dt": data["start_dt"],
                        "var": lbl_var
                    }
                else:
                    lbl_var.set(f"👤 {user}: {seconds_to_readable(data['total'])}{today_str}")

            if not active_timers:
                total_time_var.set(f"Razem czas na to zadanie: {seconds_to_readable(task_time_spent)}")

        if active_timers:
            self.update_live_timers(window, active_timers, total_time_var, task_time_spent, window.current_cycle)

        chat_label_text = f"Wiadomości (Chat ID: {chat_id}):" if chat_id else "Wiadomości (Brak podpiętego czatu):"
        if not messages and chat_id:
            chat_label_text += " [Synchronizowanie...]"

        chat_label = tk.Label(main_frame, text=chat_label_text, font=("Arial", 12, "bold"))
        chat_label.pack(anchor="w", pady=(0, 5))

        chat_scroll = ttk.Scrollbar(main_frame, orient="vertical")
        chat_scroll.pack(side="right", fill="y")

        chat_text = tk.Text(main_frame, wrap="word", yscrollcommand=chat_scroll.set)
        chat_text.pack(side="left", fill="both", expand=True)
        chat_scroll.config(command=chat_text.yview)

        if messages:
            for msg in reversed(messages):
                author_id = str(msg.get("author_id", ""))
                if author_id and author_id != "0":
                    author_name = self.users_map.get(author_id, f"ID {author_id}")
                else:
                    author_name = "System"

                text = msg.get("text", "")
                date = format_date(msg.get("date"))

                clean_text = re.sub(r"\[USER=\d+\](.*?)\[/USER\]", r"\1", text)

                chat_text.insert("end", f"[{date}] {author_name}:\n", "header")
                chat_text.insert("end", f"{clean_text}\n\n")
        else:
            chat_text.insert("end",
                             "Brak wiadomości do wyświetlenia. Jeśli to zadanie zostało otworzone pierwszy raz, wiadomości pojawią się za chwilę automatycznie.")

        chat_text.tag_config("header", font=("Arial", 10, "bold"))
        chat_text.config(state="disabled")

    def update_live_timers(self, window, active_timers, total_time_var, task_time_spent, cycle_id):
        if not window.winfo_exists() or getattr(window, "current_cycle", None) != cycle_id:
            return

        now = datetime.now(timezone(timedelta(hours=1)))
        live_total_elapsed = 0

        for user, data in active_timers.items():
            elapsed_since_start = (now - data["start_dt"]).total_seconds()
            live_elapsed = max(0, elapsed_since_start)
            live_total_elapsed += live_elapsed

            total_current_user = data["total"] + live_elapsed
            today_current_user = data["today"] + live_elapsed

            data["var"].set(
                f"👤 {user}: {seconds_to_readable(total_current_user)} (w tym dzisiaj: {seconds_to_readable(today_current_user)}) (W trakcie...)")

        base_readable = seconds_to_readable(task_time_spent)

        if live_total_elapsed > 0:
            live_readable = seconds_to_readable(live_total_elapsed)
            grand_total_seconds = task_time_spent + live_total_elapsed
            grand_total_readable = seconds_to_readable(grand_total_seconds)
            total_time_var.set(f"Razem czas na to zadanie: {base_readable} + {live_readable} = {grand_total_readable}")
        else:
            total_time_var.set(f"Razem czas na to zadanie: {base_readable}")

        window.after(1000,
                     lambda: self.update_live_timers(window, active_timers, total_time_var, task_time_spent, cycle_id))


if __name__ == "__main__":
    root = tk.Tk()
    app = BitrixApp(root)
    root.mainloop()