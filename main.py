import os
import sys
import json
import re
import tkinter as tk
from tkinter import ttk, messagebox
import requests
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


class BitrixApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Bitrix Task & Group Viewer")
        self.root.geometry("1450x700")

        self.data_dir = get_data_dir()
        self.all_fetched_tasks = []
        self.all_fetched_groups = []
        self.all_responsibles = ["Wszyscy"]

        self.current_view = tk.StringVar(value="tasks")

        self.current_filter = tk.StringVar(value="Wszystkie")
        self.current_resp_filter = tk.StringVar(value="Wszyscy")
        self.search_var = tk.StringVar()

        self.task_columns = (
            "ID", "TITLE", "REAL_STATUS", "STATUS", "TIME_SPENT",
            "CREATED_BY", "RESPONSIBLE", "DEADLINE", "CREATED_DATE",
            "CHANGED_DATE", "STATUS_CHANGED_DATE", "GROUP_ID"
        )
        self.group_columns = ("ID", "NAME", "DESCRIPTION", "OWNER_ID", "DATE_CREATE")

        self.create_widgets()

        self.load_local_data()

    def create_widgets(self):
        mode_frame = tk.Frame(self.root, bg="#e0e0e0", pady=5)
        mode_frame.pack(fill="x")

        tk.Label(mode_frame, text="Wyświetlaj:", bg="#e0e0e0", font=("Arial", 10, "bold")).pack(side="left",
                                                                                                padx=(10, 5))
        tk.Radiobutton(mode_frame, text="Zadania", variable=self.current_view, value="tasks", command=self.switch_view,
                       bg="#e0e0e0").pack(side="left")
        tk.Radiobutton(mode_frame, text="Grupy robocze", variable=self.current_view, value="groups",
                       command=self.switch_view, bg="#e0e0e0").pack(side="left", padx=10)

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

        self.filter_frame = tk.Frame(frame_top)
        self.filter_frame.pack(side="right")

        tk.Label(self.filter_frame, text="Status:").grid(row=0, column=0, padx=(10, 2))
        filter_options = ["Wszystkie"] + list(STATUS_MAP.values())
        self.status_combobox = ttk.Combobox(self.filter_frame, textvariable=self.current_filter, values=filter_options,
                                            state="readonly", width=15)
        self.status_combobox.grid(row=0, column=1, padx=2)
        self.status_combobox.bind("<<ComboboxSelected>>", self.apply_filter)

        tk.Label(self.filter_frame, text="Osoba odpowiedzialna:").grid(row=0, column=2, padx=(15, 2))
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

        self.tree = ttk.Treeview(tree_frame, columns=self.task_columns, show="headings", yscrollcommand=tree_scroll.set)
        tree_scroll.config(command=self.tree.yview)

        for col in self.task_columns:
            self.tree.heading(col, text=col, command=lambda _col=col: self.sort_treeview(_col, False))
            self.tree.column(col, width=110)

        self.tree.pack(side="left", fill="both", expand=True)

    def switch_view(self):
        mode = self.current_view.get()

        for row in self.tree.get_children():
            self.tree.delete(row)

        if mode == "tasks":
            self.btn_fetch.config(text="Pobierz / Odśwież zadania")
            self.btn_action.config(text="Otwórz zadanie")
            self.filter_frame.pack(side="right")

            self.tree.config(columns=self.task_columns)
            for col in self.task_columns:
                self.tree.heading(col, text=col, command=lambda _col=col: self.sort_treeview(_col, False))
                self.tree.column(col, width=110)

            self.apply_filter()

        elif mode == "groups":
            self.btn_fetch.config(text="Pobierz / Odśwież grupy")
            self.btn_action.config(text="Otwórz / Filtruj zadania")
            self.filter_frame.pack_forget()

            self.tree.config(columns=self.group_columns)
            for col in self.group_columns:
                self.tree.heading(col, text=col, command=lambda _col=col: self.sort_treeview(_col, False))
                width = 300 if col == "NAME" else 150
                self.tree.column(col, width=width)

            self.display_groups(self.all_fetched_groups)

    def load_local_data(self):
        tasks_path = os.path.join(self.data_dir, "tasks_list.json")
        if os.path.exists(tasks_path):
            try:
                with open(tasks_path, "r", encoding="utf-8") as f:
                    self.all_fetched_tasks = json.load(f)
                self.update_resp_filter_options()
            except Exception as e:
                print(f"Nie udało się wczytać zadań: {e}")

        groups_path = os.path.join(self.data_dir, "groups_list.json")
        if os.path.exists(groups_path):
            try:
                with open(groups_path, "r", encoding="utf-8") as f:
                    self.all_fetched_groups = json.load(f)
            except Exception as e:
                print(f"Nie udało się wczytać grup: {e}")

        self.switch_view()

    def sort_treeview(self, col, reverse):
        data = [(self.tree.set(child, col), child) for child in self.tree.get_children("")]
        try:
            data.sort(key=lambda t: float(t[0]) if t[0] else 0.0, reverse=reverse)
        except ValueError:
            data.sort(key=lambda t: t[0].lower(), reverse=reverse)

        for index, (_, child) in enumerate(data):
            self.tree.move(child, "", index)

        self.tree.heading(col, command=lambda _col=col: self.sort_treeview(_col, not reverse))

    def fetch_data(self):
        mode = self.current_view.get()
        if mode == "tasks":
            self.fetch_all_tasks()
        elif mode == "groups":
            self.fetch_all_groups()

    def fetch_all_groups(self):
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

                if "next" in data:
                    start = data["next"]
                else:
                    break

            self.all_fetched_groups = all_groups
            self.display_groups(all_groups)

            file_path = os.path.join(self.data_dir, "groups_list.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(all_groups, f, ensure_ascii=False, indent=4)

            messagebox.showinfo("Sukces", "Pobrano i zapisano grupy robocze.")

        except requests.exceptions.RequestException as e:
            messagebox.showwarning("Błąd", f"Nie udało się pobrać grup.\n{e}")

    def display_groups(self, groups):
        if self.current_view.get() != "groups":
            return

        for row in self.tree.get_children():
            self.tree.delete(row)

        for group in groups:
            self.tree.insert("", "end", values=(
                group.get("ID"),
                group.get("NAME"),
                group.get("DESCRIPTION"),
                group.get("OWNER_ID"),
                format_date(group.get("DATE_CREATE"))
            ))

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

        item_values = self.tree.item(selected_item[0], "values")
        group_id = item_values[0]
        group_name = item_values[1]

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

                if "next" in data:
                    start = data["next"]
                else:
                    break

            if not group_tasks:
                messagebox.showinfo("Informacja", f"Brak zadań w grupie: {group_name}")
                return

            self.all_fetched_tasks = group_tasks
            self.current_view.set("tasks")
            self.switch_view()
            self.update_resp_filter_options()
            self.apply_filter()

            messagebox.showinfo("Sukces", f"Wyświetlono zadania dla projektu: {group_name}")

        except Exception as e:
            messagebox.showerror("Błąd", f"Nie udało się pobrać zadań dla tej grupy:\n{str(e)}")

    def fetch_all_tasks(self):
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

                if "next" in data:
                    start = data["next"]
                else:
                    break

            self.all_fetched_tasks = all_tasks
            self.update_resp_filter_options()
            self.apply_filter()

            file_path = os.path.join(self.data_dir, "tasks_list.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(all_tasks, f, ensure_ascii=False, indent=4)

            messagebox.showinfo("Sukces", "Pobrano i zapisano wszystkie zadania.")

        except requests.exceptions.RequestException as e:
            messagebox.showwarning("Tryb Offline",
                                   f"Nie udało się połączyć z serwerem. Przeglądasz dane zapisane lokalnie.\nSzczegóły błędu: {e}")

    def update_resp_filter_options(self):
        responsibles = set()
        for task in self.all_fetched_tasks:
            resp_name = f"{task.get('RESPONSIBLE_NAME', '')} {task.get('RESPONSIBLE_LAST_NAME', '')}".strip()

            if not resp_name and 'responsible' in task:
                resp = task['responsible']
                resp_name = f"{resp.get('name', '')} {resp.get('lastName', '')}".strip()

            if resp_name:
                responsibles.add(resp_name)

        self.all_responsibles = ["Wszyscy"] + sorted(list(responsibles))
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
        typed_resp = self.current_resp_filter.get().strip().lower()
        search_term = self.search_var.get().strip().lower()

        filtered_tasks = []
        for task in self.all_fetched_tasks:
            real_status = str(task.get("REAL_STATUS") or task.get("status", ""))
            mapped_status = STATUS_MAP.get(real_status, real_status)

            resp_name = f"{task.get('RESPONSIBLE_NAME', '')} {task.get('RESPONSIBLE_LAST_NAME', '')}".strip()
            if not resp_name and 'responsible' in task:
                resp = task['responsible']
                resp_name = f"{resp.get('name', '')} {resp.get('lastName', '')}".strip()

            task_title = (task.get("TITLE") or task.get("title", "")).lower()

            match_status = (selected_status == "Wszystkie" or mapped_status == selected_status)
            match_title = (not search_term) or (search_term in task_title)

            if typed_resp in ("wszyscy", ""):
                match_resp = True
            else:
                match_resp = typed_resp in resp_name.lower()

            if match_status and match_resp and match_title:
                filtered_tasks.append(task)

        self.display_data(filtered_tasks)

    def display_data(self, tasks):
        for row in self.tree.get_children():
            self.tree.delete(row)

        for task in tasks:
            t_id = task.get("ID") or task.get("id")
            title = task.get("TITLE") or task.get("title")

            r_status = str(task.get("REAL_STATUS") or task.get("status", ""))
            status = str(task.get("STATUS") or task.get("status", ""))

            real_status_text = STATUS_MAP.get(r_status, r_status)
            status_text = STATUS_MAP.get(status, status)

            time_spent = seconds_to_readable(task.get("TIME_SPENT_IN_LOGS") or task.get("timeSpentInLogs", 0))

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
            g_id = task.get("GROUP_ID") or task.get("groupId")

            self.tree.insert("", "end", values=(
                t_id, title, real_status_text, status_text, time_spent,
                c_by, resp, deadline, created, changed, status_changed, g_id
            ))

    def open_task(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Uwaga", "Proszę wybrać zadanie z tabeli.")
            return

        item_values = self.tree.item(selected_item[0], "values")
        task_id = item_values[0]

        task_file_path = os.path.join(self.data_dir, "details", f"task_{task_id}.json")
        chat_id = None
        task_data = {}
        messages = []

        try:
            task_resp = requests.get(f"{WEBHOOK_URL}tasks.task.get?taskId={task_id}", timeout=5)
            task_resp.raise_for_status()
            task_data = task_resp.json().get("result", {}).get("task", {})

            if task_data:
                with open(task_file_path, "w", encoding="utf-8") as f:
                    json.dump(task_data, f, ensure_ascii=False, indent=4)

            chat_id = task_data.get("chatId") or task_data.get("CHAT_ID")

            if chat_id:
                chat_file_path = os.path.join(self.data_dir, "chats", f"chat_{chat_id}.json")

                start_param = 0
                while True:
                    chat_resp = requests.get(
                        f"{WEBHOOK_URL}im.dialog.messages.get?DIALOG_ID=chat{chat_id}&start={start_param}", timeout=10)
                    chat_resp.raise_for_status()
                    chat_data_json = chat_resp.json()

                    fetched_messages = chat_data_json.get("result", {}).get("messages", [])
                    if not fetched_messages:
                        break

                    messages.extend(fetched_messages)

                    if "next" in chat_data_json:
                        start_param = chat_data_json["next"]
                    else:
                        if len(fetched_messages) == 50:
                            start_param += 50
                        else:
                            break

                with open(chat_file_path, "w", encoding="utf-8") as f:
                    json.dump(messages, f, ensure_ascii=False, indent=4)

        except requests.exceptions.RequestException:
            if os.path.exists(task_file_path):
                with open(task_file_path, "r", encoding="utf-8") as f:
                    task_data = json.load(f)
                chat_id = task_data.get("chatId") or task_data.get("CHAT_ID")
            else:
                messagebox.showerror("Błąd", "Nie masz internetu, a to zadanie nie zostało jeszcze pobrane lokalnie.")
                return

            if chat_id:
                chat_file_path = os.path.join(self.data_dir, "chats", f"chat_{chat_id}.json")
                if os.path.exists(chat_file_path):
                    with open(chat_file_path, "r", encoding="utf-8") as f:
                        messages = json.load(f)

        if not task_data:
            messagebox.showerror("Błąd", "Nie znaleziono szczegółów zadania.")
            return

        self.show_task_details_window(task_data, messages, chat_id)

    def show_task_details_window(self, task_data, messages, chat_id):
        top = tk.Toplevel(self.root)
        top.title(f"Zadanie #{task_data.get('id')} - {task_data.get('title')}")
        top.geometry("900x700")

        main_frame = tk.Frame(top, padx=10, pady=10)
        main_frame.pack(fill="both", expand=True)

        info_label = tk.Label(main_frame, text="Szczegóły zadania:", font=("Arial", 12, "bold"))
        info_label.pack(anchor="w", pady=(0, 5))

        desc_text = tk.Text(main_frame, height=4, wrap="word", bg="#f0f0f0")
        desc_text.insert("1.0", task_data.get('description', 'Brak opisu.'))
        desc_text.config(state="disabled")
        desc_text.pack(fill="x", pady=(0, 10))

        # --- SEKCJA: ŚLEDZENIE CZASU ---
        time_frame = tk.LabelFrame(main_frame, text="Raport czasu pracy", font=("Arial", 11, "bold"), padx=10, pady=5)
        time_frame.pack(fill="x", pady=(0, 15))

        task_time_spent = int(task_data.get("TIME_SPENT_IN_LOGS") or task_data.get("timeSpentInLogs") or 0)

        tracker = {}

        # Pobieramy dzisiejszą datę do porównań
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

                    # KOREKTA: Zliczamy do dzisiejszego bilansu jeśli data startu lub stopu to dzisiaj
                    if dt.date() == today_date or tracker[user]["start_dt"].date() == today_date:
                        tracker[user]["today"] += max(0, elapsed)

                tracker[user]["start_dt"] = None

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
                    # KOREKTA: Sprawdzamy czy włączony stoper to rzeczywiście akcja z dzisiaj.
                    # Odcina to absurdalne sumy wiszących stoperów z innych dni.
                    if data["start_dt"].date() == today_date:
                        is_active_today = True

                # Informacja ile z wyliczonego czasu przypada na dzisiaj
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
            self.update_live_timers(top, active_timers, total_time_var, task_time_spent)

        # --- SEKCJA: CZAT ---
        chat_label_text = f"Wiadomości (Chat ID: {chat_id}):" if chat_id else "Wiadomości (Brak podpiętego czatu):"
        chat_label = tk.Label(main_frame, text=chat_label_text, font=("Arial", 12, "bold"))
        chat_label.pack(anchor="w", pady=(0, 5))

        chat_scroll = ttk.Scrollbar(main_frame, orient="vertical")
        chat_scroll.pack(side="right", fill="y")

        chat_text = tk.Text(main_frame, wrap="word", yscrollcommand=chat_scroll.set)
        chat_text.pack(side="left", fill="both", expand=True)
        chat_scroll.config(command=chat_text.yview)

        if messages:
            for msg in reversed(messages):
                author = msg.get("author_id", "System" if not msg.get("author_id") else msg.get("author_id"))
                text = msg.get("text", "")
                date = format_date(msg.get("date"))

                clean_text = re.sub(r"\[USER=\d+\](.*?)\[/USER\]", r"\1", text)

                chat_text.insert("end", f"[{date}] Użytkownik {author}:\n", "header")
                chat_text.insert("end", f"{clean_text}\n\n")
        else:
            chat_text.insert("end", "Brak wiadomości do wyświetlenia.")

        chat_text.tag_config("header", font=("Arial", 10, "bold"))
        chat_text.config(state="disabled")

    def update_live_timers(self, window, active_timers, total_time_var, task_time_spent):
        if not window.winfo_exists():
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

        window.after(1000, lambda: self.update_live_timers(window, active_timers, total_time_var, task_time_spent))


if __name__ == "__main__":
    root = tk.Tk()
    app = BitrixApp(root)
    root.mainloop()