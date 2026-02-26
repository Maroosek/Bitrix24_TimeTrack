import os
import tkinter as tk
from tkinter import ttk, messagebox
import requests
from datetime import datetime, timezone, timedelta

# Konfiguracja zmiennych
WEBHOOK_URL = os.environ.get("BITRIX_WEBHOOK", "https://jenaeuropa.bitrix24.pl/rest/223/8cd46qmskggzo81m/")
ENDPOINT = "task.item.list.json"

STATUS_MAP = {
    "1": "Nowe",
    "2": "Oczekujące",
    "3": "W trakcie",
    "4": "Do kontroli",
    "5": "Zakończone",
    "6": "Odłożone"
}


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
        # Parsowanie pełnej daty z uwzględnieniem strefy czasowej
        dt = datetime.fromisoformat(date_string)

        # Jeśli data ma informacje o strefie (np. +03:00), konwertujemy na +01:00
        if dt.tzinfo is not None:
            target_tz = timezone(timedelta(hours=1))
            dt = dt.astimezone(target_tz)

        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        # Fallback (bezpiecznik), jeśli format jest nietypowy i wywali błąd
        try:
            return datetime.fromisoformat(date_string.split("+")[0]).strftime("%Y-%m-%d %H:%M")
        except:
            return date_string


class BitrixApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Bitrix Task Viewer")
        self.root.geometry("1400x700")

        self.all_fetched_tasks = []
        self.current_filter = tk.StringVar(value="Wszystkie")
        self.current_resp_filter = tk.StringVar(value="Wszyscy")

        self.create_widgets()

    def create_widgets(self):
        # Górny panel narzędziowy
        frame_top = tk.Frame(self.root)
        frame_top.pack(pady=10, fill="x", padx=10)

        # Przyciski akcji
        btn_frame = tk.Frame(frame_top)
        btn_frame.pack(side="left")

        tk.Button(btn_frame, text="Pobierz dane", command=self.fetch_data, width=15, bg="#4CAF50", fg="white").grid(
            row=0, column=0, padx=5)
        tk.Button(btn_frame, text="Otwórz zadanie", command=self.open_task, width=15, bg="#2196F3", fg="white").grid(
            row=0, column=1, padx=5)

        # Filtry
        filter_frame = tk.Frame(frame_top)
        filter_frame.pack(side="right")

        # Filtr statusu
        tk.Label(filter_frame, text="Status:").grid(row=0, column=0, padx=(10, 2))
        filter_options = ["Wszystkie"] + list(STATUS_MAP.values())
        self.status_combobox = ttk.Combobox(filter_frame, textvariable=self.current_filter, values=filter_options,
                                            state="readonly", width=20)
        self.status_combobox.grid(row=0, column=1, padx=2)
        self.status_combobox.bind("<<ComboboxSelected>>", self.apply_filter)

        # Filtr osoby odpowiedzialnej
        tk.Label(filter_frame, text="Osoba odpowiedzialna:").grid(row=0, column=2, padx=(15, 2))
        self.resp_combobox = ttk.Combobox(filter_frame, textvariable=self.current_resp_filter, values=["Wszyscy"],
                                          state="readonly", width=20)
        self.resp_combobox.grid(row=0, column=3, padx=2)
        self.resp_combobox.bind("<<ComboboxSelected>>", self.apply_filter)

        # Ramka na tabelę i pasek przewijania
        tree_frame = tk.Frame(self.root)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=10)

        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical")
        tree_scroll.pack(side="right", fill="y")

        columns = (
            "ID", "TITLE", "REAL_STATUS", "STATUS", "TIME_SPENT",
            "CREATED_BY", "RESPONSIBLE", "DEADLINE", "CREATED_DATE",
            "CHANGED_DATE", "STATUS_CHANGED_DATE", "GROUP_ID"
        )

        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", yscrollcommand=tree_scroll.set)
        tree_scroll.config(command=self.tree.yview)

        for col in columns:
            self.tree.heading(col, text=col, command=lambda _col=col: self.sort_treeview(_col, False))
            self.tree.column(col, width=110)

        self.tree.pack(side="left", fill="both", expand=True)

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
        full_url = f"{WEBHOOK_URL}{ENDPOINT}"
        all_tasks = []
        start = 0

        try:
            while True:
                response = requests.get(f"{full_url}?start={start}")
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

        except Exception as e:
            messagebox.showerror("Błąd", f"Nie udało się pobrać danych:\n{str(e)}")

    def update_resp_filter_options(self):
        responsibles = set()
        for task in self.all_fetched_tasks:
            resp_name = f"{task.get('RESPONSIBLE_NAME', '')} {task.get('RESPONSIBLE_LAST_NAME', '')}".strip()
            if resp_name:
                responsibles.add(resp_name)

        options = ["Wszyscy"] + sorted(list(responsibles))
        self.resp_combobox.config(values=options)
        self.current_resp_filter.set("Wszyscy")

    def apply_filter(self, event=None):
        selected_status = self.current_filter.get()
        selected_resp = self.current_resp_filter.get()

        filtered_tasks = []
        for task in self.all_fetched_tasks:
            real_status = task.get("REAL_STATUS")
            mapped_status = STATUS_MAP.get(str(real_status), real_status)

            resp_name = f"{task.get('RESPONSIBLE_NAME', '')} {task.get('RESPONSIBLE_LAST_NAME', '')}".strip()

            match_status = (selected_status == "Wszystkie" or mapped_status == selected_status)
            match_resp = (selected_resp == "Wszyscy" or resp_name == selected_resp)

            if match_status and match_resp:
                filtered_tasks.append(task)

        self.display_data(filtered_tasks)

    def display_data(self, tasks):
        for row in self.tree.get_children():
            self.tree.delete(row)

        for task in tasks:
            real_status = task.get("REAL_STATUS")
            status = task.get("STATUS")

            real_status_text = STATUS_MAP.get(str(real_status), real_status)
            status_text = STATUS_MAP.get(str(status), status)

            time_spent = seconds_to_readable(task.get("TIME_SPENT_IN_LOGS", 0))
            created_by = f"{task.get('CREATED_BY_NAME', '')} {task.get('CREATED_BY_LAST_NAME', '')}".strip()
            responsible = f"{task.get('RESPONSIBLE_NAME', '')} {task.get('RESPONSIBLE_LAST_NAME', '')}".strip()

            self.tree.insert("", "end", values=(
                task.get("ID"), task.get("TITLE"), real_status_text, status_text, time_spent,
                created_by, responsible, format_date(task.get("DEADLINE")),
                format_date(task.get("CREATED_DATE")), format_date(task.get("CHANGED_DATE")),
                format_date(task.get("STATUS_CHANGED_DATE")), task.get("GROUP_ID")
            ))

    def open_task(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Uwaga", "Proszę wybrać zadanie z tabeli.")
            return

        item_values = self.tree.item(selected_item[0], "values")
        task_id = item_values[0]

        try:
            task_resp = requests.get(f"{WEBHOOK_URL}tasks.task.get?taskId={task_id}")
            task_resp.raise_for_status()
            task_data = task_resp.json().get("result", {}).get("task", {})

            if not task_data:
                messagebox.showerror("Błąd", "Nie znaleziono szczegółów zadania.")
                return

            chat_id = task_data.get("chatId") or task_data.get("CHAT_ID")
            messages = []

            if chat_id:
                chat_resp = requests.get(f"{WEBHOOK_URL}im.dialog.messages.get?DIALOG_ID=chat{chat_id}")
                chat_resp.raise_for_status()
                messages = chat_resp.json().get("result", {}).get("messages", [])

            self.show_task_details_window(task_data, messages, chat_id)

        except Exception as e:
            messagebox.showerror("Błąd API", f"Nie udało się otworzyć zadania:\n{str(e)}")

    def show_task_details_window(self, task_data, messages, chat_id):
        top = tk.Toplevel(self.root)
        top.title(f"Zadanie #{task_data.get('id')} - {task_data.get('title')}")
        top.geometry("800x600")

        main_frame = tk.Frame(top, padx=10, pady=10)
        main_frame.pack(fill="both", expand=True)

        info_label = tk.Label(main_frame, text="Szczegóły zadania:", font=("Arial", 12, "bold"))
        info_label.pack(anchor="w", pady=(0, 5))

        desc_text = tk.Text(main_frame, height=5, wrap="word", bg="#f0f0f0")
        desc_text.insert("1.0", task_data.get('description', 'Brak opisu.'))
        desc_text.config(state="disabled")
        desc_text.pack(fill="x", pady=(0, 15))

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
                author = msg.get("author_id", "Nieznany")
                text = msg.get("text", "")

                # Używamy tej samej, poprawionej funkcji daty do wiadomości z czatu!
                date = format_date(msg.get("date"))

                chat_text.insert("end", f"[{date}] Użytkownik {author}:\n", "header")
                chat_text.insert("end", f"{text}\n\n")
        else:
            chat_text.insert("end", "Brak wiadomości do wyświetlenia.")

        chat_text.tag_config("header", font=("Arial", 10, "bold"))
        chat_text.config(state="disabled")


if __name__ == "__main__":
    root = tk.Tk()
    app = BitrixApp(root)
    root.mainloop()