"""
styles.py — Styl ttk (ciemny motyw) oraz wielokrotnie używane widżety Tk.
"""
import tkinter as tk
from tkinter import ttk
from config import C, FONT_BODY, FONT_SMALL


# ---------------------------------------------------------------------------
# Globalna konfiguracja stylu ttk
# ---------------------------------------------------------------------------

def apply_dark_style(root: tk.Tk) -> None:
    """Aplikuje ciemny motyw do wszystkich widżetów ttk."""
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(
        "Treeview",
        background=C["card"],
        foreground=C["text"],
        fieldbackground=C["card"],
        rowheight=26,
        borderwidth=0,
        font=FONT_BODY,
        relief="flat",
    )
    style.configure(
        "Treeview.Heading",
        background=C["sidebar"],
        foreground=C["accent"],
        font=FONT_BODY,
        borderwidth=0,
        relief="flat",
    )
    style.map(
        "Treeview",
        background=[("selected", C["accent2"])],
        foreground=[("selected", "#FFFFFF")],
    )
    style.configure(
        "Vertical.TScrollbar",
        background=C["sidebar"],
        troughcolor=C["bg"],
        arrowcolor=C["text_muted"],
        borderwidth=0,
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=C["sidebar"],
        troughcolor=C["bg"],
        arrowcolor=C["text_muted"],
        borderwidth=0,
    )
    style.configure(
        "TCombobox",
        fieldbackground=C["input_bg"],
        background=C["input_bg"],
        foreground=C["text"],
        selectbackground=C["accent2"],
        selectforeground="#fff",
        borderwidth=1,
        relief="flat",
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", C["input_bg"])],
        foreground=[("readonly", C["text"])],
    )


# ---------------------------------------------------------------------------
# Wielokrotnie używane widżety
# ---------------------------------------------------------------------------

class ModernButton(tk.Button):
    """Przycisk z efektem hover i zaokrąglonymi krawędziami (flat)."""

    def __init__(self, master, text: str, command, color: str = None, width: int = None, **kwargs):
        color = color or C["btn_blue"]
        super().__init__(
            master,
            text=text,
            command=command,
            bg=color,
            fg="#FFFFFF",
            font=FONT_BODY,
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=14,
            pady=7,
            activebackground=color,
            activeforeground="#FFFFFF",
            width=width or 0,
            **kwargs,
        )
        self._color = color
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, _event) -> None:
        self.config(bg=self._lighten(self._color))

    def _on_leave(self, _event) -> None:
        self.config(bg=self._color)

    @staticmethod
    def _lighten(hex_color: str) -> str:
        r = min(255, int(hex_color[1:3], 16) + 30)
        g = min(255, int(hex_color[3:5], 16) + 30)
        b = min(255, int(hex_color[5:7], 16) + 30)
        return f"#{r:02x}{g:02x}{b:02x}"


class ModernCheckbutton(tk.Checkbutton):
    """Checkbutton dopasowany do ciemnego motywu."""

    def __init__(self, master, text: str, variable, command=None, **kwargs):
        super().__init__(
            master,
            text=text,
            variable=variable,
            command=command,
            bg=C["sidebar"],
            fg=C["text_muted"],
            selectcolor=C["bg"],
            activebackground=C["sidebar"],
            activeforeground=C["text"],
            font=FONT_SMALL,
            relief="flat",
            bd=0,
            cursor="hand2",
            **kwargs,
        )
