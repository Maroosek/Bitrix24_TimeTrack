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
from PIL import Image, ImageTk, ImageDraw
import io
from datetime import datetime, timezone, timedelta

# Konfiguracja
WEBHOOK_URL = os.environ.get("BITRIX_WEBHOOK", "https://jenaeuropa.bitrix24.pl/rest/223/8cd46qmskggzo81m/")

STATUS_MAP = {
    "1": "Nowe",
    "2": "Oczekujące",
    "3": "W trakcie",
    "4": "Do kontroli",
    "5": "Zakończone",
    "6": "Odłożone"
}

STATUS_COLORS = {
    "Nowe": "#3B82F6",
    "Oczekujące": "#F59E0B",
    "W trakcie": "#10B981",
    "Do kontroli": "#8B5CF6",
    "Zakończone": "#6B7280",
    "Odłożone": "#EF4444",
}

# Paleta kolorów
C = {
    "bg": "#0F172A",  # tło główne (ciemny granat)
    "sidebar": "#1E293B",  # boczny panel
    "card": "#1E293B",  # karta
    "card_hover": "#293548",
    "card_border": "#334155",
    "header": "#0F172A",
    "accent": "#38BDF8",  # jasny niebieski akcent
    "accent2": "#818CF8",  # fiolet
    "text": "#E2E8F0",
    "text_muted": "#94A3B8",
    "text_dark": "#64748B",
    "btn_green": "#10B981",
    "btn_blue": "#3B82F6",
    "btn_red": "#EF4444",
    "input_bg": "#1E293B",
    "input_border": "#334155",
    "divider": "#1E3A5F",
    "tag_bg": "#0F3460",
    "tag_text": "#7DD3FC",
}

FONT_TITLE = ("Segoe UI Semibold", 11)
FONT_BODY = ("Segoe UI", 9)
FONT_SMALL = ("Segoe UI", 8)
FONT_HEADING = ("Segoe UI Semibold", 13)
FONT_MONO = ("Consolas", 9)


# Helpers
def get_data_dir():
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "bitrix_data")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.join(data_dir, "details"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "chats"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "photos"), exist_ok=True)
    return data_dir


def seconds_to_readable(seconds):
    try:
        seconds = int(seconds)
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02}:{m:02}:{s:02}"
    except (ValueError, TypeError):
        return "00:00:00"


def format_date(date_string):
    if not date_string:
        return ""
    try:
        dt = datetime.fromisoformat(date_string)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone(timedelta(hours=1)))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        try:
            return datetime.fromisoformat(date_string.split("+")[0]).strftime("%Y-%m-%d %H:%M")
        except:
            return date_string


def parse_to_aware_datetime(date_string):
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
        except:
            return None


def days_since(date_string):
    """Zwraca liczbę dni kalendarzowych od daty (od północy), lub None."""
    if not date_string:
        return None
    try:
        # Konwertujemy string na obiekt datetime, a następnie pobieramy samą datę (.date())
        dt = datetime.strptime(date_string, "%Y-%m-%d %H:%M").date()
        today = datetime.now().date()

        # Różnica między samymi datami zadziała zgodnie z kalendarzem
        return (today - dt).days
    except:
        return None


# Styl ttk
def apply_dark_style(root):
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure("Treeview",
                    background=C["card"],
                    foreground=C["text"],
                    fieldbackground=C["card"],
                    rowheight=26,
                    borderwidth=0,
                    font=FONT_BODY,
                    relief="flat"
                    )
    style.configure("Treeview.Heading",
                    background=C["sidebar"],
                    foreground=C["accent"],
                    font=FONT_BODY,
                    borderwidth=0,
                    relief="flat"
                    )
    style.map("Treeview",
              background=[("selected", C["accent2"])],
              foreground=[("selected", "#FFFFFF")]
              )
    style.configure("Vertical.TScrollbar",
                    background=C["sidebar"],
                    troughcolor=C["bg"],
                    arrowcolor=C["text_muted"],
                    borderwidth=0
                    )
    style.configure("Horizontal.TScrollbar",
                    background=C["sidebar"],
                    troughcolor=C["bg"],
                    arrowcolor=C["text_muted"],
                    borderwidth=0
                    )
    style.configure("TCombobox",
                    fieldbackground=C["input_bg"],
                    background=C["input_bg"],
                    foreground=C["text"],
                    selectbackground=C["accent2"],
                    selectforeground="#fff",
                    borderwidth=1,
                    relief="flat"
                    )
    style.map("TCombobox",
              fieldbackground=[("readonly", C["input_bg"])],
              foreground=[("readonly", C["text"])]
              )


# Pomocnicze widgety
class ModernButton(tk.Button):
    def __init__(self, master, text, command, color=None, width=None, **kwargs):
        color = color or C["btn_blue"]
        super().__init__(
            master, text=text, command=command,
            bg=color, fg="#FFFFFF",
            font=FONT_BODY,
            relief="flat", bd=0, cursor="hand2",
            padx=14, pady=7,
            activebackground=color,
            activeforeground="#FFFFFF",
            width=width or 0,
            **kwargs
        )
        self._color = color
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, e):
        self.config(bg=self._lighten(self._color))

    def _on_leave(self, e):
        self.config(bg=self._color)

    @staticmethod
    def _lighten(hex_color):
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        r = min(255, r + 30)
        g = min(255, g + 30)
        b = min(255, b + 30)
        return f"#{r:02x}{g:02x}{b:02x}"


class ModernCheckbutton(tk.Checkbutton):
    def __init__(self, master, text, variable, command=None, **kwargs):
        super().__init__(
            master, text=text, variable=variable,
            command=command,
            bg=C["sidebar"], fg=C["text_muted"],
            selectcolor=C["bg"],
            activebackground=C["sidebar"],
            activeforeground=C["text"],
            font=FONT_SMALL,
            relief="flat", bd=0, cursor="hand2",
            **kwargs
        )


# Kafelkowy widok zadań
class TaskCardView(tk.Frame):
    """Siatka kafelków Trello-style — stałe rozmiary, live timer, pełne szczegóły."""

    CARD_W = 290  # stała szerokość karty
    CARD_H = 240  # stała wysokość karty
    CARD_PAD = 12
    CARD_GAP = 10

    def __init__(self, master, app, on_open_cb, **kwargs):
        super().__init__(master, bg=C["bg"], **kwargs)
        self.app = app
        self.on_open_cb = on_open_cb
        self._tasks = []
        self._timer_refs = {}  # item_id -> {"var": StringVar, "base": int, "start_dt": datetime}

        self._canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0)
        self._vsb = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vsb.set)
        self._vsb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._inner = tk.Frame(self._canvas, bg=C["bg"])
        self._cw = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")

        self._inner.bind("<Configure>", lambda e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        self._canvas.bind_all("<MouseWheel>", self._on_scroll)

        # Live timer loop
        self._live = True
        self._run_timers()

    def _on_canvas_resize(self, e):
        self._canvas.itemconfig(self._cw, width=e.width)
        self._relayout()

    def _on_scroll(self, e):
        self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    def load_tasks(self, tasks):
        # Sortuj po activityDate malejąco (najnowsze pierwsze)
        def _key(t):
            raw = t.get("ACTIVITY_DATE") or t.get("activityDate") or ""
            dt = parse_to_aware_datetime(raw)
            return dt.timestamp() if dt else 0

        self._tasks = sorted(tasks, key=_key, reverse=True)
        self._timer_refs.clear()
        self._build_cards()

    def _cols(self):
        w = self._canvas.winfo_width()
        if w < 10:
            w = 900
        return max(1, (w - self.CARD_GAP) // (self.CARD_W + self.CARD_GAP))

    def _build_cards(self):
        for w in self._inner.winfo_children():
            w.destroy()
        self._timer_refs.clear()

        cols = self._cols()
        for idx, task in enumerate(self._tasks):
            col = idx % cols
            row = idx // cols
            card = self._make_card(self._inner, task, idx)
            card.grid(row=row, column=col,
                      padx=self.CARD_GAP, pady=self.CARD_GAP,
                      sticky="nw")

    def _relayout(self):
        if self._tasks:
            self._build_cards()

    def _make_card(self, parent, task, idx):
        t_id = str(task.get("ID") or task.get("id", ""))
        title = task.get("TITLE") or task.get("title", "Bez tytułu")

        # Odpowiedzialny
        resp = f"{task.get('RESPONSIBLE_NAME', '')} {task.get('RESPONSIBLE_LAST_NAME', '')}".strip()
        if not resp and 'responsible' in task:
            r = task['responsible']
            resp = f"{r.get('name', '')} {r.get('lastName', '')}".strip()

        # Uczestnicy
        participants_info = []
        acc = task.get("accomplicesData")
        if isinstance(acc, dict):
            for uid, ud in acc.items():
                if isinstance(ud, dict) and ud.get("name"):
                    participants_info.append((str(uid), ud["name"]))
        elif isinstance(acc, list):
            for ud in acc:
                if isinstance(ud, dict) and ud.get("name"):
                    uid = str(ud.get("id", ""))
                    participants_info.append((uid, ud["name"]))

        # Czas
        raw_time = task.get("TIME_SPENT_IN_LOGS") or task.get("timeSpentInLogs")
        try:
            base_time = int(raw_time) if raw_time not in (None, "None", "null", "") else 0
        except:
            base_time = 0

        deadline = format_date(task.get("DEADLINE") or task.get("deadline", ""))
        raw_activity = task.get("ACTIVITY_DATE") or task.get("activityDate", "")
        activity_str = format_date(raw_activity)
        days_ago = days_since(activity_str)
        real_status = str(task.get("REAL_STATUS") or task.get("status", ""))
        is_running = (real_status == "3")

        # ── Outer = border ─────────────────────────────────────────────────
        outer = tk.Frame(parent, bg=C["card_border"], cursor="hand2",
                         width=self.CARD_W + 2, height=self.CARD_H + 2)
        outer.pack_propagate(False)

        card = tk.Frame(outer, bg=C["card"],
                        width=self.CARD_W, height=self.CARD_H)
        card.pack_propagate(False)
        card.pack(fill="both", expand=True, padx=1, pady=1)

        # ── Wnętrze z paddingiem
        inner = tk.Frame(card, bg=C["card"], padx=self.CARD_PAD, pady=8)
        inner.pack(fill="both", expand=True)

        # ─ Wiersz 1: ID + Twórca + status aktywności ──────────────────────────────
        r1 = tk.Frame(inner, bg=C["card"])
        r1.pack(fill="x")

        # ID Zadania
        tk.Label(r1, text=f"#{t_id}", bg=C["card"], fg=C["text_muted"],
                 font=FONT_SMALL).pack(side="left", padx=(0, 6))

        # --- Pobieranie Twórcy ---
        creator_name = f"{task.get('CREATED_BY_NAME', '')} {task.get('CREATED_BY_LAST_NAME', '')}".strip()
        creator_id = str(task.get("CREATED_BY") or "")

        # Fallback (gdyby Bitrix zwrócił inne pola)
        if not creator_name and 'creator' in task:
            c = task['creator']
            creator_name = f"{c.get('name', '')} {c.get('lastName', '')}".strip()
            if not creator_id:
                creator_id = str(c.get('id', ''))

        creator_photo = None
        if creator_id and creator_id in self.app.users_map:
            user_data = self.app.users_map[creator_id]
            if isinstance(user_data, dict):
                creator_photo = self.app.get_user_avatar(creator_id, user_data.get("photo"))

        # --- Rysowanie Twórcy obok ID ---
        if creator_name:
            c_f = tk.Frame(r1, bg=C["card"])
            c_f.pack(side="left")

            if creator_photo:
                tk.Label(c_f, image=creator_photo, bg=C["card"]).pack(side="left")
            else:
                tk.Label(c_f, text="👤", bg=C["card"], fg=C["text_muted"], font=FONT_SMALL).pack(side="left")

            # Skracamy imię twórcy by nie nachodziło na status po prawej stronie
            disp_c_name = creator_name if len(creator_name) <= 15 else creator_name[:12] + "..."
            tk.Label(c_f, text=disp_c_name, bg=C["card"], fg=C["text_muted"], font=FONT_SMALL).pack(side="left",
                                                                                                    padx=(4, 0))

        # --- Status Aktywności ---
        if is_running:
            dot = tk.Label(r1, text="● W trakcie", bg=C["card"],
                           fg=C["btn_green"], font=FONT_SMALL)
        else:
            dot = tk.Label(r1, text="○", bg=C["card"],
                           fg=C["text_dark"], font=FONT_SMALL)
        dot.pack(side="right")

        # ─ Tytuł (maks 2 linie)
        short_title = title if len(title) <= 55 else title[:52] + "..."
        tk.Label(inner, text=short_title, bg=C["card"], fg=C["text"],
                 font=FONT_TITLE, wraplength=self.CARD_W - 2 * self.CARD_PAD - 4,
                 justify="left", anchor="w").pack(fill="x", pady=(4, 4))

        # ─ Separator
        tk.Frame(inner, bg=C["card_border"], height=1).pack(fill="x", pady=(0, 5))

        # ─ Odpowiedzialny
        if resp:
            rr = tk.Frame(inner, bg=C["card"])
            rr.pack(fill="x", pady=1)

            # Pobieramy ID pracownika
            resp_id = str(task.get("RESPONSIBLE_ID") or task.get("responsibleId") or "")
            if not resp_id and 'responsible' in task:
                resp_id = str(task['responsible'].get('id', ''))

            resp_photo = None
            if resp_id and resp_id in self.app.users_map:
                user_data = self.app.users_map[resp_id]
                if isinstance(user_data, dict):
                    resp_photo = self.app.get_user_avatar(resp_id, user_data.get("photo"))

            # Wstawiamy zdjęcie lub standardową ikonę
            if resp_photo:
                tk.Label(rr, image=resp_photo, bg=C["card"]).pack(side="left", anchor="nw", pady=(1, 0))
            else:
                tk.Label(rr, text="👤", bg=C["card"], fg=C["text_muted"],
                         font=FONT_SMALL).pack(side="left", anchor="nw")

            disp = resp if len(resp) <= 28 else resp[:25] + "..."
            tk.Label(rr, text=disp, bg=C["card"], fg=C["text"],
                     font=FONT_SMALL).pack(side="left", padx=3, anchor="nw")

            # ─ Uczestnicy
            if participants_info:
                pr = tk.Frame(inner, bg=C["card"])
                pr.pack(fill="x", pady=2)

                # Główna ikona uczestników (przyklejona do lewego górnego rogu)
                tk.Label(pr, text="👥", bg=C["card"], fg=C["text_muted"],
                         font=FONT_SMALL).pack(side="left", anchor="nw")

                # Kontener na pionową listę uczestników
                p_sub = tk.Frame(pr, bg=C["card"])
                p_sub.pack(side="left", fill="x", padx=3)

                # Ograniczamy widoczność, by nie rozepchać kafelka w dół (np. do max 3 osób)
                limit = 3
                displayed = participants_info[:limit]

                for p_id, p_name in displayed:
                    p_photo = None
                    if p_id and p_id in self.app.users_map:
                        user_data = self.app.users_map[p_id]
                        if isinstance(user_data, dict):
                            p_photo = self.app.get_user_avatar(p_id, user_data.get("photo"))

                    # Każdy użytkownik to osobny wiersz układany od góry (side="top")
                    u_f = tk.Frame(p_sub, bg=C["card"])
                    u_f.pack(side="top", anchor="w", pady=(0, 3))

                    # Ikona lub zdjęcie
                    if p_photo:
                        tk.Label(u_f, image=p_photo, bg=C["card"]).pack(side="left")
                    else:
                        tk.Label(u_f, text="👤", bg=C["card"], fg=C["text_muted"], font=FONT_SMALL).pack(side="left")

                    # Imię pracownika (mamy teraz więcej miejsca, więc tniemy dopiero po np. 28 znakach)
                    disp_name = p_name if len(p_name) <= 28 else p_name[:25] + "..."

                    tk.Label(u_f, text=disp_name, bg=C["card"], fg=C["text_muted"],
                             font=FONT_SMALL).pack(side="left", padx=(4, 0))

                # Jeśli jest ich więcej niż limit, dodajemy na dole informację "+ X innych"
                if len(participants_info) > limit:
                    tk.Label(p_sub, text=f"+ {len(participants_info) - limit} innych",
                             bg=C["card"], fg=C["accent"], font=FONT_SMALL).pack(side="top", anchor="w", padx=(2, 0))

        # ─ Deadline
        if deadline:
            dr = tk.Frame(inner, bg=C["card"])
            dr.pack(fill="x", pady=1)
            dl_color = C["btn_red"] if deadline < datetime.now().strftime("%Y-%m-%d %H:%M") else C["text_muted"]
            tk.Label(dr, text="📅", bg=C["card"], fg=C["text_muted"],
                     font=FONT_SMALL).pack(side="left")
            tk.Label(dr, text=deadline, bg=C["card"], fg=dl_color,
                     font=FONT_SMALL).pack(side="left", padx=3)

        # Wypychacz
        tk.Frame(inner, bg=C["card"]).pack(fill="both", expand=True)

        # Separator przed stopką
        tk.Frame(inner, bg=C["card_border"], height=1).pack(fill="x", pady=(4, 4))

        # Stopka: timer + aktywność
        footer = tk.Frame(inner, bg=C["card"])
        footer.pack(fill="x", side="bottom")

        # Timer (live dla W trakcie)
        time_var = tk.StringVar(value=f"⏱ {seconds_to_readable(base_time)}")
        time_lbl = tk.Label(footer, textvariable=time_var, bg=C["card"],
                            fg=C["accent"], font=FONT_MONO)
        time_lbl.pack(side="left")

        # Aktywność po prawej
        if activity_str:
            if days_ago is None or days_ago < 3:
                act_color = C["text_muted"]
            elif days_ago >= 7:
                act_color = C["btn_red"]
            else:
                act_color = "#F59E0B"
            ago_text = "dziś" if (not days_ago or days_ago == 0) else f"{days_ago}d temu"
            tk.Label(footer, text=f"🕐 {ago_text}", bg=C["card"],
                     fg=act_color, font=FONT_SMALL).pack(side="right")

        # Rejestruj timer dla zadań "W trakcie" (tylko z dzisiejszą aktywnością)
        if is_running:
            act_dt = parse_to_aware_datetime(raw_activity)
            if act_dt:
                today_date = datetime.now(timezone(timedelta(hours=1))).date()
                if act_dt.date() == today_date:
                    self._timer_refs[t_id] = {
                        "var": time_var,
                        "base": base_time,
                        "start": act_dt,
                    }

        # Hover + klik (teraz bezpieczny dla innych kolorów)
        def _all(w):
            res = [w]
            for ch in w.winfo_children():
                res.extend(_all(ch))
            return res

        def _enter(e):
            outer.config(bg=C["accent"])
            for w in _all(card):
                try:
                    if w.cget("bg") == C["card"]:
                        w.config(bg=C["card_hover"])
                except:
                    pass

        def _leave(e):
            outer.config(bg=C["card_border"])
            for w in _all(card):
                try:
                    if w.cget("bg") == C["card_hover"]:
                        w.config(bg=C["card"])
                except:
                    pass

        def _click(e, tid=t_id):
            self.on_open_cb(tid)

        for w in _all(outer):
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)
            w.bind("<Button-1>", _click)

        return outer

    def _run_timers(self):
        """Aktualizuje live timery na kafelkach co sekundę."""
        if not self._live:
            return
        now = datetime.now(timezone.utc)
        for tid, data in list(self._timer_refs.items()):
            elapsed = (now - data["start"]).total_seconds()
            if elapsed > 0:
                total = data["base"] + int(elapsed)
                try:
                    data["var"].set(f"⏱ {seconds_to_readable(total)}")
                except tk.TclError:
                    pass
        self.after(1000, self._run_timers)

    def get_all_task_ids(self):
        return [str(t.get("ID") or t.get("id", "")) for t in self._tasks]


# Główna aplikacja
class BitrixApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Bitrix24 — Task Manager")
        self.root.geometry("1300x820")  # Zwiększamy nieco minimalną szerokość, żeby wszystko weszło
        self.root.configure(bg=C["bg"])
        apply_dark_style(root)

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
        self.live_timer_var = tk.BooleanVar(value=False)
        self.hide_inactive_var = tk.BooleanVar(value=False)

        # Tryb wyświetlania zadań: "cards" lub "list" — wczytany z configu
        saved_mode = self._load_display_mode()
        self.display_mode = tk.StringVar(value=saved_mode)

        self.current_group_view_id = None
        self.current_group_view_name = None
        self.is_fetching = False
        self.active_tree_timers = {}

        self.task_columns = (
            "ID", "TITLE", "REAL_STATUS", "TIME_SPENT",
            "CREATED_BY", "RESPONSIBLE", "PARTICIPANTS", "DEADLINE",
            "CREATED_DATE", "ACTIVITY_DATE", "CHANGED_DATE",
            "STATUS_CHANGED_DATE", "GROUP"
        )
        self.group_columns = ("ID", "NAME", "DESCRIPTION", "OWNER_ID", "DATE_CREATE", "DATE_ACTIVITY")

        self._build_ui()
        self.load_local_data()
        self._run_live_timers()
        self._schedule_auto_refresh()

    # UI Construction

    def _build_ui(self):
        # Topbar
        topbar = tk.Frame(self.root, bg=C["header"], pady=0)
        topbar.pack(fill="x")

        # Logo strip
        logo_strip = tk.Frame(topbar, bg=C["header"])
        logo_strip.pack(fill="x")

        accent_line = tk.Frame(logo_strip, bg=C["accent"], width=4)
        accent_line.pack(side="left", fill="y", padx=(0, 12))

        tk.Label(logo_strip, text="BITRIX24", bg=C["header"], fg=C["accent"],
                 font=("Segoe UI Black", 16)).pack(side="left", pady=8)
        tk.Label(logo_strip, text="Task Manager", bg=C["header"], fg=C["text_muted"],
                 font=("Segoe UI Light", 12)).pack(side="left", padx=(6, 0), pady=8)

        # Status label po prawej
        self.status_var = tk.StringVar(value="")
        tk.Label(logo_strip, textvariable=self.status_var, bg=C["header"],
                 fg=C["accent"], font=("Segoe UI Italic", 9)).pack(side="right", padx=14)

        # Separator
        tk.Frame(self.root, bg=C["accent"], height=2).pack(fill="x")

        # ==========================================
        # TOOLBAR (podzielony na dwa wiersze, żeby wszystko się mieściło na mniejszych ekranach)
        # ==========================================

        # Tworzymy główny kontener dla paska narzędzi, by móc w nim zawijać elementy
        toolbar_container = tk.Frame(self.root, bg=C["sidebar"], pady=4)
        toolbar_container.pack(fill="x")

        # --- PIERWSZY WIERSZ (Przyciski akcji, Widoki) ---
        toolbar_row1 = tk.Frame(toolbar_container, bg=C["sidebar"])
        toolbar_row1.pack(fill="x", padx=12, pady=2)

        left = tk.Frame(toolbar_row1, bg=C["sidebar"])
        left.pack(side="left")

        # Radiobuttons styl
        for val, lbl in [("tasks", "📋 Zadania"), ("groups", "🗂 Grupy")]:
            rb = tk.Radiobutton(
                left, text=lbl, variable=self.current_view, value=val,
                command=self.switch_view,
                bg=C["sidebar"], fg=C["text"], selectcolor=C["accent"],
                activebackground=C["sidebar"], activeforeground=C["accent"],
                font=FONT_BODY, relief="flat", bd=0, cursor="hand2",
                indicatoron=False, padx=6, pady=4,
            )
            rb.pack(side="left", padx=1)

        tk.Frame(left, bg=C["card_border"], width=1).pack(side="left", fill="y", padx=6)

        self.btn_fetch = ModernButton(left, "⟳ Odśwież", command=self.fetch_data, color=C["btn_green"])
        self.btn_fetch.pack(side="left", padx=2)

        # Zapisz referencję do przycisku akcji i separatora, by móc je ukrywać
        self.btn_action = ModernButton(left, "↗ Otwórz zadanie", command=self.handle_main_action, color=C["btn_blue"])
        self.btn_action.pack(side="left", padx=2)

        self.action_separator = tk.Frame(left, bg=C["card_border"], width=1)
        self.action_separator.pack(side="left", fill="y", padx=6)

        # Przełącznik widoku: Kafelki / Lista
        self.view_toggle_frame = tk.Frame(left, bg=C["sidebar"], highlightthickness=1,
                                          highlightbackground=C["card_border"])
        self.view_toggle_frame.pack(side="left", padx=2)

        def _make_toggle(parent, text, mode_val):
            btn = tk.Button(
                parent, text=text,
                bg=C["accent"] if self.display_mode.get() == mode_val else C["sidebar"],
                fg="#000" if self.display_mode.get() == mode_val else C["text_muted"],
                font=FONT_SMALL, relief="flat", bd=0, cursor="hand2",
                padx=8, pady=4,
                activebackground=C["accent"], activeforeground="#000",
            )
            btn.pack(side="left")
            return btn

        self.btn_view_cards = _make_toggle(self.view_toggle_frame, "⊞ Kafelki", "cards")
        self.btn_view_list = _make_toggle(self.view_toggle_frame, "☰ Lista", "list")

        def _set_mode(mode):
            self.display_mode.set(mode)
            # Zaktualizuj wygląd przycisków
            self.btn_view_cards.config(
                bg=C["accent"] if mode == "cards" else C["sidebar"],
                fg="#000" if mode == "cards" else C["text_muted"],
            )
            self.btn_view_list.config(
                bg=C["accent"] if mode == "list" else C["sidebar"],
                fg="#000" if mode == "list" else C["text_muted"],
            )

            # Pokaż/ukryj przycisk "Otwórz zadanie" w zależności od trybu
            if mode == "cards":
                self.btn_action.pack_forget()
                self.action_separator.pack_forget()
            else:
                # Odtwórz widoczność zachowując układ z paska
                self.btn_action.pack(side="left", padx=2, after=self.btn_fetch)
                self.action_separator.pack(side="left", fill="y", padx=6, after=self.btn_action)

            # Pokaż/ukryj checkboxy zalezne od trybu
            if mode == "cards":
                self.chk_live_timer.pack_forget()
                self.chk_hide_inactive.pack_forget()
            else:
                self.chk_live_timer.pack(side="left", padx=6)
                self.chk_hide_inactive.pack(side="left", padx=6)

            self.apply_filter()

        self.btn_view_cards.config(command=lambda: _set_mode("cards"))
        self.btn_view_list.config(command=lambda: _set_mode("list"))

        # Przycisk "Ustaw jako domyślny"
        self.btn_set_default = tk.Button(
            left, text="★ Domyślny",
            bg=C["sidebar"], fg=C["text_muted"],
            font=FONT_SMALL, relief="flat", bd=0, cursor="hand2",
            padx=6, pady=4,
            activebackground=C["tag_bg"], activeforeground=C["accent"],
            command=self._save_display_mode_as_default,
        )
        self.btn_set_default.pack(side="left", padx=(4, 0))

        # --- DRUGI WIERSZ (Filtry) ---
        toolbar_row2 = tk.Frame(toolbar_container, bg=C["sidebar"])
        toolbar_row2.pack(fill="x", padx=12, pady=2)

        right = tk.Frame(toolbar_row2, bg=C["sidebar"])
        right.pack(side="left")  # Zmieniono side na left, by nie "uciekały" przy zwężaniu okna

        # Checkboxy
        self.chk_live_timer = ModernCheckbutton(right, "⏱ Licz czas na żywo",
                                                variable=self.live_timer_var, command=self.apply_filter)
        self.chk_live_timer.pack(side="left", padx=4)

        self.chk_hide_inactive = ModernCheckbutton(right, "🔕 Ukryj nieaktywne >7d",
                                                   variable=self.hide_inactive_var, command=self.apply_filter)
        self.chk_hide_inactive.pack(side="left", padx=4)

        tk.Frame(right, bg=C["card_border"], width=1).pack(side="left", fill="y", padx=6)

        self.filter_frame = tk.Frame(right, bg=C["sidebar"])
        self.filter_frame.pack(side="left")

        self._label(self.filter_frame, "Status:").pack(side="left", padx=(0, 2))
        filter_options = ["Wszystkie"] + list(STATUS_MAP.values())
        self.status_combobox = ttk.Combobox(
            self.filter_frame, textvariable=self.current_filter,
            values=filter_options, state="readonly", width=12
        )
        self.status_combobox.pack(side="left", padx=(0, 6))
        self.status_combobox.bind("<<ComboboxSelected>>", self.on_status_change)

        self._label(self.filter_frame, "Pracownik:").pack(side="left", padx=(0, 2))
        self.resp_combobox = ttk.Combobox(
            self.filter_frame, textvariable=self.current_resp_filter,
            values=["Wszyscy"], width=16
        )
        self.resp_combobox.pack(side="left", padx=(0, 6))
        self.resp_combobox.bind("<<ComboboxSelected>>", self.apply_filter)
        self.resp_combobox.bind("<KeyRelease>", self.on_resp_type)

        self._label(self.filter_frame, "🔍").pack(side="left", padx=(0, 2))
        self.search_entry = tk.Entry(
            self.filter_frame, textvariable=self.search_var,
            bg=C["input_bg"], fg=C["text"], insertbackground=C["text"],
            relief="flat", font=FONT_BODY, width=20,
            highlightthickness=1, highlightbackground=C["input_border"],
            highlightcolor=C["accent"]
        )
        self.search_entry.pack(side="left")
        self.search_entry.bind("<KeyRelease>", self.apply_filter)

        # --- NOWY PRZYCISK RESETOWANIA FILTRÓW ---
        self.btn_reset = tk.Button(
            self.filter_frame, text="✖ Reset",
            bg=C["sidebar"], fg=C["text_muted"],
            font=FONT_SMALL, relief="flat", bd=0, cursor="hand2",
            padx=8, pady=2,
            activebackground=C["btn_red"], activeforeground="#FFF",
            command=self.reset_filters
        )
        self.btn_reset.pack(side="left", padx=(8, 0))

        # Licznik zadań
        self.count_var = tk.StringVar(value="")
        count_bar = tk.Frame(self.root, bg=C["bg"], pady=4)
        count_bar.pack(fill="x")
        tk.Label(count_bar, textvariable=self.count_var, bg=C["bg"],
                 fg=C["text_muted"], font=FONT_SMALL).pack(side="left", padx=14)

        # Etykieta aktualnie wybranego widoku
        self.view_label_var = tk.StringVar(value="")
        tk.Label(count_bar, textvariable=self.view_label_var, bg=C["bg"],
                 fg=C["accent2"], font=("Segoe UI Semibold", 9)).pack(side="right", padx=14)

        # Content area
        self.content_frame = tk.Frame(self.root, bg=C["bg"])
        self.content_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Treeview (dla widoku listy / grup)
        self.tree_frame = tk.Frame(self.content_frame, bg=C["bg"])
        self.tree_frame.pack(fill="both", expand=True)

        tree_scroll = ttk.Scrollbar(self.tree_frame, orient="vertical")
        tree_scroll.pack(side="right", fill="y")
        tree_scroll_x = ttk.Scrollbar(self.tree_frame, orient="horizontal")
        tree_scroll_x.pack(side="bottom", fill="x")

        self.tree = ttk.Treeview(
            self.tree_frame, columns=self.task_columns, show="headings",
            yscrollcommand=tree_scroll.set, xscrollcommand=tree_scroll_x.set,
            style="Treeview"
        )
        tree_scroll.config(command=self.tree.yview)
        tree_scroll_x.config(command=self.tree.xview)

        for col in self.task_columns:
            self.tree.heading(col, text=col, command=lambda c=col: self.sort_treeview(c, False))
            self.tree.column(col, width=100)

        self.tree.pack(side="left", fill="both", expand=True)

        # Siatka kafelków (dla "W trakcie")
        self.card_view = TaskCardView(self.content_frame, app=self, on_open_cb=self._open_task_by_id)
        # Na początku ukryta

        self._card_mode = False

        # Ustaw domyślny układ
        _set_mode(self.display_mode.get())

    def _label(self, parent, text):
        return tk.Label(parent, text=text, bg=C["sidebar"], fg=C["text_muted"], font=FONT_SMALL)

    # Przełączanie tryb karta / lista

    def _show_cards(self, tasks):
        self._card_mode = True
        self.tree_frame.pack_forget()
        self.card_view.pack(fill="both", expand=True)
        self.card_view.load_tasks(tasks)
        self.count_var.set(f"{len(tasks)} zadań w trakcie")

    def _show_tree(self):
        self._card_mode = False
        self.card_view.pack_forget()
        self.tree_frame.pack(fill="both", expand=True)

    def _open_task_by_id(self, task_id):
        """Otwiera okno zadania po kliknięciu kafelka."""
        # Znajdź zadanie po ID w self.all_fetched_tasks
        for task in self.all_fetched_tasks:
            t_id = str(task.get("ID") or task.get("id", ""))
            if t_id == str(task_id):
                self._open_task_direct(task_id)
                return
        self._open_task_direct(task_id)

    def _open_task_direct(self, task_id):
        """Szuka zadania i otwiera je — analogicznie do open_task ale bez Treeview."""
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
            threading.Thread(
                target=self.bg_fetch_messages,
                args=(task_data, chat_id, chat_file_path, top_window),
                daemon=True
            ).start()

    # Widoki i filtry

    def on_status_change(self, event=None):
        if self.current_group_view_id is None:
            self.load_tasks_from_file_based_on_filter()
        self.apply_filter()

    def load_tasks_from_file_based_on_filter(self):
        selected_status = self.current_filter.get()
        file_name = "tasks_in_progress.json" if selected_status == "W trakcie" else "tasks_list.json"
        file_path = os.path.join(self.data_dir, file_name)
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self.all_fetched_tasks = json.load(f)
                self.update_resp_filter_options()
            except Exception as e:
                print(f"Nie udało się wczytać: {e}")
                self.all_fetched_tasks = []
        else:
            self.all_fetched_tasks = []

    def auto_fit_columns(self):
        font = tkfont.nametofont("TkDefaultFont")
        for col in self.tree["columns"]:
            max_w = font.measure(col) + 30
            for item in self.tree.get_children():
                val = self.tree.set(item, col)
                if val:
                    w = font.measure(str(val)) + 30
                    if w > max_w:
                        max_w = w
            if col in ["TITLE", "NAME", "DESCRIPTION", "GROUP"]:
                max_w = min(max_w, 500)
                self.tree.column(col, width=max_w, minwidth=max_w, stretch=True)
            else:
                max_w = min(max_w, 250)
                self.tree.column(col, width=max_w, minwidth=max_w, stretch=False)

    def switch_view(self):
        mode = self.current_view.get()
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.active_tree_timers.clear()

        if mode == "tasks":
            self.btn_fetch.config(text="⟳  Odśwież")

            # Wznów widoczność przycisku otwierania i filtru
            self.filter_frame.pack(side="left")
            self.tree.config(columns=self.task_columns)
            for col in self.task_columns:
                self.tree.heading(col, text=col, command=lambda c=col: self.sort_treeview(c, False))

            # --- PRZYWRÓĆ OPCJE KAFELEK/LISTY ---
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

            # --- UKRYJ OPCJE KAFELEK/LISTY W GRUPACH ---
            self.view_toggle_frame.pack_forget()
            self.btn_set_default.pack_forget()

            # W trybie grup zawszę chcemy włączyć "Otwórz / Filtruj zadania"
            self.btn_action.config(text="↗  Otwórz / Filtruj zadania")
            self.btn_action.pack(side="left", padx=2, after=self.btn_fetch)
            self.action_separator.pack(side="left", fill="y", padx=6, after=self.btn_action)

            self.filter_frame.pack_forget()
            if self._card_mode:
                self._show_tree()
            self.tree.config(columns=self.group_columns)
            for col in self.group_columns:
                self.tree.heading(col, text=col, command=lambda c=col: self.sort_treeview(c, False))
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
                    photo = u.get("PERSONAL_PHOTO")
                    print(photo)
                    all_users[uid] = {"name": name, "photo": photo}
                if "next" in data:
                    start = data["next"]
                else:
                    break
            self.users_map = all_users
            with open(os.path.join(self.data_dir, "users_list.json"), "w", encoding="utf-8") as f:
                json.dump(all_users, f, ensure_ascii=False, indent=4)
        except requests.exceptions.RequestException as e:
            print(f"Błąd pobierania użytkowników: {e}")

    def load_local_data(self):
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
                    self.users_map = json.load(f)
            except Exception:
                self.fetch_all_users()
        else:
            self.fetch_all_users()

        users_path = os.path.join(self.data_dir, "users_list.json")
        if os.path.exists(users_path):
            try:
                with open(users_path, "r", encoding="utf-8") as f:
                    loaded_users = json.load(f)
                    if loaded_users and isinstance(list(loaded_users.values())[0], str):
                        self.users_map = {k: {"name": v, "photo": None} for k, v in loaded_users.items()}
                    else:
                        self.users_map = loaded_users
            except Exception:
                self.fetch_all_users()

        self.switch_view()

    def get_user_avatar(self, uid, url, size=20):
        if not hasattr(self, '_photo_cache'):
            self._photo_cache = {}

        if not url:
            return None

        cache_key = f"{uid}_{size}"
        if cache_key in self._photo_cache:
            return self._photo_cache[cache_key]

        local_path = os.path.join(self.data_dir, "photos", f"{uid}.png")
        try:
            # Ładujemy z dysku lub pobieramy
            if os.path.exists(local_path):
                img = Image.open(local_path)
            else:
                resp = requests.get(url, timeout=3)
                img = Image.open(io.BytesIO(resp.content))
                img.save(local_path)

            # Skalujemy
            img = img.resize((size, size), Image.Resampling.LANCZOS)

            # Wycianamy idealne kółeczko
            mask = Image.new('L', (size, size), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, size, size), fill=255)

            output = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            output.paste(img, (0, 0), mask)

            photo = ImageTk.PhotoImage(output)
            self._photo_cache[cache_key] = photo
            return photo
        except Exception:
            return None

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
        self.tree.heading(col, command=lambda c=col: self.sort_treeview(c, not reverse))

    def _config_path(self):
        return os.path.join(self.data_dir, "ui_config.json")

    def _load_display_mode(self):
        """Wczytuje tryb widoku z pliku konfiguracyjnego. Domyślnie 'cards'."""
        try:
            p = os.path.join(get_data_dir(), "ui_config.json")
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                return cfg.get("display_mode", "cards")
        except Exception:
            pass
        return "cards"

    def _save_display_mode_as_default(self):
        """Zapisuje aktualny tryb widoku jako domyślny."""
        try:
            p = self._config_path()
            cfg = {}
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            cfg["display_mode"] = self.display_mode.get()
            with open(p, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            # Krótki feedback na przycisku
            self.btn_set_default.config(text="✓ Zapisano!", fg=C["btn_green"])
            self.root.after(2000, lambda: self.btn_set_default.config(
                text="★ Domyślny", fg=C["text_muted"]))
        except Exception as e:
            messagebox.showerror("Błąd", f"Nie udało się zapisać konfiguracji:\n{e}")

    def _schedule_auto_refresh(self):
        self.root.after(300000, self._auto_refresh_trigger)

    def _auto_refresh_trigger(self):
        if not self.is_fetching:
            mode = self.current_view.get()
            if mode == "tasks":
                if self.current_group_view_id:
                    self.is_fetching = True
                    self._toggle_buttons_state("disabled")
                    self.status_var.set("Automatyczne odświeżanie grupy...")
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
            self.status_var.set("Automatyczne odświeżanie..." if is_auto else "Pobieranie zadań...")
            threading.Thread(target=self._bg_fetch_all_tasks, args=(is_auto,), daemon=True).start()
        elif mode == "groups":
            self.status_var.set("Pobieranie grup...")
            threading.Thread(target=self._bg_fetch_all_groups, args=(is_auto,), daemon=True).start()

    def _toggle_buttons_state(self, state):
        self.btn_fetch.config(state=state)
        # Błędy mogłyby wywalać logi jeżeli guzik aktualnie był ukyty:
        try:
            self.btn_action.config(state=state)
        except:
            pass
        self.btn_view_cards.config(state=state)
        self.btn_view_list.config(state=state)
        self.btn_set_default.config(state=state)

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

    def _on_fetch_groups_success(self, all_groups, is_auto=False):
        self.all_fetched_groups = all_groups
        self.build_groups_map()
        self.display_groups(all_groups)
        if is_auto:
            self._reset_fetch_status(f"Odświeżono ({datetime.now().strftime('%H:%M')}).")
        else:
            self._reset_fetch_status("Pobrano grupy.")
            messagebox.showinfo("Sukces", "Pobrano i zapisano grupy robocze.")

    def _bg_fetch_all_tasks(self, is_auto=False):
        if self.current_filter.get() == "W trakcie":
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

    def _on_fetch_tasks_success(self, all_tasks, is_auto=False):
        self.all_fetched_tasks = all_tasks
        self.update_resp_filter_options()
        self.apply_filter()
        if is_auto:
            self._reset_fetch_status(f"Odświeżono ({datetime.now().strftime('%H:%M')}).")
        else:
            self._reset_fetch_status("Pobrano zadania.")
            messagebox.showinfo("Sukces", "Zakończono pobieranie.")

    def _on_fetch_error(self, e, category):
        self._reset_fetch_status("Błąd pobierania.", success=False)
        messagebox.showwarning("Tryb Offline",
                               f"Nie udało się pobrać {category}.\nPrzeglądasz dane lokalne.\nBłąd: {e}")

    def display_groups(self, groups):
        if self.current_view.get() != "groups":
            return
        if self._card_mode:
            self._show_tree()
        selected_ids = [self.tree.item(item, "values")[0] for item in self.tree.selection()]
        for row in self.tree.get_children():
            self.tree.delete(row)
        for group in groups:
            self.tree.insert("", "end", values=(
                group.get("ID"), group.get("NAME"), group.get("DESCRIPTION"),
                group.get("OWNER_ID"), format_date(group.get("DATE_CREATE")),
                format_date(group.get("DATE_ACTIVITY"))
            ))
        for item in self.tree.get_children():
            if self.tree.item(item, "values")[0] in selected_ids:
                self.tree.selection_add(item)
        self.sort_treeview("DATE_ACTIVITY", reverse=True)
        self.auto_fit_columns()
        self.count_var.set(f"{len(groups)} grup")
        self.view_label_var.set("Widok: Grupy robocze")

    def handle_main_action(self):
        if self.current_view.get() == "tasks":
            if self._card_mode:
                # W trybie kafelków nie ma selekcji — nic nie robimy
                messagebox.showinfo("Info", "Kliknij kafelek zadania, aby je otworzyć.")
            else:
                self.open_task()
        elif self.current_view.get() == "groups":
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
        self.status_var.set(f"Pobieranie zadań: {group_name}...")
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
                self.root.after(0, lambda n=len(group_tasks): self.status_var.set(f"Pobrano {n} zadań grupy..."))
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
            self._reset_fetch_status(f"Odświeżono ({datetime.now().strftime('%H:%M')}).")
        else:
            self._reset_fetch_status("Pobrano zadania grupy.")
            messagebox.showinfo("Sukces", f"Wyświetlono zadania: {group_name}")

    def _on_filter_tasks_error(self, e, group_name):
        self._reset_fetch_status("Błąd pobierania.", success=False)
        messagebox.showerror("Błąd", f"Nie udało się pobrać zadań {group_name}:\n{str(e)}")

    def _extract_participants(self, task):
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
        all_workers = set()
        for task in self.all_fetched_tasks:
            resp_name = f"{task.get('RESPONSIBLE_NAME', '')} {task.get('RESPONSIBLE_LAST_NAME', '')}".strip()
            if not resp_name and 'responsible' in task:
                r = task['responsible']
                resp_name = f"{r.get('name', '')} {r.get('lastName', '')}".strip()
            if resp_name:
                all_workers.add(resp_name)
            c_by = f"{task.get('CREATED_BY_NAME', '')} {task.get('CREATED_BY_LAST_NAME', '')}".strip()
            if not c_by and 'creator' in task:
                c_by = f"{task['creator'].get('name', '')} {task['creator'].get('lastName', '')}".strip()
            if c_by:
                all_workers.add(c_by)
            for p in self._extract_participants(task):
                all_workers.add(p)
        self.all_responsibles = ["Wszyscy"] + sorted(list(all_workers))
        self.resp_combobox.config(values=self.all_responsibles)
        self.current_resp_filter.set("Wszyscy")

    def on_resp_type(self, event):
        if event.keysym in ("Up", "Down", "Left", "Right", "Return", "Tab"):
            return
        typed = self.current_resp_filter.get().lower()
        if not typed:
            self.resp_combobox.config(values=self.all_responsibles)
        else:
            self.resp_combobox.config(values=[n for n in self.all_responsibles if typed in n.lower()])
        self.apply_filter()

    def apply_filter(self, event=None):
        if self.current_view.get() != "tasks":
            return
        selected_status = self.current_filter.get()
        typed_worker = self.current_resp_filter.get().strip().lower()
        search_term = self.search_var.get().strip().lower()
        hide_inactive = self.hide_inactive_var.get()
        threshold_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")

        filtered = []
        for task in self.all_fetched_tasks:
            real_status = str(task.get("REAL_STATUS") or task.get("status", ""))
            mapped = STATUS_MAP.get(real_status, real_status)
            resp_name = f"{task.get('RESPONSIBLE_NAME', '')}{task.get('RESPONSIBLE_LAST_NAME', '')}".strip()
            if not resp_name and 'responsible' in task:
                r = task['responsible']
                resp_name = f"{r.get('name', '')}{r.get('lastName', '')}".strip()
            c_by = f"{task.get('CREATED_BY_NAME', '')}{task.get('CREATED_BY_LAST_NAME', '')}".strip()
            if not c_by and 'creator' in task:
                c_by = f"{task['creator'].get('name', '')}{task['creator'].get('lastName', '')}".strip()
            participants_str = " ".join(self._extract_participants(task))
            worker_pool = f"{resp_name} {c_by} {participants_str}".lower()
            task_title = (task.get("TITLE") or task.get("title", "")).lower()
            activity_str = format_date(task.get("ACTIVITY_DATE") or task.get("activityDate") or "")

            match_status = selected_status == "Wszystkie" or mapped == selected_status
            match_title = not search_term or search_term in task_title
            match_worker = typed_worker in ("wszyscy", "") or typed_worker in worker_pool
            match_activity = True
            if hide_inactive and real_status == "3":
                if not activity_str or activity_str < threshold_date:
                    match_activity = False

            if match_status and match_worker and match_title and match_activity:
                filtered.append(task)

        # Wyświetl w trybie kafelków lub listy
        mode = self.display_mode.get()
        if mode == "cards":
            self.view_label_var.set(f"⊞ Kafelki — {selected_status}")
            self._show_cards(filtered)
        else:
            self.view_label_var.set(f"☰ Lista — {selected_status}")
            if self._card_mode:
                self._show_tree()
            self.display_data(filtered)

    def reset_filters(self):
        """Resetuje wszystkie filtry, w tym aktywny widok konkretnej grupy roboczej."""

        # 1. NAJWAŻNIEJSZE: Wyczyszczenie pamięci o wybranej grupie
        self.current_group_view_id = None
        self.current_group_view_name = None

        # 2. Reset standardowych opcji (comboboxy, szukajka)
        self.current_filter.set("W trakcie")
        self.current_resp_filter.set("Wszyscy")
        self.search_var.set("")
        self.live_timer_var.set(False)
        self.hide_inactive_var.set(False)

        # 3. Wymuszenie wczytania pełnej puli zadań z pliku (skoro nie jesteśmy już w grupie)
        self.load_tasks_from_file_based_on_filter()

        # 4. Odświeżenie widoku tabeli/kafelków
        self.apply_filter()

        # Opcjonalnie: mały komunikat, że wróciliśmy do ogółu
        self.status_var.set("Zresetowano filtry i widok grupy.")

    def display_data(self, tasks):
        selected_ids = [self.tree.item(item, "values")[0] for item in self.tree.selection()]
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.active_tree_timers.clear()

        for task in tasks:
            t_id = task.get("ID") or task.get("id")
            title = task.get("TITLE") or task.get("title")
            r_s = str(task.get("REAL_STATUS") or task.get("status", ""))
            status_txt = STATUS_MAP.get(r_s, r_s)
            raw_time = task.get("TIME_SPENT_IN_LOGS") or task.get("timeSpentInLogs")
            try:
                base_time = int(raw_time) if raw_time not in (None, "None", "null", "") else 0
            except:
                base_time = 0
            c_by = f"{task.get('CREATED_BY_NAME', '')}{task.get('CREATED_BY_LAST_NAME', '')}".strip()
            if not c_by and 'creator' in task:
                c_by = f"{task['creator'].get('name', '')}{task['creator'].get('lastName', '')}".strip()
            resp = f"{task.get('RESPONSIBLE_NAME', '')}{task.get('RESPONSIBLE_LAST_NAME', '')}".strip()
            if not resp and 'responsible' in task:
                resp = f"{task['responsible'].get('name', '')}{task['responsible'].get('lastName', '')}".strip()
            deadline = format_date(task.get("DEADLINE") or task.get("deadline"))
            created = format_date(task.get("CREATED_DATE") or task.get("createdDate"))
            changed = format_date(task.get("CHANGED_DATE") or task.get("changedDate"))
            status_changed = format_date(task.get("STATUS_CHANGED_DATE") or task.get("statusChangedDate"))
            g_id = str(task.get("GROUP_ID") or task.get("groupId") or "")
            group_name = self.groups_map.get(g_id, g_id) if g_id else ""
            raw_act = task.get("ACTIVITY_DATE") or task.get("activityDate")
            activity_date = format_date(raw_act)
            participants = ", ".join(self._extract_participants(task))
            time_str = seconds_to_readable(base_time)

            item_id = self.tree.insert("", "end", values=(
                t_id, title, status_txt, time_str,
                c_by, resp, participants, deadline, created,
                activity_date, changed, status_changed, group_name
            ))

            if self.live_timer_var.get() and r_s == "3":
                act_dt = parse_to_aware_datetime(raw_act)
                if act_dt:
                    today_date = datetime.now(timezone(timedelta(hours=1))).date()
                    if act_dt.date() == today_date:
                        self.active_tree_timers[item_id] = {"base_time": base_time, "activity_dt": act_dt}

        for item in self.tree.get_children():
            if self.tree.item(item, "values")[0] in selected_ids:
                self.tree.selection_add(item)

        self.sort_treeview("ACTIVITY_DATE", reverse=True)
        self.auto_fit_columns()
        self.count_var.set(f"{len(tasks)} zadań")

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
        if task_data.get("createdBy"):
            required_ids.add(str(task_data.get("createdBy")))
        if task_data.get("responsibleId"):
            required_ids.add(str(task_data.get("responsibleId")))
        for msg in messages:
            if msg.get("author_id"):
                required_ids.add(str(msg.get("author_id")))
        missing = [uid for uid in required_ids if uid not in self.users_map and uid != "0"]
        if missing:
            self.fetch_all_users()

    def open_task(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Uwaga", "Proszę wybrać zadanie z tabeli.")
            return
        item_values = self.tree.item(selected_item[0], "values")
        task_id = item_values[0]
        self._open_task_direct(task_id)

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
                    fetched = chat_data_json.get("result", {}).get("messages", [])
                    if not fetched:
                        break
                    messages.extend(fetched)
                    valid_ids = [msg.get("id") for msg in fetched if msg.get("id")]
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
            print(f"Błąd pobierania wiadomości: {e}")

    def create_task_window(self):
        top = tk.Toplevel(self.root)
        top.geometry("960x760")
        top.configure(bg=C["bg"])
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
        t_id = task_data.get("id", "")
        title = task_data.get("title", "")
        window.title(f"#{t_id} — {title}")

        # Header okna
        header = tk.Frame(window, bg=C["sidebar"], pady=10, padx=14)
        header.pack(fill="x")
        status_color = STATUS_COLORS.get("W trakcie", C["accent"])
        tk.Frame(header, bg=status_color, width=4).pack(side="left", fill="y", padx=(0, 12))
        tk.Label(header, text=f"#{t_id}", bg=C["sidebar"], fg=C["text_muted"], font=FONT_SMALL).pack(anchor="w")
        tk.Label(header, text=title, bg=C["sidebar"], fg=C["text"], font=FONT_HEADING, wraplength=800,
                 justify="left").pack(anchor="w")
        tk.Frame(window, bg=C["accent"], height=2).pack(fill="x")

        main_frame = tk.Frame(window, bg=C["bg"], padx=14, pady=12)
        main_frame.pack(fill="both", expand=True)

        # Opis
        tk.Label(main_frame, text="Opis zadania", bg=C["bg"], fg=C["accent2"], font=FONT_TITLE).pack(anchor="w")
        desc_bg = tk.Frame(main_frame, bg=C["card"], padx=10, pady=8,
                           highlightthickness=1, highlightbackground=C["card_border"])
        desc_bg.pack(fill="x", pady=(4, 12))
        desc_text = tk.Text(desc_bg, height=3, wrap="word", bg=C["card"], fg=C["text"],
                            font=FONT_BODY, bd=0, relief="flat", insertbackground=C["text"])
        desc_text.insert("1.0", task_data.get("description", "Brak opisu."))
        desc_text.config(state="disabled")
        desc_text.pack(fill="x")

        # Czas pracy
        time_lf = tk.LabelFrame(main_frame, text=" ⏱  Raport czasu pracy ",
                                bg=C["bg"], fg=C["accent"], font=FONT_TITLE,
                                padx=10, pady=8, bd=1, relief="groove")
        time_lf.pack(fill="x", pady=(0, 12))

        task_time_spent = int(task_data.get("TIME_SPENT_IN_LOGS") or task_data.get("timeSpentInLogs") or 0)
        tracker = {}
        today_date = datetime.now(timezone(timedelta(hours=1))).date()

        for msg in reversed(messages):
            text = msg.get("text", "")
            raw_date = msg.get("date")
            if not raw_date:
                continue
            try:
                dt_obj = datetime.fromisoformat(raw_date)
                dt = dt_obj.astimezone(timezone(timedelta(hours=1))) if dt_obj.tzinfo else dt_obj.replace(
                    tzinfo=timezone(timedelta(hours=1)))
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
        total_time_lbl = tk.Label(time_lf, textvariable=total_time_var, bg=C["bg"],
                                  fg=C["accent"], font=("Segoe UI Semibold", 12))
        total_time_lbl.pack(anchor="w", pady=(0, 8))

        if not tracker and task_time_spent == 0:
            total_time_var.set("Razem: 00:00:00")
            tk.Label(time_lf, text="Brak historii czasu.", bg=C["bg"], fg=C["text_muted"], font=FONT_BODY).pack(
                anchor="w")
        else:
            for user, data in tracker.items():
                lbl_var = tk.StringVar()
                lbl = tk.Label(time_lf, textvariable=lbl_var, bg=C["bg"], fg=C["text"], font=FONT_BODY)
                lbl.pack(anchor="w")
                is_active = bool(data["start_dt"] and data["start_dt"].date() == today_date)
                today_str = f"  (dziś: {seconds_to_readable(data['today'])})" if data['today'] > 0 else ""
                if is_active:
                    active_timers[user] = {
                        "total": data["total"], "today": data["today"],
                        "start_dt": data["start_dt"], "var": lbl_var
                    }
                else:
                    lbl_var.set(f"👤 {user}  {seconds_to_readable(data['total'])}{today_str}")
            if not active_timers:
                total_time_var.set(f"Razem: {seconds_to_readable(task_time_spent)}")

        if active_timers:
            self.update_live_timers(window, active_timers, total_time_var, task_time_spent, window.current_cycle)

        # Chat
        chat_hdr = f"💬 Wiadomości (Chat ID: {chat_id})" if chat_id else "💬 Wiadomości (brak czatu)"
        if not messages and chat_id:
            chat_hdr += " — synchronizowanie..."
        tk.Label(main_frame, text=chat_hdr, bg=C["bg"], fg=C["accent2"], font=FONT_TITLE).pack(anchor="w")

        chat_frame = tk.Frame(main_frame, bg=C["bg"])
        chat_frame.pack(fill="both", expand=True, pady=(4, 0))
        chat_scroll = ttk.Scrollbar(chat_frame, orient="vertical")
        chat_scroll.pack(side="right", fill="y")
        chat_text = tk.Text(chat_frame, wrap="word", yscrollcommand=chat_scroll.set,
                            bg=C["card"], fg=C["text"], font=FONT_BODY,
                            bd=0, relief="flat", insertbackground=C["text"],
                            selectbackground=C["accent2"])
        chat_text.pack(side="left", fill="both", expand=True)
        chat_scroll.config(command=chat_text.yview)

        if messages:
            for msg in reversed(messages):
                author_id = str(msg.get("author_id", ""))
                author_name = self.users_map.get(author_id,
                                                 f"ID {author_id}") if author_id and author_id != "0" else "System"
                text = msg.get("text", "")
                date = format_date(msg.get("date"))
                clean_text = re.sub(r"\[USER=\d+\](.*?)\[/USER\]", r"\1", text)
                chat_text.insert("end", f" [{date}]  {author_name}\n", "header")
                chat_text.insert("end", f"  {clean_text}\n\n", "body")
        else:
            chat_text.insert("end", "Brak wiadomości. Jeśli to pierwsze otwarcie, wiadomości pojawią się za chwilę.")

        chat_text.tag_config("header", foreground=C["accent"], font=("Segoe UI Semibold", 9),
                             background=C["sidebar"])
        chat_text.tag_config("body", foreground=C["text"])
        chat_text.config(state="disabled")

    def update_live_timers(self, window, active_timers, total_time_var, task_time_spent, cycle_id):
        if not window.winfo_exists() or getattr(window, "current_cycle", None) != cycle_id:
            return
        now = datetime.now(timezone(timedelta(hours=1)))
        live_total = 0
        for user, data in active_timers.items():
            elapsed = max(0, (now - data["start_dt"]).total_seconds())
            live_total += elapsed
            total_user = data["total"] + elapsed
            today_user = data["today"] + elapsed
            data["var"].set(
                f"👤 {user}  {seconds_to_readable(total_user)}  (dziś: {seconds_to_readable(today_user)})  🔴 aktywny")
        base_r = seconds_to_readable(task_time_spent)
        if live_total > 0:
            grand = task_time_spent + live_total
            total_time_var.set(
                f"Razem: {base_r}  +  {seconds_to_readable(live_total)}  =  {seconds_to_readable(grand)}")
        else:
            total_time_var.set(f"Razem: {base_r}")
        window.after(1000,
                     lambda: self.update_live_timers(window, active_timers, total_time_var, task_time_spent, cycle_id))


if __name__ == "__main__":
    root = tk.Tk()
    app = BitrixApp(root)
    root.mainloop()