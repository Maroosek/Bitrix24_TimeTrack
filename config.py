"""
config.py — Stałe konfiguracyjne: URL, mapy statusów, paleta kolorów, czcionki.
"""
import os

WEBHOOK_URL = os.environ.get(
    "BITRIX_WEBHOOK",
    "https://jenaeuropa.bitrix24.pl/rest/223/8cd46qmskggzo81m/"
)

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

# Paleta kolorów UI
C = {
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

FONT_TITLE   = ("Segoe UI Semibold", 11)
FONT_BODY    = ("Segoe UI", 9)
FONT_SMALL   = ("Segoe UI", 8)
FONT_HEADING = ("Segoe UI Semibold", 13)
FONT_MONO    = ("Consolas", 9)
