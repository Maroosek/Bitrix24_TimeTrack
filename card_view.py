"""
card_view.py — Widok kafelkowy zadań (Trello-style) z live timerem.
"""
import tkinter as tk
from tkinter import ttk
from datetime import datetime, timezone, timedelta

from config import C, FONT_TITLE, FONT_BODY, FONT_SMALL, FONT_MONO
from helpers import (
    seconds_to_readable,
    format_date,
    parse_to_aware_datetime,
    days_since,
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
        self._tasks     = []
        self._timer_refs: dict = {}  # task_id -> {var, base, start}

        self._canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0)
        self._vsb    = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vsb.set)
        self._vsb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._inner = tk.Frame(self._canvas, bg=C["bg"])
        self._cw    = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")

        self._inner.bind("<Configure>", lambda e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        self._canvas.bind_all("<MouseWheel>", self._on_scroll)

        self._live = True
        self._run_timers()

    # ------------------------------------------------------------------
    # Publiczne API
    # ------------------------------------------------------------------

    def load_tasks(self, tasks: list) -> None:
        """Ładuje i sortuje listę zadań, a następnie buduje kafelki."""
        def _key(t):
            raw = t.get("ACTIVITY_DATE") or t.get("activityDate") or ""
            dt  = parse_to_aware_datetime(raw)
            return dt.timestamp() if dt else 0

        self._tasks = sorted(tasks, key=_key, reverse=True)
        self._timer_refs.clear()
        self._build_cards()

    def get_all_task_ids(self) -> list[str]:
        return [str(t.get("ID") or t.get("id", "")) for t in self._tasks]

    # ------------------------------------------------------------------
    # Zdarzenia canvasu
    # ------------------------------------------------------------------

    def _on_canvas_resize(self, event) -> None:
        self._canvas.itemconfig(self._cw, width=event.width)
        self._relayout()

    def _on_scroll(self, event) -> None:
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ------------------------------------------------------------------
    # Budowanie siatki kart
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

        cols = self._cols()
        for idx, task in enumerate(self._tasks):
            col  = idx % cols
            row  = idx // cols
            card = self._make_card(self._inner, task)
            card.grid(row=row, column=col,
                      padx=self.CARD_GAP, pady=self.CARD_GAP, sticky="nw")

    def _relayout(self) -> None:
        if self._tasks:
            self._build_cards()

    # ------------------------------------------------------------------
    # Budowanie pojedynczej karty
    # ------------------------------------------------------------------

    def _make_card(self, parent, task) -> tk.Frame:
        t_id  = str(task.get("ID") or task.get("id", ""))
        title = task.get("TITLE") or task.get("title", "Bez tytułu")

        # Odpowiedzialny
        resp = f"{task.get('RESPONSIBLE_NAME', '')} {task.get('RESPONSIBLE_LAST_NAME', '')}".strip()
        if not resp and "responsible" in task:
            r    = task["responsible"]
            resp = f"{r.get('name', '')} {r.get('lastName', '')}".strip()

        # Uczestnicy
        participants_info: list[tuple[str, str]] = []
        acc = task.get("accomplicesData")
        if isinstance(acc, dict):
            for uid, ud in acc.items():
                if isinstance(ud, dict) and ud.get("name"):
                    participants_info.append((str(uid), ud["name"]))
        elif isinstance(acc, list):
            for ud in acc:
                if isinstance(ud, dict) and ud.get("name"):
                    participants_info.append((str(ud.get("id", "")), ud["name"]))

        # Czas podstawowy
        raw_time = task.get("TIME_SPENT_IN_LOGS") or task.get("timeSpentInLogs")
        try:
            base_time = int(raw_time) if raw_time not in (None, "None", "null", "") else 0
        except (TypeError, ValueError):
            base_time = 0

        deadline     = format_date(task.get("DEADLINE") or task.get("deadline", ""))
        raw_activity = task.get("ACTIVITY_DATE") or task.get("activityDate", "")
        activity_str = format_date(raw_activity)
        days_ago     = days_since(activity_str)
        real_status  = str(task.get("REAL_STATUS") or task.get("status", ""))
        is_running   = (real_status == "3")

        # ── Ramka zewnętrzna (obramowanie) ────────────────────────────
        outer = tk.Frame(parent, bg=C["card_border"], cursor="hand2",
                         width=self.CARD_W + 2, height=self.CARD_H + 2)
        outer.pack_propagate(False)

        card = tk.Frame(outer, bg=C["card"], width=self.CARD_W, height=self.CARD_H)
        card.pack_propagate(False)
        card.pack(fill="both", expand=True, padx=1, pady=1)

        inner = tk.Frame(card, bg=C["card"], padx=self.CARD_PAD, pady=8)
        inner.pack(fill="both", expand=True)

        # ── Wiersz 1: ID + twórca + status ───────────────────────────
        r1 = tk.Frame(inner, bg=C["card"])
        r1.pack(fill="x")

        tk.Label(r1, text=f"#{t_id}", bg=C["card"], fg=C["text_muted"],
                 font=FONT_SMALL).pack(side="left", padx=(0, 6))

        creator_name = f"{task.get('CREATED_BY_NAME', '')} {task.get('CREATED_BY_LAST_NAME', '')}".strip()
        creator_id   = str(task.get("CREATED_BY") or "")
        if not creator_name and "creator" in task:
            c            = task["creator"]
            creator_name = f"{c.get('name', '')} {c.get('lastName', '')}".strip()
            if not creator_id:
                creator_id = str(c.get("id", ""))

        creator_photo = None
        if creator_id and creator_id in self.app.users_map:
            ud = self.app.users_map[creator_id]
            if isinstance(ud, dict):
                creator_photo = self.app.get_user_avatar(creator_id, ud.get("photo"))

        if creator_name:
            c_f = tk.Frame(r1, bg=C["card"])
            c_f.pack(side="left")
            if creator_photo:
                tk.Label(c_f, image=creator_photo, bg=C["card"]).pack(side="left")
            else:
                tk.Label(c_f, text="👤", bg=C["card"], fg=C["text_muted"],
                         font=FONT_SMALL).pack(side="left")
            disp = creator_name if len(creator_name) <= 15 else creator_name[:12] + "..."
            tk.Label(c_f, text=disp, bg=C["card"], fg=C["text_muted"],
                     font=FONT_SMALL).pack(side="left", padx=(4, 0))

        dot_text  = "● W trakcie" if is_running else "○"
        dot_color = C["btn_green"] if is_running else C["text_dark"]
        tk.Label(r1, text=dot_text, bg=C["card"], fg=dot_color, font=FONT_SMALL).pack(side="right")

        # ── Tytuł ─────────────────────────────────────────────────────
        short_title = title if len(title) <= 55 else title[:52] + "..."
        tk.Label(inner, text=short_title, bg=C["card"], fg=C["text"],
                 font=FONT_TITLE,
                 wraplength=self.CARD_W - 2 * self.CARD_PAD - 4,
                 justify="left", anchor="w").pack(fill="x", pady=(4, 4))

        tk.Frame(inner, bg=C["card_border"], height=1).pack(fill="x", pady=(0, 5))

        # ── Odpowiedzialny ────────────────────────────────────────────
        if resp:
            rr      = tk.Frame(inner, bg=C["card"])
            rr.pack(fill="x", pady=1)
            resp_id = str(task.get("RESPONSIBLE_ID") or task.get("responsibleId") or "")
            if not resp_id and "responsible" in task:
                resp_id = str(task["responsible"].get("id", ""))

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

            # ── Uczestnicy ────────────────────────────────────────────
            if participants_info:
                self._render_participants(inner, participants_info)

        # ── Deadline ──────────────────────────────────────────────────
        if deadline:
            dr       = tk.Frame(inner, bg=C["card"])
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

        # ── Stopka: timer + aktywność ─────────────────────────────────
        footer   = tk.Frame(inner, bg=C["card"])
        footer.pack(fill="x", side="bottom")

        time_var = tk.StringVar(value=f"⏱ {seconds_to_readable(base_time)}")
        tk.Label(footer, textvariable=time_var, bg=C["card"],
                 fg=C["accent"], font=FONT_MONO).pack(side="left")

        if activity_str:
            if days_ago is None or days_ago < 3:
                act_color = C["text_muted"]
            elif days_ago >= 7:
                act_color = C["btn_red"]
            else:
                act_color = "#F59E0B"
            ago_text = "dziś" if not days_ago else f"{days_ago}d temu"
            tk.Label(footer, text=f"🕐 {ago_text}", bg=C["card"],
                     fg=act_color, font=FONT_SMALL).pack(side="right")

        # Rejestruj live timer dla zadań "W trakcie" z dzisiejszą aktywnością
        if is_running:
            act_dt = parse_to_aware_datetime(raw_activity)
            if act_dt:
                today = datetime.now(timezone(timedelta(hours=1))).date()
                if act_dt.date() == today:
                    self._timer_refs[t_id] = {"var": time_var, "base": base_time, "start": act_dt}

        # ── Hover + klik ──────────────────────────────────────────────
        self._bind_hover_and_click(outer, card, t_id)
        return outer

    # ------------------------------------------------------------------
    # Pomocnicze rendery
    # ------------------------------------------------------------------

    def _render_participants(self, parent: tk.Frame, participants_info: list) -> None:
        pr    = tk.Frame(parent, bg=C["card"])
        pr.pack(fill="x", pady=2)
        tk.Label(pr, text="👥", bg=C["card"], fg=C["text_muted"],
                 font=FONT_SMALL).pack(side="left", anchor="nw")

        p_sub   = tk.Frame(pr, bg=C["card"])
        p_sub.pack(side="left", fill="x", padx=3)
        limit   = 3

        for p_id, p_name in participants_info[:limit]:
            p_photo = None
            if p_id and p_id in self.app.users_map:
                ud = self.app.users_map[p_id]
                if isinstance(ud, dict):
                    p_photo = self.app.get_user_avatar(p_id, ud.get("photo"))

            u_f = tk.Frame(p_sub, bg=C["card"])
            u_f.pack(side="top", anchor="w", pady=(0, 3))

            if p_photo:
                tk.Label(u_f, image=p_photo, bg=C["card"]).pack(side="left")
            else:
                tk.Label(u_f, text="👤", bg=C["card"], fg=C["text_muted"],
                         font=FONT_SMALL).pack(side="left")

            disp = p_name if len(p_name) <= 28 else p_name[:25] + "..."
            tk.Label(u_f, text=disp, bg=C["card"], fg=C["text_muted"],
                     font=FONT_SMALL).pack(side="left", padx=(4, 0))

        if len(participants_info) > limit:
            tk.Label(p_sub, text=f"+ {len(participants_info) - limit} innych",
                     bg=C["card"], fg=C["accent"], font=FONT_SMALL).pack(side="top", anchor="w", padx=(2, 0))

    def _bind_hover_and_click(self, outer: tk.Frame, card: tk.Frame, tid: str) -> None:
        def _all_widgets(w):
            res = [w]
            for ch in w.winfo_children():
                res.extend(_all_widgets(ch))
            return res

        def _enter(_event):
            outer.config(bg=C["accent"])
            for w in _all_widgets(card):
                try:
                    if w.cget("bg") == C["card"]:
                        w.config(bg=C["card_hover"])
                except Exception:
                    pass

        def _leave(_event):
            outer.config(bg=C["card_border"])
            for w in _all_widgets(card):
                try:
                    if w.cget("bg") == C["card_hover"]:
                        w.config(bg=C["card"])
                except Exception:
                    pass

        def _click(_event, task_id=tid):
            self.on_open_cb(task_id)

        for w in _all_widgets(outer):
            w.bind("<Enter>",    _enter)
            w.bind("<Leave>",    _leave)
            w.bind("<Button-1>", _click)

    # ------------------------------------------------------------------
    # Live timers
    # ------------------------------------------------------------------

    def _run_timers(self) -> None:
        """Aktualizuje live timery co sekundę."""
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
