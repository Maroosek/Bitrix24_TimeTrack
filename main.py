import os
import tkinter as tk
from tkinter import ttk, messagebox
import requests
from datetime import datetime

# Konfiguracja zmiennych
WEBHOOK_URL = os.environ.get("BITRIX_WEBHOOK", "https://jenaeuropa.bitrix24.pl/rest/223/8cd46qmskggzo81m/")
ENDPOINT = "task.item.list.json"

STATUS_MAP = {
    "2": "Wstrzymane / Oczekujące",
    "3": "W trakcie",
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
        return datetime.fromisoformat(date_string.split("+")[0]).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return date_string


class BitrixApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Bitrix Task Viewer")
        self.root.geometry("1400x700")

        # Zmienna do przechowywania wszystkich pobranych zadań (aby nie pobierać ich ponownie przy filtrowaniu)
        self.all_fetched_tasks = []
        self.current_filter = tk.StringVar(value="Wszystkie")

        self.create_widgets()

    def create_widgets(self):
        # Górny panel z przyciskiem i filtrem
        frame_top = tk.Frame(self.root)
        frame_top.pack(pady=10)

        tk.Button(frame_top, text="Pobierz dane", command=self.fetch_data, width=20, bg="#4CAF50", fg="white").grid(
            row=0, column=0, padx=10)

        # Dodanie etykiety i rozwijanej listy (Combobox) dla filtra
        tk.Label(frame_top, text="Filtruj po statusie:").grid(row=0, column=1, padx=(20, 5))

        filter_options = ["Wszystkie"] + list(STATUS_MAP.values())
        self.status_combobox = ttk.Combobox(frame_top, textvariable=self.current_filter, values=filter_options,
                                            state="readonly", width=25)
        self.status_combobox.grid(row=0, column=2, padx=5)

        # Wywołanie funkcji filtrującej za każdym razem, gdy użytkownik wybierze nową opcję
        self.status_combobox.bind("<<ComboboxSelected>>", self.apply_filter)

        # Ramka na tabelę i pasek przewijania
        tree_frame = tk.Frame(self.root)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=10)

        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical")
        tree_scroll.pack(side="right", fill="y")

        columns = (
            "ID",
            "TITLE",
            "REAL_STATUS",
            "STATUS",
            "TIME_SPENT",
            "CREATED_BY",
            "RESPONSIBLE",
            "DEADLINE",
            "CREATED_DATE",
            "CHANGED_DATE",
            "STATUS_CHANGED_DATE",
            "GROUP_ID"
        )

        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", yscrollcommand=tree_scroll.set)
        tree_scroll.config(command=self.tree.yview)

        for col in columns:
            self.tree.heading(col, text=col, command=lambda _col=col: self.sort_treeview(_col, False))
            self.tree.column(col, width=130)

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

            # Zapisz pobrane zadania w pamięci podręcznej i zastosuj obecny filtr
            self.all_fetched_tasks = all_tasks
            self.apply_filter()

        except Exception as e:
            messagebox.showerror("Błąd", f"Nie udało się pobrać danych:\n{str(e)}")

    def apply_filter(self, event=None):
        """Filtruje dane w zależności od wybranego statusu."""
        selected_status = self.current_filter.get()

        if selected_status == "Wszystkie":
            filtered_tasks = self.all_fetched_tasks
        else:
            filtered_tasks = []
            for task in self.all_fetched_tasks:
                real_status = task.get("REAL_STATUS")
                # Zamieniamy kod statusu na czytelny tekst, tak jak to robimy przy wyświetlaniu
                mapped_status = STATUS_MAP.get(str(real_status), real_status)

                if mapped_status == selected_status:
                    filtered_tasks.append(task)

        # Wyświetl przefiltrowaną listę
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

            created_by = f"{task.get('CREATED_BY_NAME', '')} {task.get('CREATED_BY_LAST_NAME', '')}"
            responsible = f"{task.get('RESPONSIBLE_NAME', '')} {task.get('RESPONSIBLE_LAST_NAME', '')}"

            self.tree.insert("", "end", values=(
                task.get("ID"),
                task.get("TITLE"),
                real_status_text,
                status_text,
                time_spent,
                created_by.strip(),
                responsible.strip(),
                format_date(task.get("DEADLINE")),
                format_date(task.get("CREATED_DATE")),
                format_date(task.get("CHANGED_DATE")),
                format_date(task.get("STATUS_CHANGED_DATE")),
                task.get("GROUP_ID")
            ))


if __name__ == "__main__":
    root = tk.Tk()
    app = BitrixApp(root)
    root.mainloop()