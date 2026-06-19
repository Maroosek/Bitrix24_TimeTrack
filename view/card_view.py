"""
view/card_view.py — Widok kafelkowy zadań (Trello-style) z live timerem.
"""
import tkinter as tk
from tkinter import ttk
from datetime import datetime

from styles import C, FONT_TITLE, FONT_BODY, FONT_SMALL, FONT_MONO
from helpers import seconds_to_readable, parse_to_aware_datetime
from view.task_utils import (
    get_responsible, get_responsible_id, get_creator, get_creator_id,
    get_base_time, get_participants, get_activity_dt,
    tick_timers, register_timer,
    bind_hover_click, render_participants_block, render_avatar_row,
    activity_color, format_date, days_since,
)


class TaskCardView(tk.Frame):
    """Siatka kafelków — stałe rozmiary, live timer, pełne szczegóły."""

    CARD_W   = 290
    CARD_H   = 240
    CARD_PAD = 12
    CARD_GAP = 10

    def __init__(self, master, app, on_open_cb, **kwargs):
        super().__init__(master, bg=C["bg"], **kwargs)
        self.app        = app
        self.on_open_cb = on_open_cb
        self._tasks:      list = []
        self._timer_refs: dict = {}

        self.page_size    = 50
        self.current_page = 1

        # ── Paginacja (dół) ────────────────────────────────────────────
        self.pagination_frame = tk.Frame(self, bg=C["bg"], pady=8)
        self.pagination_frame.pack(side="bottom", fill="x")

        self.btn_prev = tk.Button(
            self.pagination_frame, text="◀ Poprzednia", command=self._prev_page,
            bg=C["sidebar"], fg=C["text"], font=FONT_SMALL,
            relief="flat", cursor="hand2", padx=10, pady=4,
            activebackground=C["card_hover"], activeforeground=C["text"],
        )
        self.btn_prev.pack(side="left", padx=10)

        self.lbl_page = tk.Label(
            self.pagination_frame, text="Strona 1 z 1",
            bg=C["bg"], fg=C["text_muted"], font=FONT_BODY,
        )
        self.lbl_page.pack(side="left", expand=True)

        self.btn_next = tk.Button(
            self.pagination_frame, text="Następna ▶", command=self._next_page,
            bg=C["sidebar"], fg=C["text"], font=FONT_SMALL,
            relief="flat", cursor="hand2", padx=10, pady=4,
            activebackground=C["card_hover"], activeforeground=C["text"],
        )
        self.btn_next.pack(side="right", padx=10)

        # ── Canvas z przewijaniem ──────────────────────────────────────
        self._canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0)
        self._vsb    = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vsb.set)
        self._vsb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._inner = tk.Frame(self._canvas, bg=C["bg"])
        self._cw    = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")

        self._inner.bind("<Configure>",
                         lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        self._canvas.bind_all("<MouseWheel>", self._on_scroll)

        self._live = True
        self._run_timers()

    # ------------------------------------------------------------------
    # Publiczne API
    # ------------------------------------------------------------------

    def load_tasks(self, tasks: list) -> None:
        def _key(t):
            dt = parse_to_aware_datetime(t.get("ACTIVITY_DATE") or t.get("activityDate") or "")
            return dt.timestamp() if dt else 0

        self._tasks       = sorted(tasks, key=_key, reverse=True)
        self.current_page = 1
        self._timer_refs.clear()
        self._build_cards()

    def get_all_task_ids(self) -> list[str]:
        return [str(t.get("ID") or t.get("id", "")) for t in self._tasks]

    # ------------------------------------------------------------------
    # Zdarzenia
    # ------------------------------------------------------------------

    def _on_canvas_resize(self, event) -> None:
        self._canvas.itemconfig(self._cw, width=event.width)
        self._relayout()

    def _on_scroll(self, event) -> None:
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ------------------------------------------------------------------
    # Siatka kart
    # ------------------------------------------------------------------

    def _cols(self) -> int:
        w = self._canvas.winfo_width()
        if w < 10:
            w = 900
        return max(1, (w - self.CARD_GAP) // (self.CARD_W + self.CARD_GAP))

    def _build_cards(self) -> None:
        for w in self._inner.winfo_children():
            w.destroy()
        self._timer_refs.clear()

        start = (self.current_page - 1) * self.page_size
        page_tasks = self._tasks[start:start + self.page_size]

        self._update_pagination_ui()

        cols = self._cols()
        for idx, task in enumerate(page_tasks):
            card = self._make_card(self._inner, task)
            card.grid(row=idx // cols, column=idx % cols,
                      padx=self.CARD_GAP, pady=self.CARD_GAP, sticky="nw")

        self._canvas.yview_moveto(0)

    def _relayout(self) -> None:
        if self._tasks:
            self._build_cards()

    # ------------------------------------------------------------------
    # Paginacja
    # ------------------------------------------------------------------

    def _update_pagination_ui(self) -> None:
        total = max(1, (len(self._tasks) + self.page_size - 1) // self.page_size)
        self.lbl_page.config(text=f"Strona {self.current_page} z {total}")
        self.btn_prev.config(state="normal" if self.current_page > 1     else "disabled")
        self.btn_next.config(state="normal" if self.current_page < total else "disabled")

    def _prev_page(self) -> None:
        if self.current_page > 1:
            self.current_page -= 1
            self._build_cards()

    def _next_page(self) -> None:
        total = max(1, (len(self._tasks) + self.page_size - 1) // self.page_size)
        if self.current_page < total:
            self.current_page += 1
            self._build_cards()

    # ------------------------------------------------------------------
    # Budowanie karty
    # ------------------------------------------------------------------

    def _make_card(self, parent, task) -> tk.Frame:
        t_id  = str(task.get("ID") or task.get("id", ""))
        title = task.get("TITLE") or task.get("title", "Bez tytułu")

        resp             = get_responsible(task)
        resp_id          = get_responsible_id(task)
        creator_name     = get_creator(task)
        creator_id       = get_creator_id(task)
        base_time        = get_base_time(task)
        participants_info = get_participants(task)

        deadline     = format_date(task.get("DEADLINE") or task.get("deadline", ""))
        raw_activity = task.get("ACTIVITY_DATE") or task.get("activityDate", "")
        activity_str = format_date(raw_activity)
        days_ago     = days_since(activity_str)
        is_running   = str(task.get("REAL_STATUS") or task.get("status", "")) == "3"
        is_finished  = str(task.get("REAL_STATUS") or task.get("status", "")) == "5"

        # ── Ramka zewnętrzna ───────────────────────────────────────────
        outer = tk.Frame(parent, bg=C["card_border"], cursor="hand2",
                         width=self.CARD_W + 2, height=self.CARD_H + 2)
        outer.pack_propagate(False)

        card = tk.Frame(outer, bg=C["card"], width=self.CARD_W, height=self.CARD_H)
        card.pack_propagate(False)
        card.pack(fill="both", expand=True, padx=1, pady=1)

        inner = tk.Frame(card, bg=C["card"], padx=self.CARD_PAD, pady=8)
        inner.pack(fill="both", expand=True)

        # ── Wiersz 1: ID + twórca + status ────────────────────────────
        r1 = tk.Frame(inner, bg=C["card"])
        r1.pack(fill="x")

        tk.Label(r1, text=f"#{t_id}", bg=C["card"], fg=C["text_muted"],
                 font=FONT_SMALL).pack(side="left", padx=(0, 6))

        if creator_name:
            c_f = tk.Frame(r1, bg=C["card"])
            c_f.pack(side="left")
            creator_photo = None
            if creator_id and creator_id in self.app.users_map:
                ud = self.app.users_map[creator_id]
                if isinstance(ud, dict):
                    creator_photo = self.app.get_user_avatar(creator_id, ud.get("photo"))
            if creator_photo:
                tk.Label(c_f, image=creator_photo, bg=C["card"]).pack(side="left")
            else:
                tk.Label(c_f, text="👤", bg=C["card"], fg=C["text_muted"],
                         font=FONT_SMALL).pack(side="left")
            disp = creator_name if len(creator_name) <= 15 else creator_name[:12] + "..."
            tk.Label(c_f, text=disp, bg=C["card"], fg=C["text_muted"],
                     font=FONT_SMALL).pack(side="left", padx=(4, 0))

        if is_running:
            dot_text = "● W trakcie"
            dot_color = C["btn_green"]
        elif is_finished:
            dot_text = "✓ Zakończony"
            dot_color = C["text_muted"]
        else:
            dot_text = "○"
            dot_color = C["text_dark"]
        tk.Label(r1, text=dot_text, bg=C["card"], fg=dot_color,
                 font=FONT_SMALL).pack(side="right")

        # ── Tytuł ──────────────────────────────────────────────────────
        short_title = title if len(title) <= 55 else title[:52] + "..."
        tk.Label(inner, text=short_title, bg=C["card"], fg=C["text"],
                 font=FONT_TITLE,
                 wraplength=self.CARD_W - 2 * self.CARD_PAD - 4,
                 justify="left", anchor="w").pack(fill="x", pady=(4, 4))

        tk.Frame(inner, bg=C["card_border"], height=1).pack(fill="x", pady=(0, 5))

        # ── Odpowiedzialny ─────────────────────────────────────────────
        if resp:
            rr = tk.Frame(inner, bg=C["card"])
            rr.pack(fill="x", pady=1)
            resp_photo = None
            if resp_id and resp_id in self.app.users_map:
                ud = self.app.users_map[resp_id]
                if isinstance(ud, dict):
                    resp_photo = self.app.get_user_avatar(resp_id, ud.get("photo"))
            if resp_photo:
                tk.Label(rr, image=resp_photo, bg=C["card"]).pack(side="left", anchor="nw", pady=(1, 0))
            else:
                tk.Label(rr, text="👤", bg=C["card"], fg=C["text_muted"],
                         font=FONT_SMALL).pack(side="left", anchor="nw")
            disp = resp if len(resp) <= 28 else resp[:25] + "..."
            tk.Label(rr, text=disp, bg=C["card"], fg=C["text"],
                     font=FONT_SMALL).pack(side="left", padx=3, anchor="nw")

            # ── Uczestnicy (wspólny helper) ────────────────────────────
            render_participants_block(inner, participants_info,
                                      self.app.users_map, self.app.get_user_avatar)

        # ── Deadline ───────────────────────────────────────────────────
        if deadline:
            dr = tk.Frame(inner, bg=C["card"])
            dr.pack(fill="x", pady=1)
            dl_color = (C["btn_red"]
                        if deadline < datetime.now().strftime("%Y-%m-%d %H:%M")
                        else C["text_muted"])
            tk.Label(dr, text="📅", bg=C["card"], fg=C["text_muted"],
                     font=FONT_SMALL).pack(side="left")
            tk.Label(dr, text=deadline, bg=C["card"], fg=dl_color,
                     font=FONT_SMALL).pack(side="left", padx=3)

        # Wypychacz
        tk.Frame(inner, bg=C["card"]).pack(fill="both", expand=True)
        tk.Frame(inner, bg=C["card_border"], height=1).pack(fill="x", pady=(4, 4))

        # ── Stopka: timer + aktywność ──────────────────────────────────
        footer   = tk.Frame(inner, bg=C["card"])
        footer.pack(fill="x", side="bottom")

        time_var = tk.StringVar(value=f"⏱ {seconds_to_readable(base_time)}")
        tk.Label(footer, textvariable=time_var, bg=C["card"],
                 fg=C["accent"], font=FONT_MONO).pack(side="left")

        if activity_str:
            ago_text = "dziś" if not days_ago else f"{days_ago}d temu"
            tk.Label(footer, text=f"🕐 Aktywność - {ago_text}", bg=C["card"],
                     fg=activity_color(days_ago), font=FONT_SMALL).pack(side="right")

            # Rejestracja timera (wspólny helper)
            register_timer(self._timer_refs, task, time_var, resp, participants_info)

        # ── Hover + klik (wspólny helper) ─────────────────────────────
        bind_hover_click(outer, card, t_id, self.on_open_cb)
        return outer

    # ------------------------------------------------------------------
    # Live timery
    # ------------------------------------------------------------------

    def _run_timers(self) -> None:
        if not self._live:
            return
        tick_timers(self._timer_refs)
        self.after(1000, self._run_timers)