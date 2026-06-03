"""
view/summary_view.py — Widok "Podsumowanie": timeline pracy wybranej osoby.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime, timezone, timedelta
from tkinter import ttk
import tkinter as tk

from config import C, FONT_BODY, FONT_SMALL, FONT_TITLE, FONT_MONO
from helpers import parse_to_aware_datetime, seconds_to_readable, TZ_LOCAL
from view.task_utils import (
    get_responsible, get_creator, get_participants_names,
)


# ── Stałe ─────────────────────────────────────────────────────────────────────

HOUR_W  = 48
ROW_H   = 38
LABEL_W = 88
AXIS_H  = 26

BLOCK_PALETTE = [
    ("#3B82F6", "#1D4ED8"),
    ("#10B981", "#059669"),
    ("#F59E0B", "#D97706"),
    ("#8B5CF6", "#6D28D9"),
    ("#EC4899", "#BE185D"),
    ("#06B6D4", "#0E7490"),
    ("#F97316", "#C2410C"),
    ("#EF4444", "#B91C1C"),
]


# ── Parser sesji ──────────────────────────────────────────────────────────────

def _parse_sessions(
    messages: list, person_name: str
) -> list[tuple[datetime, datetime, bool]]:
    name_lc  = person_name.strip().lower()
    sessions: list[list] = []

    for msg in reversed(messages):
        text     = msg.get("text", "")
        raw_date = msg.get("date")
        if not raw_date:
            continue
        try:
            dt_obj = datetime.fromisoformat(raw_date)
            dt = (dt_obj.astimezone(TZ_LOCAL)
                  if dt_obj.tzinfo else
                  dt_obj.replace(tzinfo=TZ_LOCAL))
        except Exception:
            continue

        # Nowy format angielski + stary polski
        start_m = re.search(
            r"\[USER=\d+\](.*?)\[/USER\]\s+(?:włączył[a]?\s+śledzenie\s+czasu|enabled\s+personal\s+task\s+time\s+tracker)",
            text, re.IGNORECASE,
        )
        stop_m = re.search(
            r"\[USER=\d+\](.*?)\[/USER\]\s+(?:wyłączył[a]?\s+śledzenie\s+czasu|stopped\s+task\s+time\s+tracker)",
            text, re.IGNORECASE,
        )
        finish_m = re.search(
            r"(?:ukończył|zakończył)[a]?\s+zadanie|completed\s+the\s+task",
            text, re.IGNORECASE,
        )

        if start_m and start_m.group(1).strip().lower() == name_lc:
            sessions.append([dt, None])
        elif stop_m and stop_m.group(1).strip().lower() == name_lc:
            for sess in reversed(sessions):
                if sess[1] is None:
                    sess[1] = dt
                    break
        elif finish_m:
            for sess in reversed(sessions):
                if sess[1] is None:
                    sess[1] = dt
                    break

    now    = datetime.now(TZ_LOCAL)
    result = []
    for s, e in sessions:
        result.append((s, e or now, e is None))
    return result


# ==============================================================================
# Tooltip
# ==============================================================================

class _Tooltip:
    """Lekki tooltip wyświetlany przy kursorze nad canvasem."""

    def __init__(self, canvas: tk.Canvas):
        self._canvas  = canvas
        self._win:    tk.Toplevel | None = None
        self._after:  str | None = None

    def show(self, text: str, x_root: int, y_root: int) -> None:
        self._cancel()
        self._after = self._canvas.after(300, lambda: self._create(text, x_root, y_root))

    def hide(self) -> None:
        self._cancel()
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None

    def _cancel(self) -> None:
        if self._after:
            try:
                self._canvas.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def _create(self, text: str, x_root: int, y_root: int) -> None:
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass

        win = tk.Toplevel(self._canvas)
        win.wm_overrideredirect(True)
        win.wm_geometry(f"+{x_root + 14}+{y_root + 10}")
        win.attributes("-topmost", True)

        bg = C.get("card", "#1E293B")
        tk.Label(
            win, text=text,
            bg=bg, fg=C["text"],
            font=("Segoe UI", 9),
            padx=10, pady=6,
            relief="flat",
            wraplength=320,
            justify="left",
        ).pack()

        # Ramka
        win.configure(bg=C.get("card_border", "#334155"))

        self._win = win


# ==============================================================================
# Główny widok
# ==============================================================================

class SummaryView(tk.Frame):

    def __init__(self, master, app, **kwargs):
        super().__init__(master, bg=C["bg"], **kwargs)
        self.app = app

        self._selected_person: str  = ""
        self._days:            int  = 14
        self._loading:         bool = False
        self._cancel_flag:     bool = False
        self._task_data:       dict = {}

        # Mapa tag → dane bloku dla tooltipów
        # {"block_N": {"title": str, "start": dt, "end": dt, "duration_s": int, "is_open": bool}}
        self._block_info: dict = {}

        self._build_controls()
        self._build_canvas_area()

    # ── Pasek kontrolny ───────────────────────────────────────────────────────

    def _build_controls(self) -> None:
        ctrl = tk.Frame(self, bg=C["sidebar"], pady=6, padx=12)
        ctrl.pack(fill="x")

        left = tk.Frame(ctrl, bg=C["sidebar"])
        left.pack(side="left")

        tk.Label(left, text="👤 Pracownik:", bg=C["sidebar"],
                 fg=C["text_muted"], font=FONT_SMALL).pack(side="left", padx=(0, 4))

        self._person_var = tk.StringVar()
        self._person_cb  = ttk.Combobox(
            left, textvariable=self._person_var,
            state="readonly", width=24,
        )
        self._person_cb.pack(side="left", padx=(0, 14))

        tk.Label(left, text="📅 Dni wstecz:", bg=C["sidebar"],
                 fg=C["text_muted"], font=FONT_SMALL).pack(side="left", padx=(0, 4))

        self._days_var = tk.StringVar(value="14")
        ttk.Combobox(
            left, textvariable=self._days_var,
            values=["7", "14", "21", "30", "60", "90"],
            state="readonly", width=6,
        ).pack(side="left", padx=(0, 14))

        self._btn_run = tk.Button(
            left, text="▶ Generuj",
            bg=C["btn_blue"], fg="#fff",
            font=("Segoe UI Semibold", 9), relief="flat", cursor="hand2",
            padx=14, pady=4,
            activebackground=C["accent"], activeforeground="#000",
            command=self._start,
        )
        self._btn_run.pack(side="left", padx=(0, 8))

        self._status_var = tk.StringVar(value="")
        tk.Label(left, textvariable=self._status_var,
                 bg=C["sidebar"], fg=C["accent"], font=FONT_SMALL).pack(side="left", padx=8)

        right = tk.Frame(ctrl, bg=C["sidebar"])
        right.pack(side="right")
        for color, label in [("#3B82F6", "sesja"), ("#EF4444", "otwarta")]:
            tk.Frame(right, bg=color, width=10, height=10).pack(side="left", padx=(0, 3))
            tk.Label(right, text=label, bg=C["sidebar"],
                     fg=C["text_muted"], font=FONT_SMALL).pack(side="left", padx=(0, 10))

    # ── Obszar canvasów ───────────────────────────────────────────────────────

    def _build_canvas_area(self) -> None:
        wrap = tk.Frame(self, bg=C["bg"])
        wrap.pack(fill="both", expand=True)

        self._header = tk.Canvas(
            wrap, bg=C["bg"], highlightthickness=0,
            height=AXIS_H,
        )
        self._header.pack(fill="x", side="top")

        scroll_area = tk.Frame(wrap, bg=C["bg"])
        scroll_area.pack(fill="both", expand=True)

        self._vsb = ttk.Scrollbar(scroll_area, orient="vertical")
        self._hsb = ttk.Scrollbar(scroll_area, orient="horizontal")
        self._vsb.pack(side="right",  fill="y")
        self._hsb.pack(side="bottom", fill="x")

        self._canvas = tk.Canvas(
            scroll_area, bg=C["bg"], highlightthickness=0,
            yscrollcommand=self._vsb.set,
            xscrollcommand=self._on_hscroll,
        )
        self._canvas.pack(fill="both", expand=True)
        self._vsb.config(command=self._canvas.yview)
        self._hsb.config(command=self._canvas.xview)

        self._canvas.bind("<MouseWheel>",
            lambda e: self._canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        self._canvas.bind("<Shift-MouseWheel>",
            lambda e: self._canvas.xview_scroll(int(-1*(e.delta/120)), "units"))
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        # Tooltip
        self._tooltip = _Tooltip(self._canvas)

        # Kliknięcie poza blokami → schowaj tooltip
        self._canvas.bind("<Button-1>", lambda e: self._tooltip.hide())

    # ── Scroll synchronizacja ─────────────────────────────────────────────────

    def _on_hscroll(self, *args) -> None:
        self._hsb.set(*args)
        try:
            self._sync_header(float(args[0]))
        except Exception:
            pass

    def _sync_header(self, x_frac: float | None = None) -> None:
        if x_frac is None:
            vals   = self._canvas.xview()
            x_frac = vals[0] if vals else 0.0
        canvas_w = LABEL_W + 24 * HOUR_W + 40
        self._header.configure(scrollregion=(0, 0, canvas_w, AXIS_H))
        self._header.xview_moveto(x_frac)

    def _on_canvas_configure(self, _event=None) -> None:
        self._draw_header()
        self._sync_header()

    # ── Nagłówek ─────────────────────────────────────────────────────────────

    def _draw_header(self) -> None:
        canvas_w = LABEL_W + 24 * HOUR_W + 40
        self._header.configure(scrollregion=(0, 0, canvas_w, AXIS_H))
        self._header.delete("all")
        self._header.create_rectangle(0, 0, canvas_w, AXIS_H,
                                      fill=C["sidebar"], outline="")
        self._header.create_text(LABEL_W // 2, AXIS_H // 2, text="Data",
                                 fill=C["text_muted"], font=("Segoe UI", 7, "bold"))
        for h in range(24):
            x = LABEL_W + h * HOUR_W
            self._header.create_text(x + HOUR_W // 2, AXIS_H // 2,
                                     text=f"{h:02}:00",
                                     fill=C["text_muted"], font=("Segoe UI", 7))
        self._header.create_line(0, AXIS_H - 1, canvas_w, AXIS_H - 1,
                                 fill=C.get("card_border", "#334155"))

    # ── Publiczne API ─────────────────────────────────────────────────────────

    def refresh_persons(self) -> None:
        names = sorted(n for n in self.app.all_responsibles if n != "Wszyscy")
        self._person_cb.config(values=names)
        cur = self._person_var.get()
        if cur not in names and names:
            self._person_var.set(names[0])

    # ── Start ─────────────────────────────────────────────────────────────────

    def _start(self) -> None:
        if self._loading:
            return
        person = self._person_var.get().strip()
        if not person:
            self._status_var.set("⚠ Wybierz pracownika.")
            return
        try:
            days = int(self._days_var.get())
        except ValueError:
            days = 14

        self._selected_person = person
        self._days            = days
        self._loading         = True
        self._cancel_flag     = False
        self._task_data.clear()
        self._block_info.clear()
        self._canvas.delete("all")
        self._btn_run.config(state="disabled")
        self._status_var.set("⏳ Zbieram zadania…")
        threading.Thread(target=self._bg_collect, daemon=True).start()

    # ── Wątek tła ─────────────────────────────────────────────────────────────

    def _finalize_loading(self) -> None:
        self._loading = False
        self._btn_run.config(state="normal")
        total_sess = sum(len(v["sessions"]) for v in self._task_data.values())
        self._status_var.set(
            f"✓ {len(self._task_data)} zadań  |  "
            f"łączny czas: {seconds_to_readable(sum((e - s).total_seconds() for info in self._task_data.values() for s, e, _ in info['sessions']))}"
        )

    def _bg_collect(self) -> None:
        person_lc = self._selected_person.lower()
        cutoff_dt = datetime.now(TZ_LOCAL) - timedelta(days=self._days)

        # ── Krok 1: Lokalne zadania — synchronicznie, bez sieci ───────────
        local_map: dict[str, dict] = {}
        for task in self.app.all_fetched_tasks:
            raw_act = task.get("ACTIVITY_DATE") or task.get("activityDate") or ""
            act_dt = parse_to_aware_datetime(raw_act)
            if act_dt and act_dt < cutoff_dt:
                continue
            pool = " ".join(filter(None, [
                get_responsible(task),
                get_creator(task),
                *get_participants_names(task),
            ])).lower()
            if person_lc in pool:
                t_id = str(task.get("ID") or task.get("id", ""))
                if t_id:
                    local_map[t_id] = task

        # Wczytaj lokalne chaty synchronicznie (bez sieci)
        local_results: dict = {}
        for t_id, task in local_map.items():
            title = task.get("TITLE") or task.get("title", f"Zadanie #{t_id}")
            msgs = []
            detail = self.app.storage.load_task_detail(t_id)
            chat_id = None
            if detail:
                chat_id = detail.get("chatId") or detail.get("CHAT_ID")
            if chat_id:
                msgs = self.app.storage.load_chat_messages(chat_id)
            local_results[t_id] = {"title": title, "messages": msgs}

        # Pokaż lokalny wynik natychmiast
        if local_results:
            self.app.root.after(
                0, lambda r=local_results: self._on_data_ready(r, partial=True)
            )

        # ── Krok 2: API w tle — znajdź wszystkie zadania osoby ────────────
        person_id = None
        for uid, ud in self.app.users_map.items():
            name = (ud.get("name") if isinstance(ud, dict) else ud or "").strip().lower()
            if name == person_lc:
                person_id = uid
                break

        api_map: dict[str, dict] = {}
        api_lock = threading.Lock()

        def _fetch_by_filter(params: dict) -> None:
            try:
                import requests
                from config import WEBHOOK_URL
                start = 0
                while True:
                    p = {**params, "start": start}
                    resp = requests.get(f"{WEBHOOK_URL}tasks.task.list", params=p, timeout=15)
                    resp.raise_for_status()
                    data = resp.json()
                    tasks = data.get("result", {}).get("tasks", [])
                    if not tasks:
                        break
                    with api_lock:
                        for t in tasks:
                            t_id = str(t.get("id") or t.get("ID", ""))
                            if t_id:
                                api_map[t_id] = t
                    if "next" in data:
                        start = data["next"]
                    else:
                        break
            except Exception:
                pass

        if person_id:
            date_str = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
            filters = [
                {"filter[RESPONSIBLE_ID]": person_id, "filter[>=ACTIVITY_DATE]": date_str},
                {"filter[CREATED_BY]": person_id, "filter[>=ACTIVITY_DATE]": date_str},
                {"filter[ACCOMPLICE]": person_id, "filter[>=ACTIVITY_DATE]": date_str},
            ]
            threads = [threading.Thread(target=_fetch_by_filter, args=(f,), daemon=True)
                       for f in filters]
            for t in threads: t.start()
            for t in threads: t.join(timeout=60)

        if self._cancel_flag:
            return

        # Scal — API uzupełnia lokalny cache
        merged = {**local_map, **api_map}

        # Pobierz chaty tylko dla zadań których nie ma w lokalnych wynikach
        new_ids = {t_id for t_id in merged if t_id not in local_results}

        if not new_ids and not local_results:
            self.app.root.after(0, self._on_no_tasks)
            return

        if not new_ids:
            # Nic nowego z API — odblokuj przycisk
            self.app.root.after(0, self._finalize_loading)
            return

        self.app.root.after(
            0, lambda n=len(new_ids): self._status_var.set(
                f"🔄 API: {len(merged)} zadań łącznie — pobieram {n} nowych chatów…"
            )
        )

        # Pobierz nowe chaty z API
        sem = threading.Semaphore(6)
        results = {}
        lock = threading.Lock()
        total = len(new_ids)
        counter = [0]
        done_ev = threading.Event()

        def _fetch_one(t_id: str) -> None:
            if self._cancel_flag:
                with lock:
                    counter[0] += 1
                    if counter[0] >= total:
                        done_ev.set()
                return

            task = merged[t_id]
            title = task.get("TITLE") or task.get("title", f"Zadanie #{t_id}")
            msgs = []

            with sem:
                detail = self.app.storage.load_task_detail(t_id)
                chat_id = None
                if detail:
                    chat_id = detail.get("chatId") or detail.get("CHAT_ID")
                if not chat_id:
                    try:
                        detail = self.app.api.fetch_task_detail(t_id)
                        chat_id = detail.get("chatId") or detail.get("CHAT_ID")
                    except Exception:
                        pass
                if chat_id:
                    try:
                        chat_file = self.app.storage.chat_file_path(chat_id)
                        msgs = self.app.api.fetch_chat_messages(chat_id, chat_file)
                    except Exception:
                        msgs = self.app.storage.load_chat_messages(chat_id)

            with lock:
                results[t_id] = {"title": title, "messages": msgs}
                counter[0] += 1
                n = counter[0]
                if n >= total:
                    done_ev.set()

            self.app.root.after(
                0, lambda _n=n: self._status_var.set(f"🔄 Pobrano czaty: {_n}/{total}…")
            )

        for t_id in new_ids:
            threading.Thread(target=_fetch_one, args=(t_id,), daemon=True).start()

        done_ev.wait(timeout=180)

        if not self._cancel_flag:
            self.app.root.after(0, lambda: self._on_data_ready(results, partial=False))

    # ── Callbacki UI ─────────────────────────────────────────────────────────

    def _on_no_tasks(self) -> None:
        self._loading = False
        self._btn_run.config(state="normal")
        self._status_var.set("⚠ Brak zadań dla tej osoby w podanym zakresie.")

    def _on_data_ready(self, results: dict, partial: bool = False) -> None:
        for t_id, info in results.items():
            sessions = _parse_sessions(info["messages"], self._selected_person)
            if sessions:
                self._task_data[t_id] = {"title": info["title"], "sessions": sessions}

        if not partial:
            self._loading = False
            self._btn_run.config(state="normal")

        if not self._task_data:
            if not partial:
                self._status_var.set("⚠ Brak sesji czasu dla tej osoby.")
            return

        total_sess = sum(len(v["sessions"]) for v in self._task_data.values())
        prefix = "⏳" if partial else "✓"
        self._status_var.set(f"{prefix} {len(self._task_data)} zadań, {total_sess} sesji — rysuję…")
        self.app.root.after(30, self._draw)

    # ── Rysowanie ─────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        self._canvas.delete("all")
        self._block_info.clear()
        self._draw_header()

        now       = datetime.now(TZ_LOCAL)
        day_start = (now - timedelta(days=self._days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        days_list: list[datetime] = []
        d = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        while d >= day_start:
            days_list.append(d)
            d -= timedelta(days=1)

        task_ids   = list(self._task_data.keys())
        task_color = {
            tid: BLOCK_PALETTE[i % len(BLOCK_PALETTE)]
            for i, tid in enumerate(task_ids)
        }

        canvas_w  = LABEL_W + 24 * HOUR_W + 40
        canvas_h  = len(days_list) * ROW_H + 60
        self._canvas.configure(scrollregion=(0, 0, canvas_w, canvas_h))

        for h in range(25):
            x = LABEL_W + h * HOUR_W
            self._canvas.create_line(x, 0, x, len(days_list) * ROW_H,
                                     fill=C.get("card_border", "#334155"), dash=(1, 4))

        total_secs = 0.0
        block_idx  = 0   # unikalny licznik tagów

        for row_i, day_dt in enumerate(days_list):
            y_top = row_i * ROW_H
            y_bot = y_top + ROW_H

            row_bg = C["card"] if row_i % 2 == 0 else C.get("card_hover", C["sidebar"])
            self._canvas.create_rectangle(0, y_top, canvas_w, y_bot,
                                          fill=row_bg, outline="")

            is_yesterday = (now.date() - day_dt.date()).days == 1
            week_days    = ["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Nd"]
            if is_yesterday:
                lbl_text = f"Wczoraj\n{day_dt.strftime('%d.%m')}"
                lbl_fg   = C["text"]
                lbl_font = ("Segoe UI", 7)
            else:
                wd = week_days[day_dt.weekday()]
                lbl_text = f"{wd}\n{day_dt.strftime('%d.%m')}"
                lbl_fg   = C["text_muted"]
                lbl_font = ("Segoe UI", 7)

            self._canvas.create_text(LABEL_W // 2, y_top + ROW_H // 2,
                                     text=lbl_text, fill=lbl_fg, font=lbl_font,
                                     justify="center")
            self._canvas.create_line(0, y_bot, canvas_w, y_bot,
                                     fill=C.get("card_border", "#334155"))

            day_end_dt = day_dt + timedelta(days=1)

            day_sessions: list[tuple] = []
            for t_id, info in self._task_data.items():
                for s_dt, e_dt, is_open in info["sessions"]:
                    seg_s = max(s_dt, day_dt)
                    seg_e = min(e_dt, day_end_dt)
                    if seg_s >= seg_e:
                        continue
                    total_secs += (seg_e - seg_s).total_seconds()
                    day_sessions.append((seg_s, seg_e, is_open, t_id, info["title"]))

            day_sessions.sort(key=lambda x: x[0])

            LANES    = 3
            lane_h   = (ROW_H - 4) // LANES
            lane_end = [LABEL_W - 1.0] * LANES

            for seg_s, seg_e, is_open, t_id, title in day_sessions:
                s_frac = (seg_s - day_dt).total_seconds() / 86400
                e_frac = (seg_e - day_dt).total_seconds() / 86400
                x0 = LABEL_W + s_frac * 24 * HOUR_W
                x1 = LABEL_W + e_frac * 24 * HOUR_W
                if x1 - x0 < 3:
                    x1 = x0 + 3

                lane = 0
                for li in range(LANES):
                    if lane_end[li] <= x0 + 1:
                        lane = li
                        break
                lane_end[lane] = x1

                y0_b = y_top + 2 + lane * lane_h
                y1_b = y0_b + lane_h - 1

                fill, outline = task_color[t_id]
                if is_open:
                    fill, outline = "#EF4444", "#B91C1C"

                # ── Unikalny tag bloku ─────────────────────────────────
                tag = f"block_{block_idx}"
                block_idx += 1

                rect_id = self._canvas.create_rectangle(
                    x0, y0_b, x1, y1_b,
                    fill=fill, outline=outline, width=1,
                    tags=(tag,),
                )

                # Zapisz dane bloku
                dur_s = int((seg_e - seg_s).total_seconds())
                self._block_info[tag] = {
                    "title":      title,
                    "start":      seg_s,
                    "end":        seg_e,
                    "duration_s": dur_s,
                    "is_open":    is_open,
                    "fill_orig":  fill,
                    "outline_orig": outline,
                }

                # Etykieta bloku
                block_w = x1 - x0
                if block_w > 20:
                    dur_lbl = seconds_to_readable(dur_s)
                    if block_w > 90:
                        short = title if len(title) <= 18 else title[:16] + "…"
                        label = f"{short}  {dur_lbl}"
                    elif block_w > 40:
                        label = dur_lbl
                    else:
                        label = ""
                    if label:
                        self._canvas.create_text(
                            x0 + 4, (y0_b + y1_b) // 2,
                            text=label, fill="#fff", anchor="w",
                            font=("Segoe UI", 6, "bold"),
                            tags=(tag,),
                        )

                # ── Bindy hover/klik ───────────────────────────────────
                self._bind_block(tag)

        # Legenda
        legend_y = len(days_list) * ROW_H + 10
        lx       = LABEL_W

        for t_id, info in self._task_data.items():
            fill, _ = task_color[t_id]
            self._canvas.create_rectangle(lx, legend_y, lx + 10, legend_y + 10,
                                          fill=fill, outline="")
            short  = info["title"] if len(info["title"]) <= 28 else info["title"][:26] + "…"
            text_w = len(short) * 5 + 16
            self._canvas.create_text(lx + 13, legend_y + 5, text=short,
                                     fill=C["text_muted"], anchor="w",
                                     font=("Segoe UI", 7))
            lx += 13 + text_w
            if lx > canvas_w - 120:
                lx        = LABEL_W
                legend_y += 14

        final_h = legend_y + 20
        self._canvas.configure(scrollregion=(0, 0, canvas_w, final_h))

        self._status_var.set(
            f"✓ {len(self._task_data)} zadań  |  "
            f"łączny czas: {seconds_to_readable(int(total_secs))}"
        )
        self._sync_header()

    # ── Hover / klik na bloku ─────────────────────────────────────────────────

    def _bind_block(self, tag: str) -> None:
        """Binduje tooltip (hover) i rozszerzony popup (klik) do bloku."""

        # Znajdź ID samego prostokąta (pierwszy element tagu o typie "rectangle")
        def _rect_id() -> int | None:
            for item in self._canvas.find_withtag(tag):
                if self._canvas.type(item) == "rectangle":
                    return item
            return None

        def _enter(event, t=tag) -> None:
            info = self._block_info.get(t)
            if not info:
                return
            rid = _rect_id()
            if rid:
                self._canvas.itemconfig(rid, outline="#FFFFFF", width=2)
            short_text = (
                f"{info['title']}\n"
                f"{info['start'].strftime('%H:%M')} – {info['end'].strftime('%H:%M')}  "
                f"({seconds_to_readable(info['duration_s'])})"
            )
            if info["is_open"]:
                short_text += "\n⚠ sesja otwarta"
            self._tooltip.show(short_text, event.x_root, event.y_root)

        def _leave(event, t=tag) -> None:
            info = self._block_info.get(t)
            rid = _rect_id()
            if info and rid:
                self._canvas.itemconfig(rid, outline=info["outline_orig"], width=1)
            self._tooltip.hide()

        def _click(event, t=tag) -> None:
            self._tooltip.hide()
            info = self._block_info.get(t)
            if not info:
                return
            self._show_block_popup(info, event.x_root, event.y_root)

        self._canvas.tag_bind(tag, "<Enter>", _enter)
        self._canvas.tag_bind(tag, "<Leave>", _leave)
        self._canvas.tag_bind(tag, "<Button-1>", _click)

    def _show_block_popup(self, info: dict, x_root: int, y_root: int) -> None:
        """Wyświetla okienko z pełnymi szczegółami bloku sesji."""
        popup = tk.Toplevel(self._canvas)
        popup.wm_overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg=C.get("card_border", "#334155"))

        inner = tk.Frame(popup, bg=C["card"], padx=14, pady=10)
        inner.pack(padx=1, pady=1)

        # Tytuł
        tk.Label(inner, text=info["title"],
                 bg=C["card"], fg=C["accent"],
                 font=("Segoe UI Semibold", 10),
                 wraplength=300, justify="left").pack(anchor="w")

        tk.Frame(inner, bg=C.get("card_border", "#334155"), height=1).pack(fill="x", pady=6)

        # Szczegóły
        rows = [
            ("🕐 Start:",    info["start"].strftime("%d.%m.%Y  %H:%M")),
            ("🕑 Koniec:",   info["end"].strftime("%d.%m.%Y  %H:%M")
                             + ("  ⚠ otwarta" if info["is_open"] else "")),
            ("⏱ Czas:",     seconds_to_readable(info["duration_s"])),
        ]
        for lbl, val in rows:
            row = tk.Frame(inner, bg=C["card"])
            row.pack(fill="x", pady=1)
            tk.Label(row, text=lbl, bg=C["card"], fg=C["text_muted"],
                     font=("Segoe UI", 8), width=10, anchor="w").pack(side="left")
            tk.Label(row, text=val, bg=C["card"], fg=C["text"],
                     font=("Segoe UI", 8)).pack(side="left")

        tk.Frame(inner, bg=C.get("card_border", "#334155"), height=1).pack(fill="x", pady=6)

        tk.Button(inner, text="✕ Zamknij",
                  bg=C["sidebar"], fg=C["text_muted"],
                  font=("Segoe UI", 8), relief="flat", cursor="hand2",
                  padx=8, pady=2,
                  command=popup.destroy).pack(anchor="e")

        # Pozycja — żeby nie wychodziło poza ekran
        popup.update_idletasks()
        pw = popup.winfo_reqwidth()
        ph = popup.winfo_reqheight()
        sw = popup.winfo_screenwidth()
        sh = popup.winfo_screenheight()
        px = min(x_root + 10, sw - pw - 10)
        py = min(y_root + 10, sh - ph - 10)
        popup.wm_geometry(f"+{px}+{py}")

        # Zamknij kliknięciem gdziekolwiek poza popupem
        popup.bind("<FocusOut>", lambda e: popup.destroy())
        popup.focus_set()