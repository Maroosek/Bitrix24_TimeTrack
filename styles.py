"""
styles.py — Styl ttk (ciemny motyw) oraz wielokrotnie używane widżety Tk.
"""
import tkinter as tk
from tkinter import ttk
# from config import C, FONT_BODY, FONT_SMALL


# ---------------------------------------------------------------------------
# Globalna konfiguracja stylu ttk
# ---------------------------------------------------------------------------

STATUS_MAP = {
    "1": "Nowe",
    "2": "Oczekujące",
    "3": "W trakcie",
    "4": "Do kontroli",
    "5": "Zakończone",
    "6": "Odłożone",
}

STATUS_COLORS = {
    "Nowe":        "#3B82F6",
    "Oczekujące":  "#F59E0B",
    "W trakcie":   "#10B981",
    "Do kontroli": "#8B5CF6",
    "Zakończone":  "#6B7280",
    "Odłożone":    "#EF4444",
}

# ── Ciemny motyw (domyślny)
DARK_C: dict = {
    "bg":           "#0F172A",
    "sidebar":      "#1E293B",
    "card":         "#1E293B",
    "card_hover":   "#293548",
    "card_border":  "#334155",
    "header":       "#0F172A",
    "accent":       "#38BDF8",
    "accent2":      "#818CF8",
    "text":         "#E2E8F0",
    "text_muted":   "#94A3B8",
    "text_dark":    "#64748B",
    "btn_green":    "#10B981",
    "btn_blue":     "#3B82F6",
    "btn_red":      "#EF4444",
    "input_bg":     "#1E293B",
    "input_border": "#334155",
    "divider":      "#1E3A5F",
    "tag_bg":       "#0F3460",
    "tag_text":     "#7DD3FC",
}

# ── Jasny motyw
LIGHT_C: dict = {
    "bg":           "#F1F5F9",
    "sidebar":      "#E2E8F0",
    "card":         "#FFFFFF",
    "card_hover":   "#F8FAFC",
    "card_border":  "#CBD5E1",
    "header":       "#1E293B",   # topbar celowo ciemny — kontrast z białym tekstem
    "accent":       "#0284C7",
    "accent2":      "#7C3AED",
    "text":         "#1E293B",
    "text_muted":   "#64748B",
    "text_dark":    "#94A3B8",
    "btn_green":    "#059669",
    "btn_blue":     "#2563EB",
    "btn_red":      "#DC2626",
    "input_bg":     "#FFFFFF",
    "input_border": "#CBD5E1",
    "divider":      "#BFDBFE",
    "tag_bg":       "#DBEAFE",
    "tag_text":     "#1D4ED8",
}

THEMES: dict = {
    "dark":  DARK_C,
    "light": LIGHT_C,
}

# C — aktywna paleta; modyfikowana w-miejscu przy zmianie motywu.
# Wszystkie moduły importują C jako referencję do tego słownika.
C: dict = dict(DARK_C)


def apply_theme(name: str) -> None:
    """Ustawia aktywną paletę C na wybrany motyw ('dark' lub 'light')."""
    C.update(THEMES.get(name, DARK_C))


# ── Czcionki
FONT_TITLE   = ("Segoe UI Semibold", 11)
FONT_BODY    = ("Segoe UI", 9)
FONT_SMALL   = ("Segoe UI", 8)
FONT_HEADING = ("Segoe UI Semibold", 13)
FONT_MONO    = ("Consolas", 9)

def apply_theme_style(root: tk.Tk) -> None:
    """Aplikuje aktualną paletę C do wszystkich widżetów ttk."""
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