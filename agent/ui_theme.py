"""ui_theme.py — общая палитра и настройка тем (светлая/тёмная) для CTk-окон Pixie.

Используется онбордингом (onboarding.py) и стартовым дашбордом (app_shell.py),
чтобы оба экрана выглядели как единый современный минималистичный продукт.
"""

from __future__ import annotations

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
