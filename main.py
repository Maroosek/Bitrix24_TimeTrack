"""
main.py — Punkt wejścia aplikacji Bitrix24 Task Manager.
"""
import tkinter as tk
from app import BitrixApp


def main() -> None:
    root = tk.Tk()
    BitrixApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
