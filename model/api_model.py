"""
model/api_client.py — Warstwa komunikacji z API Bitrix24.

Odpowiada wyłącznie za wysyłanie requestów HTTP i zwracanie surowych danych.
Nie zna tkinter, nie modyfikuje UI — tylko pobiera i zapisuje pliki JSON.
"""
import io
import json
import os
import time
from datetime import datetime, timedelta

import requests
from PIL import Image, ImageDraw, ImageTk

from config import WEBHOOK_URL


class BitrixApiClient:
    """Klient HTTP dla Bitrix24 REST API."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir

        # Cache zdjęć profilowych — żyje w pamięci przez cały czas trwania sesji.
        # PhotoImage musi być trzymany w pamięci, inaczej GC go zbierze.
        self._photo_cache: dict = {}

    # ------------------------------------------------------------------
    # Użytkownicy
    # ------------------------------------------------------------------

    def fetch_all_users(self) -> dict:
        """
        Pobiera wszystkich użytkowników z Bitrix24.
        Zwraca słownik {uid: {"name": str, "photo": str|None}}.
        Zapisuje wynik do users_list.json.
        Rzuca requests.RequestException przy błędzie sieci.
        """
        full_url  = f"{WEBHOOK_URL}user.get.json"
        all_users: dict = {}
        start     = 0

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

        out_path = os.path.join(self.data_dir, "users_list.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(all_users, f, ensure_ascii=False, indent=4)

        return all_users

    def get_user_avatar(self, uid: str, url: str, size: int = 20):
        """
        Zwraca obiekt PhotoImage z awatarem użytkownika (okrągły).
        Korzysta z cache'u w pamięci oraz lokalnych plików PNG.
        Zwraca None gdy url jest pusty lub wystąpi błąd pobierania.
        """
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
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
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

    # ------------------------------------------------------------------
    # Zadania — pobieranie
    # ------------------------------------------------------------------

    def fetch_in_progress_tasks(self, on_progress=None) -> list:
        """
        Pobiera zadania o statusie 'W trakcie' (REAL_STATUS=3)
        z ostatnich 7 dni aktywności.

        on_progress(n: int) — opcjonalny callback wywoływany po każdej
        stronie wyników z aktualną liczbą pobranych zadań.

        Zapisuje wynik do tasks_in_progress.json.
        Rzuca requests.RequestException przy błędzie sieci.
        """
        full_url  = f"{WEBHOOK_URL}tasks.task.list"
        all_tasks: list = []
        start     = 0
        date_str  = (datetime.now() - timedelta(days=28)).strftime("%Y-%m-%dT00:00:00+01:00")

        while True:
            params = {
                "filter[REAL_STATUS]":     3,
                "filter[>=ACTIVITY_DATE]": date_str,
                "start":                   start,
            }
            resp = requests.get(full_url, params=params, timeout=10)
            resp.raise_for_status()
            data  = resp.json()
            tasks = data.get("result", {}).get("tasks", [])
            if not tasks:
                break
            all_tasks.extend(tasks)
            if on_progress:
                on_progress(len(all_tasks))
            if "next" in data:
                start = data["next"]
            else:
                break

        out_path = os.path.join(self.data_dir, "tasks_in_progress.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(all_tasks, f, ensure_ascii=False, indent=4)

        return all_tasks

    def fetch_standard_tasks(self, file_exists: bool, on_progress=None) -> list:
        """
        Pobiera wszystkie zadania (pełna lista lub delta ostatnich 30 dni).

        file_exists — czy tasks_list.json już istnieje (tryb delta vs pełny).
        on_progress(n) — opcjonalny callback z postępem.

        Zapisuje wynik do tasks_list.json.
        Rzuca requests.RequestException przy błędzie sieci.
        """
        tasks_path = os.path.join(self.data_dir, "tasks_list.json")
        all_tasks: list = []
        start = 0

        if file_exists:
            full_url = f"{WEBHOOK_URL}tasks.task.list"
            date_str = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%dT00:00:00+01:00")

            while True:
                params = {
                    "filter[>=ACTIVITY_DATE]": date_str,
                    "start": start,
                }
                resp = requests.get(full_url, params=params, timeout=10)
                resp.raise_for_status()
                data  = resp.json()
                tasks = data.get("result", {}).get("tasks", [])
                if not tasks:
                    break
                all_tasks.extend(tasks)
                if on_progress:
                    on_progress(len(all_tasks))
                if "next" in data:
                    start = data["next"]
                else:
                    break
        else:
            full_url = f"{WEBHOOK_URL}task.item.list.json"

            while True:
                resp = requests.get(f"{full_url}?start={start}", timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if "result" not in data:
                    break
                all_tasks.extend(data["result"])
                if on_progress:
                    on_progress(len(all_tasks))
                if "next" in data:
                    start = data["next"]
                else:
                    break

        with open(tasks_path, "w", encoding="utf-8") as f:
            json.dump(all_tasks, f, ensure_ascii=False, indent=4)

        return all_tasks

    def fetch_tasks_by_group(self, group_id: str, on_progress=None) -> list:
        """
        Pobiera zadania należące do konkretnej grupy.

        Nie zapisuje do pliku — dane trafiają bezpośrednio do pamięci.
        Rzuca requests.RequestException przy błędzie sieci.
        """
        full_url    = f"{WEBHOOK_URL}tasks.task.list.json?filter[GROUP_ID]={group_id}"
        group_tasks: list = []
        start       = 0

        while True:
            resp = requests.get(f"{full_url}&start={start}", timeout=10)
            resp.raise_for_status()
            data  = resp.json()
            tasks = data.get("result", {}).get("tasks", [])
            if not tasks:
                break
            group_tasks.extend(tasks)
            if on_progress:
                on_progress(len(group_tasks))
            if "next" in data:
                start = data["next"]
            else:
                break

        return group_tasks

    def fetch_task_detail(self, task_id: str) -> dict:
        """
        Pobiera szczegóły pojedynczego zadania.
        Zapisuje do details/task_{task_id}.json.
        Rzuca requests.RequestException przy błędzie sieci.
        """
        resp = requests.get(
            f"{WEBHOOK_URL}tasks.task.get?taskId={task_id}", timeout=5
        )
        resp.raise_for_status()
        task_data = resp.json().get("result", {}).get("task", {})

        if task_data:
            task_file = os.path.join(self.data_dir, "details", f"task_{task_id}.json")
            os.makedirs(os.path.dirname(task_file), exist_ok=True)
            with open(task_file, "w", encoding="utf-8") as f:
                json.dump(task_data, f, ensure_ascii=False, indent=4)

        return task_data

    # ------------------------------------------------------------------
    # Grupy
    # ------------------------------------------------------------------

    def fetch_all_groups(self, on_progress=None) -> list:
        """
        Pobiera wszystkie grupy robocze z Bitrix24.
        Zapisuje wynik do groups_list.json.
        Rzuca requests.RequestException przy błędzie sieci.
        """
        full_url   = f"{WEBHOOK_URL}sonet_group.get.json"
        all_groups: list = []
        start      = 0

        while True:
            resp = requests.get(f"{full_url}?start={start}", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if "result" not in data:
                break
            all_groups.extend(data["result"])
            if on_progress:
                on_progress(len(all_groups))
            if "next" in data:
                start = data["next"]
            else:
                break

        out_path = os.path.join(self.data_dir, "groups_list.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(all_groups, f, ensure_ascii=False, indent=4)

        return all_groups

    # ------------------------------------------------------------------
    # Wiadomości czatu
    # ------------------------------------------------------------------

    def fetch_chat_messages(self, chat_id, chat_file: str) -> list:
        """
        Pobiera wszystkie wiadomości z czatu zadania (stronicowanie przez LAST_ID).
        Zapisuje wynik do chat_file.
        Zwraca listę wiadomości (może być pusta jeśli czat nie istnieje).
        Rzuca requests.RequestException przy nienaprawialnym błędzie sieci.
        """
        messages: list = []
        last_id        = None
        timeout        = 5

        while True:
            url = (
                f"{WEBHOOK_URL}im.dialog.messages.get"
                f"?DIALOG_ID=chat{chat_id}&LIMIT=50"
            )
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
            os.makedirs(os.path.dirname(chat_file), exist_ok=True)
            with open(chat_file, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=4)

        return messages

    def fetch_tasks_for_groups_report(self, on_progress=None) -> list:
        """
        Pobiera wszystkie zadania przypisane do grup (!GROUP_ID != 0).
        Używa tasks.task.list bez ograniczenia select[] żeby mieć pewność
        że closedDate, createdDate i status są obecne w odpowiedzi.

        Zapisuje wynik do group_tasks_report.json.
        Rzuca requests.RequestException przy błędzie sieci.
        """
        full_url = f"{WEBHOOK_URL}tasks.task.list"
        all_tasks: list = []
        start = 0

        while True:
            params = {
                "filter[!GROUP_ID]": 0,
                "start": start,
            }
            resp = requests.get(full_url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            tasks = data.get("result", {}).get("tasks", [])
            if not tasks:
                break
            all_tasks.extend(tasks)
            if on_progress:
                on_progress(len(all_tasks))
            if "next" in data:
                start = data["next"]
            else:
                break

        out_path = os.path.join(self.data_dir, "group_tasks_report.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(all_tasks, f, ensure_ascii=False, indent=4)

        return all_tasks