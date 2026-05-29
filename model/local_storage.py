"""
model/local_storage.py — Warstwa dostępu do lokalnych plików JSON.

Odpowiada za odczyt zadań, grup, konfiguracji UI i szczegółów zadań z dysku.
Nie zna tkinter, nie pobiera danych z sieci.
"""
import json
import os


class LocalStorage:
    """Zarządza lokalnym cache'em danych Bitrix24 i konfiguracją UI."""

    CONFIG_FILE  = "ui_config.json"
    TASKS_ALL    = "tasks_list.json"
    TASKS_ACTIVE = "tasks_in_progress.json"
    GROUPS_FILE  = "groups_list.json"
    USERS_FILE   = "users_list.json"

    def __init__(self, data_dir: str):
        self.data_dir = data_dir

    # ------------------------------------------------------------------
    # Konfiguracja UI
    # ------------------------------------------------------------------

    def load_config(self) -> dict:
        """Wczytuje ui_config.json. Zwraca pusty słownik jeśli plik nie istnieje."""
        path = os.path.join(self.data_dir, self.CONFIG_FILE)
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def save_config(self, config: dict) -> None:
        """Nadpisuje ui_config.json podanym słownikiem."""
        path = os.path.join(self.data_dir, self.CONFIG_FILE)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Nie udało się zapisać konfiguracji: {e}")

    # ------------------------------------------------------------------
    # Zadania
    # ------------------------------------------------------------------

    def load_tasks(self, in_progress_only: bool) -> list:
        """
        Wczytuje zadania z dysku.

        in_progress_only=True  → tasks_in_progress.json
        in_progress_only=False → tasks_list.json

        Zwraca listę (pustą gdy brak pliku lub błąd odczytu).
        """
        fname = self.TASKS_ACTIVE if in_progress_only else self.TASKS_ALL
        path  = os.path.join(self.data_dir, fname)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Błąd odczytu zadań ({fname}): {e}")
            return []

    def tasks_list_exists(self) -> bool:
        """Czy plik tasks_list.json istnieje na dysku (potrzebne do wyboru trybu fetch)."""
        return os.path.exists(os.path.join(self.data_dir, self.TASKS_ALL))

    def load_task_detail(self, task_id: str) -> dict | None:
        """
        Wczytuje szczegóły zadania z lokalnego cache'u.
        Zwraca None jeśli plik nie istnieje.
        """
        path = os.path.join(self.data_dir, "details", f"task_{task_id}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def chat_file_path(self, chat_id) -> str:
        """Zwraca bezwzględną ścieżkę do pliku z wiadomościami czatu."""
        return os.path.join(self.data_dir, "chats", f"chat_{chat_id}.json")

    def load_chat_messages(self, chat_id) -> list:
        """
        Wczytuje wiadomości czatu z lokalnego cache'u.
        Zwraca pustą listę jeśli plik nie istnieje.
        """
        path = self.chat_file_path(chat_id)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Grupy
    # ------------------------------------------------------------------

    def load_groups(self) -> list:
        """
        Wczytuje listę grup roboczych z dysku.
        Zwraca pustą listę gdy brak pliku.
        """
        path = os.path.join(self.data_dir, self.GROUPS_FILE)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Użytkownicy
    # ------------------------------------------------------------------

    def load_users(self) -> dict:
        """
        Wczytuje mapę użytkowników z dysku.
        Normalizuje starszy format {uid: "Imię Nazwisko"} do
        {uid: {"name": str, "photo": None}}.
        Zwraca pusty słownik gdy brak pliku.
        """
        path = os.path.join(self.data_dir, self.USERS_FILE)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)

            # Migracja starszego formatu: wartość to string, nie słownik
            if loaded and isinstance(next(iter(loaded.values())), str):
                return {k: {"name": v, "photo": None} for k, v in loaded.items()}

            return loaded
        except Exception:
            return {}

    def users_file_exists(self) -> bool:
        """Czy plik users_list.json istnieje (decyduje czy pobierać z API)."""
        return os.path.exists(os.path.join(self.data_dir, self.USERS_FILE))

    