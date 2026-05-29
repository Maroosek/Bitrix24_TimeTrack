"""
view/task_utils.py — Wspólne funkcje pomocnicze dla widoków zadań.

Używane przez: card_view.py, kanban_view.py, app.py
Eliminuje duplikacje ekstrakcji danych, logiki timerów i interakcji UI.
"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime, timezone, timedelta
from typing import Callable

from config import C, FONT_SMALL
from helpers import (
    format_date, parse_to_aware_datetime,
    seconds_to_readable, days_since,
)


# ==============================================================================
# Ekstrakcja danych z zadania
# ==============================================================================

def get_person_name(task: dict, name_key: str, last_key: str, nested_key: str) -> str:
    """
    Zwraca imię i nazwisko osoby z zadania, obsługując oba formaty API
    (klucze wielkie RESPONSIBLE_NAME oraz zagnieżdżony słownik 'responsible').

    Przykład:
        get_person_name(task, "RESPONSIBLE_NAME", "RESPONSIBLE_LAST_NAME", "responsible")
        get_person_name(task, "CREATED_BY_NAME",  "CREATED_BY_LAST_NAME",  "creator")
    """
    name = f"{task.get(name_key, '')} {task.get(last_key, '')}".strip()
    if not name and nested_key in task:
        nested = task[nested_key]
        name   = f"{nested.get('name', '')} {nested.get('lastName', '')}".strip()
    return name


def get_responsible(task: dict) -> str:
    return get_person_name(task, "RESPONSIBLE_NAME", "RESPONSIBLE_LAST_NAME", "responsible")


def get_creator(task: dict) -> str:
    return get_person_name(task, "CREATED_BY_NAME", "CREATED_BY_LAST_NAME", "creator")


def get_responsible_id(task: dict) -> str:
    rid = str(task.get("RESPONSIBLE_ID") or task.get("responsibleId") or "")
    if not rid and "responsible" in task:
        rid = str(task["responsible"].get("id", ""))
    return rid


def get_creator_id(task: dict) -> str:
    cid = str(task.get("CREATED_BY") or "")
    if not cid and "creator" in task:
        cid = str(task["creator"].get("id", ""))
    return cid


def get_base_time(task: dict) -> int:
    """Zwraca czas spędzony na zadaniu w sekundach (int, min. 0)."""
    raw = task.get("TIME_SPENT_IN_LOGS") or task.get("timeSpentInLogs")
    try:
        return int(raw) if raw not in (None, "None", "null", "") else 0
    except (TypeError, ValueError):
        return 0


def get_participants(task: dict) -> list[tuple[str, str]]:
    """
    Zwraca listę (uid, name) uczestników zadania (accomplicesData).
    Obsługuje oba formaty: dict {uid: {name:...}} oraz list [{id:.., name:...}].
    """
    result: list[tuple[str, str]] = []
    acc = task.get("accomplicesData")
    if isinstance(acc, dict):
        for uid, ud in acc.items():
            if isinstance(ud, dict) and ud.get("name"):
                result.append((str(uid), ud["name"]))
    elif isinstance(acc, list):
        for ud in acc:
            if isinstance(ud, dict) and ud.get("name"):
                result.append((str(ud.get("id", "")), ud["name"]))
    return result


def get_participants_names(task: dict) -> list[str]:
    """Zwraca tylko nazwy uczestników (bez uid)."""
    return [name for _, name in get_participants(task)]


def get_activity_dt(task: dict):
    """Zwraca świadomy datetime ostatniej aktywności lub None."""
    raw = task.get("ACTIVITY_DATE") or task.get("activityDate") or ""
    return parse_to_aware_datetime(raw)


def is_today_active(task: dict) -> bool:
    """Czy zadanie było aktywne dziś (używane do rejestracji live timera)."""
    act_dt = get_activity_dt(task)
    if not act_dt:
        return False
    today = datetime.now(timezone(timedelta(hours=1))).date()
    return act_dt.date() == today


# ==============================================================================
# Logika live timerów (wspólna dla card_view i kanban_view)
# ==============================================================================

def tick_timers(timer_refs: dict, now: datetime | None = None) -> None:
    """
    Aktualizuje StringVar timerów dla jednego taktu zegara.

    Reguły:
    - Zadanie z uczestnikami: zawsze tyka.
    - Zadanie bez uczestników: tyka tylko to o najnowszej dacie aktywności
      dla danego pracownika (zapobiega podwójnemu liczeniu).

    timer_refs: dict {task_id: {"var": StringVar, "base": int,
                                "start": datetime, "resp": str,
                                "has_participants": bool}}
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # 1. Najnowsza aktywność per pracownik (ignoruj zadania z uczestnikami)
    latest_for_resp: dict = {}
    for data in timer_refs.values():
        if not data.get("has_participants"):
            resp = data.get("resp")
            dt   = data["start"]
            if resp not in latest_for_resp or dt > latest_for_resp[resp]:
                latest_for_resp[resp] = dt

    # 2. Tick
    for data in timer_refs.values():
        should_tick = (
            data.get("has_participants") or
            data["start"] == latest_for_resp.get(data.get("resp"))
        )
        if should_tick:
            elapsed = (now - data["start"]).total_seconds()
            if elapsed > 0:
                try:
                    data["var"].set(f"⏱ {seconds_to_readable(data['base'] + int(elapsed))}")
                except tk.TclError:
                    pass


def register_timer(timer_refs: dict, task: dict, time_var: tk.StringVar,
                   resp: str, participants_info: list) -> None:
    """
    Rejestruje zadanie w słowniku timerów jeśli spełnia warunki
    (status 'W trakcie' + aktywność dzisiaj).
    """
    real_status = str(task.get("REAL_STATUS") or task.get("status", ""))
    if real_status != "3":
        return

    act_dt = get_activity_dt(task)
    if not act_dt:
        return

    today = datetime.now(timezone(timedelta(hours=1))).date()
    if act_dt.date() != today:
        return

    t_id = str(task.get("ID") or task.get("id", ""))
    timer_refs[t_id] = {
        "var":              time_var,
        "base":             get_base_time(task),
        "start":            act_dt,
        "resp":             resp,
        "has_participants": bool(participants_info),
    }


# ==============================================================================
# Interakcja UI — hover + klik
# ==============================================================================

def all_children(widget: tk.Widget) -> list[tk.Widget]:
    """Zwraca widget i wszystkich jego potomków rekurencyjnie."""
    result = [widget]
    for child in widget.winfo_children():
        result.extend(all_children(child))
    return result


def bind_hover_click(
    outer: tk.Frame,
    card: tk.Frame,
    task_id: str,
    on_click: Callable[[str], None],
    bg_card: str | None = None,
    bg_hover: str | None = None,
    bg_border: str | None = None,
    bg_accent: str | None = None,
) -> None:
    """
    Binduje efekt hover (podświetlenie) i klik na karcie zadania.

    Parametry kolorów domyślnie brane z C[] — można nadpisać dla testów.
    """
    _card   = bg_card   or C["card"]
    _hover  = bg_hover  or C["card_hover"]
    _border = bg_border or C["card_border"]
    _accent = bg_accent or C["accent"]

    def _enter(_event) -> None:
        outer.config(bg=_accent)
        for w in all_children(card):
            try:
                if w.cget("bg") == _card:
                    w.config(bg=_hover)
            except Exception:
                pass

    def _leave(_event) -> None:
        outer.config(bg=_border)
        for w in all_children(card):
            try:
                if w.cget("bg") == _hover:
                    w.config(bg=_card)
            except Exception:
                pass

    def _click(_event, tid: str = task_id) -> None:
        on_click(tid)

    for w in all_children(outer):
        w.bind("<Enter>",    _enter)
        w.bind("<Leave>",    _leave)
        w.bind("<Button-1>", _click)


# ==============================================================================
# Rendering uczestników (wspólny dla card_view i kanban_view)
# ==============================================================================

def render_avatar_row(
    parent: tk.Frame,
    uid: str,
    name: str,
    users_map: dict,
    get_avatar_fn: Callable,
    size: int = 20,
    max_name_len: int = 28,
) -> None:
    """
    Renderuje wiersz z awatarem i imieniem użytkownika w podanym kontenerze.
    Używane dla odpowiedzialnego, twórcy i uczestników.
    """
    row = tk.Frame(parent, bg=C["card"])
    row.pack(side="top", anchor="w", pady=(0, 2))

    photo = None
    if uid and uid in users_map:
        ud = users_map[uid]
        if isinstance(ud, dict):
            photo = get_avatar_fn(uid, ud.get("photo"), size)

    if photo:
        tk.Label(row, image=photo, bg=C["card"]).pack(side="left")
    else:
        tk.Label(row, text="👤", bg=C["card"], fg=C["text_muted"],
                 font=FONT_SMALL).pack(side="left")

    disp = name if len(name) <= max_name_len else name[:max_name_len - 3] + "..."
    tk.Label(row, text=disp, bg=C["card"], fg=C["text_muted"],
             font=FONT_SMALL).pack(side="left", padx=(4, 0))


def render_participants_block(
    parent: tk.Frame,
    participants_info: list[tuple[str, str]],
    users_map: dict,
    get_avatar_fn: Callable,
    limit: int = 3,
) -> None:
    """
    Renderuje blok uczestników z ikonką 👥 i listą (maks. `limit` wierszy).
    Resztę pokazuje jako "+ N innych".
    """
    if not participants_info:
        return

    pr = tk.Frame(parent, bg=C["card"])
    pr.pack(fill="x", pady=2)
    tk.Label(pr, text="👥", bg=C["card"], fg=C["text_muted"],
             font=FONT_SMALL).pack(side="left", anchor="nw")

    p_sub = tk.Frame(pr, bg=C["card"])
    p_sub.pack(side="left", fill="x", padx=3)

    for p_id, p_name in participants_info[:limit]:
        render_avatar_row(p_sub, p_id, p_name, users_map, get_avatar_fn)

    extra = len(participants_info) - limit
    if extra > 0:
        tk.Label(p_sub, text=f"+ {extra} innych",
                 bg=C["card"], fg=C["accent"],
                 font=FONT_SMALL).pack(side="top", anchor="w", padx=(2, 0))


# ==============================================================================
# Kolorowanie aktywności (wspólne)
# ==============================================================================

def activity_color(days_ago: int | None) -> str:
    """Zwraca kolor etykiety aktywności na podstawie liczby dni."""
    if days_ago is None or days_ago < 3:
        return C["text_muted"]
    if days_ago >= 7:
        return C["btn_red"]
    return "#F59E0B"