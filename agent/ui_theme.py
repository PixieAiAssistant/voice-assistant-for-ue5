"""ui_theme.py — общая палитра и настройка тем (светлая/тёмная) для CTk-окон Pixie.

Используется онбордингом (onboarding.py) и стартовым дашбордом (app_shell.py),
чтобы оба экрана выглядели как единый современный минималистичный продукт.
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

RADIUS = 16
FONT_TITLE = ("Segoe UI", 28, "bold")
FONT_SUBTITLE = ("Segoe UI", 14)
FONT_LABEL = ("Segoe UI", 13, "bold")
FONT_BODY = ("Segoe UI", 12)
FONT_SMALL = ("Segoe UI", 11)

ACCENT = "#8b5cf6"
ACCENT_HOVER = "#7c3aed"
ACCENT_2 = "#22d3ee"

# (light, dark) — кортежи-цвета для CTk, которые автоматически переключаются
# при вызове ctk.set_appearance_mode(...), без пересборки окна.
COLOR_BG = ("#f5f6fa", "#0d0f14")
COLOR_CARD = ("#ffffff", "#1b1f2a")
COLOR_TEXT = ("#1a1a2e", "#e5e7eb")
COLOR_TEXT_DIM = ("#6b7280", "#9ca3af")
COLOR_BORDER = ("#e5e7eb", "#2a2f3d")
COLOR_ENTRY = ("#f3f4f6", "#12151d")


def apply_theme(theme: str) -> None:
    """theme: 'light' | 'dark'. Переключает CTk-режим на лету."""
    ctk.set_appearance_mode("light" if theme == "light" else "dark")
    ctk.set_default_color_theme("blue")


def toggle_theme(current: str) -> str:
    new_theme = "dark" if current == "light" else "light"
    apply_theme(new_theme)
    return new_theme


def enable_paste(entry: ctk.CTkEntry) -> None:
    """Включает вставку/копирование/выделение-всё в поле ввода CTkEntry.

    Зачем это нужно: CTkEntry — обёртка над обычным tk.Entry, и в некоторых
    сборках/раскладках клавиатуры сочетание Ctrl+V может не долетать до
    внутреннего виджета (нет активного бинда). Никто не станет вводить
    API-ключ вручную посимвольно — вставка через буфер обмена ОБЯЗАНА
    работать всегда. Дублируем поддержку двумя способами:
      1. Явные бинды Ctrl+V/C/X/A на внутренний tk.Entry (._entry) —
         работают независимо от раскладки, т.к. используют физические
         сочетания, а не текстовые keysym.
      2. Контекстное меню по правому клику (Cut/Copy/Paste/Select All) —
         универсальный fallback, если сочетания клавиш всё равно не сработали
         (например, из-за глобального перехвата хоткеев на некоторых системах).
    """
    target = getattr(entry, "_entry", entry)

    def _paste(_event=None):
        try:
            target.event_generate("<<Paste>>")
        except Exception:
            pass
        return "break"

    def _copy(_event=None):
        target.event_generate("<<Copy>>")
        return "break"

    def _cut(_event=None):
        target.event_generate("<<Cut>>")
        return "break"

    def _select_all(_event=None):
        target.select_range(0, "end")
        target.icursor("end")
        return "break"

    for seq in ("<Control-v>", "<Control-V>"):
        target.bind(seq, _paste)
    for seq in ("<Control-c>", "<Control-C>"):
        target.bind(seq, _copy)
    for seq in ("<Control-x>", "<Control-X>"):
        target.bind(seq, _cut)
    for seq in ("<Control-a>", "<Control-A>"):
        target.bind(seq, _select_all)

    menu = tk.Menu(target, tearoff=0)
    menu.add_command(label="Cut", command=_cut)
    menu.add_command(label="Copy", command=_copy)
    menu.add_command(label="Paste", command=_paste)
    menu.add_separator()
    menu.add_command(label="Select All", command=_select_all)

    def _popup(event):
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    target.bind("<Button-3>", _popup)
