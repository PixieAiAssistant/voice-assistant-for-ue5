"""app_shell.py — стартовый экран Pixie (домашний дашборд).

Показывается при каждом запуске (после разового онбординга). Даёт кнопки
"Start", "Settings" (повторный запуск wizard'а в режиме редактирования) и
"Get Pro" (переход на сайт с тарифами). Минималистичный, со скруглёнными
углами, светлая/тёмная тема переключаются на лету.
"""

from __future__ import annotations

import webbrowser

import customtkinter as ctk

import licensing
import ui_theme as theme
from config_loader import load_config, update_config
from presets import PERSONALITY_PRESETS, PROJECT_TYPES

PRICING_URL = "https://pixieaiassistant.github.io/voice-assistant-for-ue5/#pricing"
WINDOW_SIZE = "560x620"


class Dashboard(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.action = "exit"
        self.data = load_config()
        theme.apply_theme(self.data.get("theme", "dark"))

        self.title(f"{self.data.get('assistant_name', 'Pixie')} — Home")
        self.geometry(WINDOW_SIZE)
        self.minsize(480, 560)
        self.configure(fg_color=theme.COLOR_BG)
        self.protocol("WM_DELETE_WINDOW", self._on_exit)

        self._build_ui()

    def _build_ui(self):
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=32, pady=28)

        top_row = ctk.CTkFrame(outer, fg_color="transparent")
        top_row.pack(fill="x")
        theme_row = ctk.CTkFrame(top_row, fg_color="transparent")
        theme_row.pack(side="right")
        self.dark_btn = ctk.CTkButton(
            theme_row, text="🌙 Dark", width=90, height=30, corner_radius=theme.RADIUS,
            command=lambda: self._on_theme_pick("dark"),
        )
        self.dark_btn.pack(side="left", padx=(0, 6))
        self.light_btn = ctk.CTkButton(
            theme_row, text="☀ Light", width=90, height=30, corner_radius=theme.RADIUS,
            command=lambda: self._on_theme_pick("light"),
        )
        self.light_btn.pack(side="left")
        self._refresh_theme_buttons()

        # --- Заголовок / логотип ---
        ctk.CTkLabel(
            outer, text=self.data.get("assistant_name", "Pixie"), font=theme.FONT_TITLE,
            text_color=theme.COLOR_TEXT,
        ).pack(pady=(24, 0))
        ctk.CTkLabel(
            outer, text="Your AI voice assistant is ready.", font=theme.FONT_SUBTITLE,
            text_color=theme.COLOR_TEXT_DIM,
        ).pack(pady=(4, 24))

        # --- Карточка статуса ---
        status_card = ctk.CTkFrame(outer, fg_color=theme.COLOR_CARD, corner_radius=theme.RADIUS)
        status_card.pack(fill="x", pady=(0, 24))
        pro_status = licensing.get_license_status()
        is_pro = getattr(pro_status, "valid", False)
        badge_text = "⭐ Pixie Pro — active" if is_pro else "Free plan"
        badge_color = theme.ACCENT if is_pro else theme.COLOR_TEXT_DIM
        ctk.CTkLabel(status_card, text=badge_text, font=theme.FONT_LABEL, text_color=badge_color).pack(
            anchor="w", padx=18, pady=(14, 2)
        )
        personality_label = PERSONALITY_PRESETS.get(self.data.get("personality", ""), {}).get("label", "—")
        project_label = PROJECT_TYPES.get(self.data.get("project_type", ""), {}).get("label", "—")
        details = (
            f"Voice: {self.data.get('voice_name', 'Aoede')}   ·   "
            f"Personality: {personality_label}\nProject: {project_label}"
        )
        ctk.CTkLabel(
            status_card, text=details, font=theme.FONT_BODY, text_color=theme.COLOR_TEXT_DIM,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 14))

        # --- Основные кнопки ---
        ctk.CTkButton(
            outer, text="▶  Start Pixie", height=52, font=theme.FONT_LABEL,
            corner_radius=theme.RADIUS, fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self._on_start,
        ).pack(fill="x", pady=(0, 12))

        ctk.CTkButton(
            outer, text="⚙  Settings", height=44, font=theme.FONT_BODY,
            corner_radius=theme.RADIUS, fg_color="transparent", border_width=1,
            border_color=theme.COLOR_BORDER, text_color=theme.COLOR_TEXT, hover_color=theme.COLOR_ENTRY,
            command=self._on_settings,
        ).pack(fill="x", pady=(0, 12))

        pro_btn_text = "⭐  Manage subscription" if is_pro else "⭐  Get Pixie Pro"
        ctk.CTkButton(
            outer, text=pro_btn_text, height=44, font=theme.FONT_BODY,
            corner_radius=theme.RADIUS, fg_color="transparent", border_width=1,
            border_color=theme.ACCENT, text_color=theme.ACCENT, hover_color=theme.COLOR_ENTRY,
            command=lambda: webbrowser.open(PRICING_URL),
        ).pack(fill="x", pady=(0, 12))

        if not is_pro:
            ctk.CTkLabel(
                outer,
                text="Pro unlocks full Unreal Engine control: actors, Blueprints, camera & more.",
                font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_DIM, wraplength=460, justify="center",
            ).pack(pady=(0, 12))

        ctk.CTkButton(
            outer, text="Exit", height=36, font=theme.FONT_SMALL,
            corner_radius=theme.RADIUS, fg_color="transparent", text_color=theme.COLOR_TEXT_DIM,
            hover_color=theme.COLOR_ENTRY, command=self._on_exit,
        ).pack(fill="x", pady=(8, 0))

    def _on_theme_pick(self, new_theme: str):
        theme.apply_theme(new_theme)
        self.data = update_config(theme=new_theme)
        self._refresh_theme_buttons()

    def _refresh_theme_buttons(self):
        """Подсвечивает активную тему заливкой+обводкой, вторая кнопка — прозрачная
        с рамкой. Раньше был обычный CTkSwitch без чёткой индикации выбранного
        состояния — по просьбе сделано явным и презентабельным, как в онбординге."""
        selected = self.data.get("theme", "dark")
        for btn, key in ((self.dark_btn, "dark"), (self.light_btn, "light")):
            if key == selected:
                btn.configure(
                    fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                    text_color="#ffffff", border_width=2, border_color=theme.ACCENT,
                )
            else:
                btn.configure(
                    fg_color="transparent", hover_color=theme.COLOR_ENTRY,
                    text_color=theme.COLOR_TEXT, border_width=1, border_color=theme.COLOR_BORDER,
                )

    def _on_start(self):
        self.action = "start"
        self.destroy()

    def _on_settings(self):
        self.destroy()
        try:
            from onboarding import run_onboarding
            run_onboarding(edit_mode=True)
        except Exception:
            pass
        # После настроек снова показываем дашборд (рекурсивно, через run_dashboard).
        self.action = "settings_done"

    def _on_exit(self):
        self.action = "exit"
        self.destroy()


def run_dashboard() -> str:
    """Показывает домашний экран. Возвращает 'start' или 'exit'.

    Если пользователь открыл Settings — после закрытия wizard'а дашборд
    показывается снова (без перезапуска процесса).
    """
    while True:
        dash = Dashboard()
        dash.mainloop()
        if dash.action == "settings_done":
            continue
        return dash.action


if __name__ == "__main__":
    print(run_dashboard())
