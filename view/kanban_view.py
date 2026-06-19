"""
view/kanban_view.py — Widok Kanban: kolumny per status, live timer, klik = otwarcie zadania.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from datetime import datetime, timezone, timedelta
from typing import Callable

from styles import (
    C, FONT_TITLE, FONT_BODY, FONT_SMALL, FONT_MONO,
    STATUS_MAP, STATUS_COLORS,
)
from helpers import seconds_to_readable, format_date, parse_to_aware_datetime
from view.task_utils import (
    get_responsible, get_responsible_id, get_base_time, get_participants,
    tick_timers, register_timer,
    bind_hover_click, all_children,
    activity_color, days_since,
)

# Żądana kolejność kolumn; statusy spoza listy trafiają na koniec alfabetycznie
COLUMN_ORDER = [
    "Oczekuje",
    "W trakcie",
    "Zakończona",
    "Do kontroli",
    "Odłożona",
]

HIDDEN_STATUSES = {"Nowe", "Usunięta", "Wstrzymana"}

COLUMN_W   = 265
COLUMN_GAP = 8
CARD_PAD_X = 8
CARD_PAD_Y = 6


# ==============================================================================
# Pojedyncza kolumna
# ==============================================================================

class _KanbanColumn(tk.Frame):
    """Kolumna z nagłówkiem i przewijalną listą kart."""

    def __init__(self, master: tk.Widget, status: str, **kwargs) -> None:
        super().__init__(master, bg=C["sidebar"],
                         highlightthickness=1,
                         highlightbackground=C["card_border"],
                         **kwargs)
        self.status = status
        color = STATUS_COLORS.get(status, C["accent"])

        self.header = tk.Frame(self, bg=C["sidebar"], pady=8, cursor="fleur")
        self.header.pack(fill="x", padx=8)

        tk.Frame(self.header, bg=color, width=4, height=18).pack(side="left", fill="y", padx=(0, 8))
        tk.Label(self.header, text=status, bg=C["sidebar"], fg=C["text"],
                 font=("Segoe UI Semibold", 10), cursor="fleur").pack(side="left")

        self.count_var = tk.StringVar(value="0")
        tk.Label(self.header, textvariable=self.count_var,
                 bg=C["tag_bg"], fg=C["accent"],
                 font=("Segoe UI Bold", 8),
                 padx=6, pady=1, relief="flat").pack(side="right")

        tk.Frame(self, bg=color, height=2).pack(fill="x")

        scroll_area = tk.Frame(self, bg=C["sidebar"])
        scroll_area.pack(fill="both", expand=True)

        vsb = ttk.Scrollbar(scroll_area, orient="vertical")
        vsb.pack(side="right", fill="y")

        self._canvas = tk.Canvas(scroll_area, bg=C["sidebar"],
                                 highlightthickness=0, yscrollcommand=vsb.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        vsb.config(command=self._canvas.yview)

        self.cards_frame = tk.Frame(self._canvas, bg=C["sidebar"])
        self._cw = self._canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")

        self.cards_frame.bind("<Configure>",
                              lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfig(self._cw, width=e.width))
        self._canvas.bind("<MouseWheel>",
                          lambda e: self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

    def clear(self) -> None:
        for w in self.cards_frame.winfo_children():
            w.destroy()
        self.count_var.set("0")

    def set_count(self, n: int) -> None:
        self.count_var.set(str(n))

    def scroll_top(self) -> None:
        self._canvas.yview_moveto(0)

    def set_drop_highlight(self, side: str | None) -> None:
        accent = STATUS_COLORS.get(self.status, C["accent"])
        if side is None:
            self.config(highlightthickness=1, highlightbackground=C["card_border"])
        else:
            self.config(highlightthickness=3, highlightbackground=accent)


# ==============================================================================
# Główny widok Kanban
# ==============================================================================

class KanbanView(tk.Frame):
    """Poziomo przewijane kolumny z pionowo przewijanymi kartami."""

    def __init__(self, master: tk.Widget, app, on_open_cb: Callable, **kwargs) -> None:
        super().__init__(master, bg=C["bg"], **kwargs)
        self.app         = app
        self.on_open_cb  = on_open_cb
        self._tasks:      list = []
        self._timer_refs: dict = {}
        self._live        = True

        # ── Canvas poziomy ─────────────────────────────────────────────
        self._h_canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0)
        h_scroll = ttk.Scrollbar(self, orient="horizontal", command=self._h_canvas.xview)
        self._h_canvas.configure(xscrollcommand=h_scroll.set)

        h_scroll.pack(side="bottom", fill="x")
        self._h_canvas.pack(side="top", fill="both", expand=True)

        self._inner = tk.Frame(self._h_canvas, bg=C["bg"])
        self._inner.grid_rowconfigure(0, weight=1)
        self._cw = self._h_canvas.create_window((0, 0), window=self._inner, anchor="nw")

        self._inner.bind("<Configure>",
                         lambda _e: self._h_canvas.configure(scrollregion=self._h_canvas.bbox("all")))
        self._h_canvas.bind("<Configure>",
                            lambda e: self._h_canvas.itemconfig(self._cw, height=e.height))
        self._h_canvas.bind("<Shift-MouseWheel>",
                            lambda e: self._h_canvas.xview_scroll(int(-1 * (e.delta / 120)), "units"))

        # ── Kolumny ────────────────────────────────────────────────────
        self._columns:   dict[str, _KanbanColumn] = {}
        self._col_order: list[str] = []

        # Stan drag-and-drop
        self._drag_status: str | None = None
        self._drag_target: str | None = None
        self._drag_side:   str | None = None

        self._build_columns()

        # ── Pasek "załaduj więcej" ─────────────────────────────────────
        self._filtered_tasks: list = []
        self._loaded_count:   int  = 0
        self.PAGE_SIZE = 50

        self._load_more_bar = tk.Frame(self, bg=C["bg"], pady=6)
        self._load_more_bar.pack(side="bottom", fill="x")

        self._btn_load_more = tk.Button(
            self._load_more_bar, text="⬇ Załaduj następne 50",
            bg=C["sidebar"], fg=C["text"],
            font=FONT_BODY, relief="flat", cursor="hand2",
            padx=14, pady=5,
            activebackground=C["card_hover"], activeforeground=C["accent"],
            command=self._load_next_page,
        )
        self._btn_load_more.pack(side="right", padx=(4, 14))

        self._lbl_loaded = tk.Label(
            self._load_more_bar, text="",
            bg=C["bg"], fg=C["text_muted"], font=FONT_SMALL,
        )
        self._lbl_loaded.pack(side="right", padx=4)

        self._run_timers()

    # ── Kolumny ────────────────────────────────────────────────────────

    def _ordered_statuses(self) -> list[str]:
        all_vals = [v for v in dict.fromkeys(STATUS_MAP.values()) if v not in HIDDEN_STATUSES]
        ordered  = [s for s in COLUMN_ORDER if s in all_vals]
        rest     = sorted(s for s in all_vals if s not in ordered)
        return ordered + rest

    def _order_path(self) -> str:
        import os
        return os.path.join(self.app.data_dir, "kanban_col_order.json")

    def _load_col_order(self) -> list[str]:
        import json, os
        default = self._ordered_statuses()
        try:
            p = self._order_path()
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                known   = set(default)
                order   = [s for s in saved if s in known]
                missing = [s for s in default if s not in order]
                return order + missing
        except Exception:
            pass
        return default

    def _save_col_order(self) -> None:
        import json
        try:
            with open(self._order_path(), "w", encoding="utf-8") as f:
                json.dump(self._col_order, f, ensure_ascii=False)
        except Exception:
            pass

    def _build_columns(self) -> None:
        for w in self._inner.winfo_children():
            w.destroy()
        self._columns.clear()

        self._col_order = self._load_col_order()

        for idx, status in enumerate(self._col_order):
            col = _KanbanColumn(self._inner, status, width=COLUMN_W)
            col.grid(row=0, column=idx,
                     padx=(COLUMN_GAP, 0), pady=COLUMN_GAP, sticky="nsew")
            col.grid_propagate(False)
            self._inner.grid_columnconfigure(idx, minsize=COLUMN_W)
            self._columns[status] = col
            self._bind_drag(col)

        spacer = tk.Frame(self._inner, bg=C["bg"], width=COLUMN_GAP)
        spacer.grid(row=0, column=len(self._col_order))

    # ── Drag-and-drop ──────────────────────────────────────────────────

    def _bind_drag(self, col: _KanbanColumn) -> None:
        for w in [col.header] + all_children(col.header):
            w.bind("<ButtonPress-1>",   lambda e, s=col.status: self._drag_start(e, s))
            w.bind("<B1-Motion>",       self._drag_motion)
            w.bind("<ButtonRelease-1>", self._drag_end)

    def _drag_start(self, event, status: str) -> None:
        self._drag_status = status

    def _drag_motion(self, event) -> None:
        if not self._drag_status:
            return
        canvas = self._h_canvas
        cx     = (event.widget.winfo_rootx() + event.x
                  - canvas.winfo_rootx() + canvas.canvasx(0))

        target_status = None
        target_side   = "left"
        for status, col in self._columns.items():
            if status == self._drag_status:
                continue
            col_x = col.winfo_x()
            col_w = col.winfo_width()
            if col_x <= cx < col_x + col_w:
                target_status = status
                target_side   = "left" if cx < col_x + col_w / 2 else "right"
                break

        if self._drag_target and self._drag_target != target_status:
            old = self._columns.get(self._drag_target)
            if old:
                old.set_drop_highlight(None)

        self._drag_target = target_status
        self._drag_side   = target_side
        if target_status:
            self._columns[target_status].set_drop_highlight(target_side)

    def _drag_end(self, _event) -> None:
        src  = self._drag_status
        tgt  = self._drag_target
        side = self._drag_side

        if tgt and tgt in self._columns:
            self._columns[tgt].set_drop_highlight(None)

        self._drag_status = self._drag_target = self._drag_side = None

        if not src or not tgt or src == tgt:
            return

        order = list(self._col_order)
        order.pop(order.index(src))
        tgt_i    = order.index(tgt)
        insert_i = tgt_i if side == "left" else tgt_i + 1
        order.insert(insert_i, src)

        self._col_order = order
        self._save_col_order()

        for idx, status in enumerate(self._col_order):
            self._columns[status].grid(row=0, column=idx,
                                       padx=(COLUMN_GAP, 0), pady=COLUMN_GAP,
                                       sticky="nsew")
            self._inner.grid_columnconfigure(idx, minsize=COLUMN_W)

        for w in self._inner.winfo_children():
            info = w.grid_info()
            if info and int(info.get("column", -1)) >= len(self._col_order):
                w.grid(row=0, column=len(self._col_order))

    # ── Publiczne API ──────────────────────────────────────────────────

    def load_tasks(self, tasks: list) -> None:
        self._tasks     = tasks
        prev_loaded     = self._loaded_count
        #cutoff          = datetime.now(timezone(timedelta(hours=1))) - timedelta(days=14)

        def _act_key(t: dict) -> float:
            dt = parse_to_aware_datetime(t.get("ACTIVITY_DATE") or t.get("activityDate") or "")
            return dt.timestamp() if dt else 0.0

        # self._filtered_tasks = sorted(
        #     (t for t in tasks
        #      if (lambda dt: dt is not None and dt >= cutoff)(
        #          parse_to_aware_datetime(t.get("ACTIVITY_DATE") or t.get("activityDate") or "")
        #      )),
        #     key=_act_key, reverse=True,
        # )

        self._filtered_tasks = sorted(tasks, key=_act_key, reverse=True)

        target = max(self.PAGE_SIZE, prev_loaded)
        self._render_page(reset=True, target=target)

    def _load_next_page(self) -> None:
        self._render_page(reset=False)

    def _render_page(self, reset: bool, target: int | None = None) -> None:
        if reset:
            self._timer_refs.clear()
            for col in self._columns.values():
                col.clear()
                col.scroll_top()
            self._loaded_count = 0

        total   = len(self._filtered_tasks)
        chunk   = target if (reset and target is not None) else self.PAGE_SIZE
        new_end = min(self._loaded_count + chunk, total)
        page    = self._filtered_tasks[self._loaded_count:new_end]
        self._loaded_count = new_end

        for task in page:
            r_s    = str(task.get("REAL_STATUS") or task.get("status", ""))
            mapped = STATUS_MAP.get(r_s, r_s)
            col    = self._columns.get(mapped)
            if col:
                card = self._make_card(col.cards_frame, task)
                card.pack(fill="x", padx=6, pady=4)

        counts: dict[str, int] = {s: 0 for s in self._columns}
        for task in self._filtered_tasks[:self._loaded_count]:
            r_s    = str(task.get("REAL_STATUS") or task.get("status", ""))
            mapped = STATUS_MAP.get(r_s, r_s)
            if mapped in counts:
                counts[mapped] += 1
        for status, col in self._columns.items():
            col.set_count(counts[status])

        has_more = self._loaded_count < total
        self._lbl_loaded.config(text=f"Pokazano {self._loaded_count} z {total} zadań")
        self._btn_load_more.config(
            state="normal" if has_more else "disabled",
            fg=C["text"] if has_more else C["text_muted"],
        )

    # ── Budowanie karty ────────────────────────────────────────────────

    def _make_card(self, parent: tk.Frame, task: dict) -> tk.Frame:
        t_id  = str(task.get("ID") or task.get("id", ""))
        title = task.get("TITLE") or task.get("title", "Bez tytułu")

        resp              = get_responsible(task)
        resp_id           = get_responsible_id(task)
        base_time         = get_base_time(task)
        participants_info = get_participants(task)

        deadline     = format_date(task.get("DEADLINE") or task.get("deadline", ""))
        raw_activity = task.get("ACTIVITY_DATE") or task.get("activityDate", "")
        activity_str = format_date(raw_activity)
        days_ago     = days_since(activity_str)
        is_running   = str(task.get("REAL_STATUS") or task.get("status", "")) == "3"

        outer = tk.Frame(parent, bg=C["card_border"], cursor="hand2")
        card  = tk.Frame(outer, bg=C["card"], padx=CARD_PAD_X, pady=CARD_PAD_Y)
        card.pack(fill="both", expand=True, padx=1, pady=1)

        # Wiersz 1: ID + wskaźnik aktywności
        r1 = tk.Frame(card, bg=C["card"])
        r1.pack(fill="x")
        tk.Label(r1, text=f"#{t_id}", bg=C["card"], fg=C["text_muted"],
                 font=FONT_SMALL).pack(side="left")
        if is_running:
            tk.Label(r1, text="● aktywne", bg=C["card"],
                     fg=C["btn_green"], font=FONT_SMALL).pack(side="right")

        # Tytuł
        short = title if len(title) <= 52 else title[:49] + "…"
        tk.Label(card, text=short, bg=C["card"], fg=C["text"],
                 font=("Segoe UI Semibold", 9),
                 wraplength=COLUMN_W - 2 * CARD_PAD_X - 18,
                 justify="left", anchor="w").pack(fill="x", pady=(3, 4))

        tk.Frame(card, bg=C["card_border"], height=1).pack(fill="x", pady=(0, 4))

        # Odpowiedzialny
        if resp:
            rr = tk.Frame(card, bg=C["card"])
            rr.pack(fill="x", pady=1)
            resp_photo = None
            if resp_id and resp_id in self.app.users_map:
                ud = self.app.users_map[resp_id]
                if isinstance(ud, dict):
                    resp_photo = self.app.get_user_avatar(resp_id, ud.get("photo"), size=16)
            if resp_photo:
                tk.Label(rr, image=resp_photo, bg=C["card"]).pack(side="left")
            else:
                tk.Label(rr, text="👤", bg=C["card"], fg=C["text_muted"],
                         font=FONT_SMALL).pack(side="left")
            disp = resp if len(resp) <= 24 else resp[:21] + "…"
            tk.Label(rr, text=disp, bg=C["card"], fg=C["text_muted"],
                     font=FONT_SMALL).pack(side="left", padx=3)

        # Uczestnicy (skrótowo — tylko liczba)
        if participants_info:
            n = len(participants_info)
            pk = tk.Frame(card, bg=C["card"])
            pk.pack(fill="x", pady=1)
            suffix = "ów" if n != 1 else ""
            tk.Label(pk, text=f"👥 {n} uczestnik{suffix}",
                     bg=C["card"], fg=C["text_muted"],
                     font=FONT_SMALL).pack(side="left")

        # Stopka: timer + deadline / aktywność
        footer = tk.Frame(card, bg=C["card"])
        footer.pack(fill="x", pady=(5, 0))

        time_var = tk.StringVar(value=f"⏱ {seconds_to_readable(base_time)}")
        tk.Label(footer, textvariable=time_var, bg=C["card"],
                 fg=C["accent"], font=FONT_MONO).pack(side="left")

        if deadline:
            dl_color = (C["btn_red"]
                        if deadline < datetime.now().strftime("%Y-%m-%d %H:%M")
                        else C["text_muted"])
            tk.Label(footer, text=f"📅 {deadline[:10]}", bg=C["card"],
                     fg=dl_color, font=FONT_SMALL).pack(side="right")
        elif activity_str:
            ago_text = "dziś" if not days_ago else f"{days_ago}d temu"
            tk.Label(footer, text=f"🕐 {ago_text}", bg=C["card"],
                     fg=activity_color(days_ago), font=FONT_SMALL).pack(side="right")

        register_timer(self._timer_refs, task, time_var, resp, participants_info)
        bind_hover_click(outer, card, t_id, self.on_open_cb)
        return outer

    # ── Live timery ────────────────────────────────────────────────────

    def _run_timers(self) -> None:
        if not self._live:
            return
        tick_timers(self._timer_refs)
        self.after(1000, self._run_timers)