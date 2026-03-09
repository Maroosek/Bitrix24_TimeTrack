"""
helpers.py — Funkcje pomocnicze: ścieżki, formatowanie dat i czasu.
"""
import os
import sys
from datetime import datetime, timezone, timedelta


def get_data_dir() -> str:
    """Zwraca ścieżkę do katalogu z danymi i tworzy wymagane podkatalogi."""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    data_dir = os.path.join(base_dir, "bitrix_data")
    for sub in ("", "details", "chats", "photos"):
        os.makedirs(os.path.join(data_dir, sub), exist_ok=True)
    return data_dir


def seconds_to_readable(seconds) -> str:
    """Konwertuje sekundy na format HH:MM:SS."""
    try:
        seconds = int(seconds)
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02}:{m:02}:{s:02}"
    except (ValueError, TypeError):
        return "00:00:00"


def format_date(date_string: str) -> str:
    """Formatuje string daty ISO do 'YYYY-MM-DD HH:MM' w strefie +01:00."""
    if not date_string:
        return ""
    try:
        dt = datetime.fromisoformat(date_string)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone(timedelta(hours=1)))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        try:
            return datetime.fromisoformat(
                date_string.split("+")[0]
            ).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return date_string


def parse_to_aware_datetime(date_string: str):
    """Parsuje string daty na świadomy obiekt datetime (+01:00). Zwraca None przy błędzie."""
    if not date_string:
        return None
    try:
        dt = datetime.fromisoformat(date_string)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone(timedelta(hours=1)))
        return dt
    except Exception:
        try:
            dt = datetime.fromisoformat(date_string.split("+")[0])
            return dt.replace(tzinfo=timezone(timedelta(hours=1)))
        except Exception:
            return None


def days_since(date_string: str):
    """Zwraca liczbę dni kalendarzowych od podanej daty lub None."""
    if not date_string:
        return None
    try:
        dt = datetime.strptime(date_string, "%Y-%m-%d %H:%M").date()
        return (datetime.now().date() - dt).days
    except Exception:
        return None
