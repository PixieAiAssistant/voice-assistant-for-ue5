"""onboarding.py — приветственный анимированный wizard первого запуска Pixie
+ быстрый экран настроек (Quick Settings) для повторного редактирования.

Показывается один раз при первой установке. Шаги первого запуска:
  0. Язык интерфейса/общения (всплывающий список, 7 самых популярных языков)
  1. Приветствие + выбор темы (светлая/тёмная) — выбранная кнопка подсвечена
  2. AI-провайдер + API-ключ (сейчас доступен только Gemini) + инструкция получения ключа
  3. Имя ассистента, голос, характер, тип проекта
  4. Путь к проекту UE (+ инструкция включения Remote Execution) + диздок (опционально)
  5. Итоговый экран

Если онбординг уже пройден — кнопка "Settings" в дашборде (app_shell.py)
открывает НЕ этот анимированный wizard с нуля, а компактный QuickSettingsWindow:
один экран со списком всех сохранённых параметров (подписанные поля,
выпадающие списки), который можно отредактировать и сохранить без повторного
прохождения всех шагов заново.

Все данные сохраняются в config.json через config_loader.update_config().
Ничего не требует от пользователя вручную редактировать файлы.
"""

from __future__ import annotations

import shutil
import webbrowser
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

import ui_theme as theme
from config_loader import BASE_DIR, load_config, save_config
from presets import (
    AI_PROVIDERS,
    DEFAULT_PERSONALITY,
    DEFAULT_PROJECT_TYPE,
    DEFAULT_PROVIDER,
    DEFAULT_UI_LANGUAGE,
    GEMINI_VOICES,
    PERSONALITY_PRESETS,
    PROJECT_TYPES,
    UI_LANGUAGES,
)

WINDOW_SIZE = "760x560"
SETTINGS_WINDOW_SIZE = "640x720"


# ---------------------------------------------------------------------------
# Общие мелкие хелперы
# ---------------------------------------------------------------------------

def _paste_entry(master, **kwargs) -> ctk.CTkEntry:
    """CTkEntry с гарантированно рабочей вставкой/копированием (Ctrl+V/C/X, ПКМ-меню)."""
    entry = ctk.CTkEntry(master, **kwargs)
    theme.enable_paste(entry)
    return entry


# ---------------------------------------------------------------------------
# Шаги полного wizard'а (первый запуск)
# ---------------------------------------------------------------------------

class _StepFrame(ctk.CTkFrame):
    """Базовый контейнер шага: заголовок + подзаголовок + область контента."""

    def __init__(self, master, title: str, subtitle: str = ""):
        super().__init__(master, fg_color="transparent")
        ctk.CTkLabel(self, text=title, font=theme.FONT_TITLE, text_color=theme.COLOR_TEXT).pack(
            anchor="w", pady=(0, 4)
        )
        if subtitle:
            ctk.CTkLabel(
                self, text=subtitle, font=theme.FONT_SUBTITLE, text_color=theme.COLOR_TEXT_DIM,
                wraplength=680, justify="left",
            ).pack(anchor="w", pady=(0, 20))
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)

    def validate(self) -> str | None:
        """Вернуть None если всё ок, иначе текст ошибки."""
        return None

    def save(self, data: dict) -> None:
        pass


class LanguageStep(_StepFrame):
    """Первый экран — выбор языка интерфейса/общения (всплывающий список)."""

    def __init__(self, master, data: dict):
        super().__init__(
            master,
            "🌍 Choose your language",
            "Pick the language Pixie will speak and use in its interface. "
            "You can change this later anytime from Settings.",
        )
        ctk.CTkLabel(self.body, text="Language", font=theme.FONT_LABEL, text_color=theme.COLOR_TEXT).pack(
            anchor="w"
        )
        self._labels = [info["label"] for info in UI_LANGUAGES.values()]
        self._label_to_key = {info["label"]: key for key, info in UI_LANGUAGES.items()}
        current = data.get("language", DEFAULT_UI_LANGUAGE)
        current_label = UI_LANGUAGES.get(current, UI_LANGUAGES[DEFAULT_UI_LANGUAGE])["label"]
        self.lang_var = ctk.StringVar(value=current_label)
        ctk.CTkOptionMenu(
            self.body, values=self._labels, variable=self.lang_var, width=320,
            fg_color=theme.ACCENT, button_color=theme.ACCENT_HOVER, button_hover_color=theme.ACCENT_HOVER,
        ).pack(anchor="w", pady=(4, 18))

    def save(self, data: dict) -> None:
        data["language"] = self._label_to_key.get(self.lang_var.get(), DEFAULT_UI_LANGUAGE)


class WelcomeStep(_StepFrame):
    def __init__(self, master, data: dict):
        super().__init__(
            master,
            "Welcome to Pixie 👋",
            "Let's set your assistant up in a couple of minutes. No config files, "
            "no manual editing — just answer a few questions.",
        )
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(anchor="w", pady=10)
        ctk.CTkLabel(row, text="Choose your theme:", font=theme.FONT_LABEL, text_color=theme.COLOR_TEXT).pack(
            side="left", padx=(0, 16)
        )
        self.theme_var = ctk.StringVar(value=data.get("theme", "dark"))

        self.dark_btn = ctk.CTkButton(
            row, text="🌙 Dark", width=110, corner_radius=theme.RADIUS,
            command=lambda: self._pick("dark"),
        )
        self.dark_btn.pack(side="left", padx=6)
        self.light_btn = ctk.CTkButton(
            row, text="☀ Light", width=110, corner_radius=theme.RADIUS,
            command=lambda: self._pick("light"),
        )
        self.light_btn.pack(side="left", padx=6)
        self._refresh_buttons()

    def _pick(self, val: str):
        self.theme_var.set(val)
        theme.apply_theme(val)
        self._refresh_buttons()

    def _refresh_buttons(self):
        """Явно подсвечивает выбранную тему — заливка+обводка у активной кнопки,
        прозрачная кнопка с рамкой у неактивной. Без этого обе кнопки выглядели
        одинаково и было не видно, какая тема выбрана сейчас."""
        selected = self.theme_var.get()
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

    def save(self, data: dict) -> None:
        data["theme"] = self.theme_var.get()


class ApiKeyStep(_StepFrame):
    def __init__(self, master, data: dict):
        super().__init__(
            master,
            "Connect your AI",
            "Pick an AI provider and paste your API key. Pixie currently runs on "
            "Google Gemini Live — support for more providers is coming soon.",
        )
        ctk.CTkLabel(self.body, text="AI provider", font=theme.FONT_LABEL, text_color=theme.COLOR_TEXT).pack(
            anchor="w"
        )
        provider_labels = [info["label"] for info in AI_PROVIDERS.values()]
        self._provider_keys = list(AI_PROVIDERS.keys())
        self.provider_var = ctk.StringVar(
            value=AI_PROVIDERS.get(data.get("ai_provider", DEFAULT_PROVIDER), AI_PROVIDERS[DEFAULT_PROVIDER])["label"]
        )
        menu = ctk.CTkOptionMenu(self.body, values=provider_labels, variable=self.provider_var, width=320)
        menu.pack(anchor="w", pady=(4, 18))

        ctk.CTkLabel(self.body, text="API key", font=theme.FONT_LABEL, text_color=theme.COLOR_TEXT).pack(anchor="w")
        # show="•" по умолчанию, но вставка (Ctrl+V/ПКМ) работает всегда — см. ui_theme.enable_paste.
        self.key_entry = _paste_entry(
            self.body, width=460, show="•", placeholder_text="Paste your API key here",
            corner_radius=theme.RADIUS,
        )
        self.key_entry.pack(anchor="w", pady=(4, 6))
        if data.get("gemini_api_key"):
            self.key_entry.insert(0, data["gemini_api_key"])

        self.show_var = ctk.BooleanVar(value=False)

        def _toggle_show():
            self.key_entry.configure(show="" if self.show_var.get() else "•")

        ctk.CTkCheckBox(
            self.body, text="Show key", variable=self.show_var, command=_toggle_show,
            font=theme.FONT_SMALL,
        ).pack(anchor="w", pady=(0, 16))

        help_url = AI_PROVIDERS[DEFAULT_PROVIDER]["key_help_url"]
        help_text = AI_PROVIDERS[DEFAULT_PROVIDER]["key_help_text"]
        info_card = ctk.CTkFrame(self.body, fg_color=theme.COLOR_CARD, corner_radius=theme.RADIUS)
        info_card.pack(anchor="w", fill="x", pady=(4, 0))
        ctk.CTkLabel(
            info_card, text=f"ℹ  {help_text}", font=theme.FONT_BODY, text_color=theme.COLOR_TEXT_DIM,
            wraplength=560, justify="left",
        ).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkButton(
            info_card, text="Open Google AI Studio →", fg_color="transparent",
            text_color=theme.ACCENT_2, hover_color=theme.COLOR_ENTRY, anchor="w",
            command=lambda: webbrowser.open(help_url),
        ).pack(anchor="w", padx=8, pady=(0, 10))

    def validate(self) -> str | None:
        if not self.key_entry.get().strip():
            return "Please paste your Gemini API key to continue."
        return None

    def save(self, data: dict) -> None:
        label_to_key = {info["label"]: key for key, info in AI_PROVIDERS.items()}
        data["ai_provider"] = label_to_key.get(self.provider_var.get(), DEFAULT_PROVIDER)
        data["gemini_api_key"] = self.key_entry.get().strip()


class IdentityStep(_StepFrame):
    def __init__(self, master, data: dict):
        super().__init__(
            master,
            "Make it yours",
            "Name your assistant, pick a voice and a personality, and tell Pixie "
            "what kind of project you're building.",
        )
        left = ctk.CTkFrame(self.body, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=(0, 24))
        right = ctk.CTkFrame(self.body, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(left, text="Assistant name", font=theme.FONT_LABEL, text_color=theme.COLOR_TEXT).pack(anchor="w")
        self.name_entry = _paste_entry(left, width=280, corner_radius=theme.RADIUS, placeholder_text="Pixie")
        self.name_entry.pack(anchor="w", pady=(4, 16))
        self.name_entry.insert(0, data.get("assistant_name", "Pixie"))

        ctk.CTkLabel(left, text="Voice", font=theme.FONT_LABEL, text_color=theme.COLOR_TEXT).pack(anchor="w")
        self.voice_var = ctk.StringVar(value=data.get("voice_name", GEMINI_VOICES[0]))
        ctk.CTkOptionMenu(left, values=GEMINI_VOICES, variable=self.voice_var, width=280).pack(anchor="w", pady=(4, 16))

        ctk.CTkLabel(left, text="Personality", font=theme.FONT_LABEL, text_color=theme.COLOR_TEXT).pack(anchor="w")
        self._personality_labels = [v["label"] for v in PERSONALITY_PRESETS.values()]
        self._personality_keys = list(PERSONALITY_PRESETS.keys())
        current_personality = data.get("personality", DEFAULT_PERSONALITY)
        self.personality_var = ctk.StringVar(
            value=PERSONALITY_PRESETS.get(current_personality, PERSONALITY_PRESETS[DEFAULT_PERSONALITY])["label"]
        )
        ctk.CTkOptionMenu(left, values=self._personality_labels, variable=self.personality_var, width=280).pack(
            anchor="w", pady=(4, 4)
        )
        self.personality_desc = ctk.CTkLabel(
            left, text="", font=theme.FONT_SMALL, text_color=theme.COLOR_TEXT_DIM, wraplength=280, justify="left"
        )
        self.personality_desc.pack(anchor="w", pady=(0, 16))

        def _update_desc(*_):
            label_to_key = {v["label"]: k for k, v in PERSONALITY_PRESETS.items()}
            key = label_to_key.get(self.personality_var.get())
            if key:
                self.personality_desc.configure(text=PERSONALITY_PRESETS[key]["description"])

        self.personality_var.trace_add("write", _update_desc)
        _update_desc()

        ctk.CTkLabel(right, text="What are you building?", font=theme.FONT_LABEL, text_color=theme.COLOR_TEXT).pack(
            anchor="w"
        )
        self._project_labels = [v["label"] for v in PROJECT_TYPES.values()]
        current_project = data.get("project_type", DEFAULT_PROJECT_TYPE)
        self.project_var = ctk.StringVar(
            value=PROJECT_TYPES.get(current_project, PROJECT_TYPES[DEFAULT_PROJECT_TYPE])["label"]
        )
        for label in self._project_labels:
            ctk.CTkRadioButton(
                right, text=label, variable=self.project_var, value=label, font=theme.FONT_BODY,
            ).pack(anchor="w", pady=6)

    def validate(self) -> str | None:
        if not self.name_entry.get().strip():
            return "Give your assistant a name."
        return None

    def save(self, data: dict) -> None:
        data["assistant_name"] = self.name_entry.get().strip() or "Pixie"
        data["voice_name"] = self.voice_var.get()
        label_to_key = {v["label"]: k for k, v in PERSONALITY_PRESETS.items()}
        data["personality"] = label_to_key.get(self.personality_var.get(), DEFAULT_PERSONALITY)
        label_to_key_p = {v["label"]: k for k, v in PROJECT_TYPES.items()}
        data["project_type"] = label_to_key_p.get(self.project_var.get(), DEFAULT_PROJECT_TYPE)


class UnrealSetupStep(_StepFrame):
    def __init__(self, master, data: dict):
        super().__init__(
            master,
            "Unreal Engine setup (optional)",
            "If you're using Unreal Engine, point Pixie to your project and enable "
            "Python Remote Execution. Not using UE? Just skip this step.",
        )
        ctk.CTkLabel(self.body, text="UE project folder", font=theme.FONT_LABEL, text_color=theme.COLOR_TEXT).pack(
            anchor="w"
        )
        path_row = ctk.CTkFrame(self.body, fg_color="transparent")
        path_row.pack(anchor="w", fill="x", pady=(4, 4))
        self.path_entry = _paste_entry(path_row, width=480, corner_radius=theme.RADIUS)
        self.path_entry.pack(side="left")
        self.path_entry.insert(0, data.get("ue_project_path", ""))
        ctk.CTkButton(
            path_row, text="Browse…", width=90, corner_radius=theme.RADIUS,
            fg_color="transparent", border_width=1, border_color=theme.COLOR_BORDER,
            text_color=theme.COLOR_TEXT, hover_color=theme.COLOR_ENTRY,
            command=self._browse_folder,
        ).pack(side="left", padx=(8, 0))

        info_card = ctk.CTkFrame(self.body, fg_color=theme.COLOR_CARD, corner_radius=theme.RADIUS)
        info_card.pack(anchor="w", fill="x", pady=(16, 16))
        ctk.CTkLabel(
            info_card,
            text=(
                "ℹ  In Unreal Editor: Edit → Project Settings → Plugins → Python → "
                "enable “Enable Remote Execution”. Restart the editor afterwards."
            ),
            font=theme.FONT_BODY, text_color=theme.COLOR_TEXT_DIM, wraplength=600, justify="left",
        ).pack(anchor="w", padx=16, pady=12)

        ctk.CTkLabel(
            self.body, text="Game Design Document (optional, PDF or TXT)", font=theme.FONT_LABEL,
            text_color=theme.COLOR_TEXT,
        ).pack(anchor="w")
        gdd_row = ctk.CTkFrame(self.body, fg_color="transparent")
        gdd_row.pack(anchor="w", fill="x", pady=(4, 4))
        self.gdd_label = ctk.CTkLabel(
            gdd_row, text=self._gdd_display(data.get("gdd_path", "")), font=theme.FONT_BODY,
            text_color=theme.COLOR_TEXT_DIM,
        )
        self.gdd_label.pack(side="left")
        ctk.CTkButton(
            gdd_row, text="Upload…", width=90, corner_radius=theme.RADIUS,
            fg_color="transparent", border_width=1, border_color=theme.COLOR_BORDER,
            text_color=theme.COLOR_TEXT, hover_color=theme.COLOR_ENTRY,
            command=self._browse_gdd,
        ).pack(side="left", padx=(12, 0))

        self._gdd_path_value = data.get("gdd_path", "")

    @staticmethod
    def _gdd_display(path: str) -> str:
        return f"Attached: {Path(path).name}" if path else "No document attached"

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select your Unreal Engine project folder")
        if folder:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, folder)

    def _browse_gdd(self):
        file_path = filedialog.askopenfilename(
            title="Select your Game Design Document",
            filetypes=[("PDF or text", "*.pdf *.txt"), ("All files", "*.*")],
        )
        if not file_path:
            return
        try:
            dest_name = "gdd" + Path(file_path).suffix.lower()
            dest_path = BASE_DIR / dest_name
            shutil.copy(file_path, dest_path)
            self._gdd_path_value = f"./{dest_name}"
            self.gdd_label.configure(text=self._gdd_display(self._gdd_path_value))
        except OSError as exc:
            self.gdd_label.configure(text=f"Failed to copy file: {exc}")

    def save(self, data: dict) -> None:
        data["ue_project_path"] = self.path_entry.get().strip()
        data["gdd_path"] = self._gdd_path_value


class SummaryStep(_StepFrame):
    def __init__(self, master, data: dict):
        super().__init__(
            master,
            "All set! 🎉",
            "Pixie is ready to go. You can revisit any of these settings later from "
            "the Settings button on the home screen.",
        )
        card = ctk.CTkFrame(self.body, fg_color=theme.COLOR_CARD, corner_radius=theme.RADIUS)
        card.pack(fill="both", expand=True)
        rows = [
            ("Language", UI_LANGUAGES.get(data.get("language", DEFAULT_UI_LANGUAGE), {}).get("label", "")),
            ("Assistant name", data.get("assistant_name", "Pixie")),
            ("Voice", data.get("voice_name", "Aoede")),
            ("Personality", PERSONALITY_PRESETS.get(data.get("personality", DEFAULT_PERSONALITY), {}).get("label", "")),
            ("Project", PROJECT_TYPES.get(data.get("project_type", DEFAULT_PROJECT_TYPE), {}).get("label", "")),
            ("UE project path", data.get("ue_project_path") or "— (not set)"),
            ("Game Design Document", data.get("gdd_path") or "— (not attached)"),
        ]
        for label, value in rows:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=8)
            ctk.CTkLabel(row, text=label, font=theme.FONT_LABEL, text_color=theme.COLOR_TEXT_DIM, width=200, anchor="w").pack(
                side="left"
            )
            ctk.CTkLabel(row, text=str(value), font=theme.FONT_BODY, text_color=theme.COLOR_TEXT, anchor="w").pack(
                side="left"
            )


class OnboardingWizard(ctk.CTk):
    """Полный анимированный wizard — показывается ТОЛЬКО при первом запуске
    (когда onboarding_complete=False в config.json). Повторное редактирование
    настроек уже настроенного приложения идёт через QuickSettingsWindow ниже."""

    def __init__(self):
        super().__init__()
        self.title("Pixie — Setup")
        self.geometry(WINDOW_SIZE)
        self.minsize(720, 520)
        self.resizable(True, True)

        self.data = load_config()
        theme.apply_theme(self.data.get("theme", "dark"))
        self.configure(fg_color=theme.COLOR_BG)

        self.step_classes = [LanguageStep, WelcomeStep, ApiKeyStep, IdentityStep, UnrealSetupStep, SummaryStep]
        self.step_index = 0
        self.current_step: _StepFrame | None = None

        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=36, pady=28)

        self.progress = ctk.CTkProgressBar(outer, height=6, corner_radius=3, progress_color=theme.ACCENT)
        self.progress.pack(fill="x", pady=(0, 24))

        self.content_area = ctk.CTkFrame(outer, fg_color="transparent")
        self.content_area.pack(fill="both", expand=True)

        nav = ctk.CTkFrame(outer, fg_color="transparent")
        nav.pack(fill="x", pady=(20, 0))
        self.back_btn = ctk.CTkButton(
            nav, text="← Back", width=110, corner_radius=theme.RADIUS, fg_color="transparent",
            border_width=1, border_color=theme.COLOR_BORDER, text_color=theme.COLOR_TEXT,
            hover_color=theme.COLOR_ENTRY, command=self._go_back,
        )
        self.back_btn.pack(side="left")
        self.error_label = ctk.CTkLabel(nav, text="", font=theme.FONT_SMALL, text_color="#f87171")
        self.error_label.pack(side="left", padx=16)
        self.next_btn = ctk.CTkButton(
            nav, text="Next →", width=140, corner_radius=theme.RADIUS, fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER, command=self._go_next,
        )
        self.next_btn.pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._render_step()

    def _clear_content(self):
        for widget in self.content_area.winfo_children():
            widget.destroy()

    def _render_step(self):
        self._clear_content()
        self.error_label.configure(text="")
        step_cls = self.step_classes[self.step_index]
        self.current_step = step_cls(self.content_area, self.data)
        self.current_step.pack(fill="both", expand=True)
        self.progress.set((self.step_index + 1) / len(self.step_classes))
        self.back_btn.configure(state="normal" if self.step_index > 0 else "disabled")
        is_last = self.step_index == len(self.step_classes) - 1
        self.next_btn.configure(text="Finish" if is_last else "Next →")

    def _go_back(self):
        if self.current_step:
            self.current_step.save(self.data)
        if self.step_index > 0:
            self.step_index -= 1
            self._render_step()

    def _go_next(self):
        if self.current_step:
            error = self.current_step.validate()
            if error:
                self.error_label.configure(text=error)
                return
            self.current_step.save(self.data)

        if self.step_index < len(self.step_classes) - 1:
            self.step_index += 1
            self._render_step()
        else:
            self._finish()

    def _finish(self):
        self.data["onboarding_complete"] = True
        save_config(self.data)
        self.destroy()

    def _on_close(self):
        # Если пользователь закрыл окно крестиком до завершения первого запуска —
        # сохраняем то, что уже успел ввести, но НЕ отмечаем онбординг завершённым,
        # чтобы wizard показался снова при следующем запуске (иначе пользователь
        # окажется с неполным config.json и без возможности его донастроить).
        if self.current_step:
            self.current_step.save(self.data)
        save_config(self.data)
        self.destroy()


# ---------------------------------------------------------------------------
# Quick Settings — компактный экран редактирования уже настроенного приложения
# ---------------------------------------------------------------------------

class QuickSettingsWindow(ctk.CTk):
    """Открывается по кнопке "Settings" в дашборде, когда онбординг уже пройден.

    В отличие от OnboardingWizard, это ОДИН прокручиваемый экран со всеми
    сохранёнными параметрами сразу — подписанные поля и выпадающие списки,
    без пошагового "Next →". Пользователю не нужно проходить всю анимированную
    настройку с нуля, чтобы поменять, например, только голос или тему.
    """

    def __init__(self):
        super().__init__()
        self.data = load_config()
        theme.apply_theme(self.data.get("theme", "dark"))
        self.configure(fg_color=theme.COLOR_BG)

        self.title("Pixie — Settings")
        self.geometry(SETTINGS_WINDOW_SIZE)
        self.minsize(520, 480)
        self.saved = False

        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=28, pady=24)

        ctk.CTkLabel(outer, text="Settings", font=theme.FONT_TITLE, text_color=theme.COLOR_TEXT).pack(
            anchor="w", pady=(0, 4)
        )
        ctk.CTkLabel(
            outer, text="Edit any of your saved preferences below and hit Save.",
            font=theme.FONT_SUBTITLE, text_color=theme.COLOR_TEXT_DIM,
        ).pack(anchor="w", pady=(0, 16))

        scroll = ctk.CTkScrollableFrame(outer, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        self._build_field_language(scroll)
        self._build_field_theme(scroll)
        self._build_field_provider_and_key(scroll)
        self._build_field_identity(scroll)
        self._build_field_project(scroll)
        self._build_field_ue(scroll)
        self._build_field_gdd(scroll)

        nav = ctk.CTkFrame(outer, fg_color="transparent")
        nav.pack(fill="x", pady=(16, 0))
        ctk.CTkButton(
            nav, text="Close", width=110, corner_radius=theme.RADIUS, fg_color="transparent",
            border_width=1, border_color=theme.COLOR_BORDER, text_color=theme.COLOR_TEXT,
            hover_color=theme.COLOR_ENTRY, command=self._on_close,
        ).pack(side="left")
        self.status_label = ctk.CTkLabel(nav, text="", font=theme.FONT_SMALL, text_color="#34d399")
        self.status_label.pack(side="left", padx=16)
        ctk.CTkButton(
            nav, text="💾 Save", width=140, corner_radius=theme.RADIUS, fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER, command=self._save,
        ).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- Секции полей ---

    def _section_label(self, master, text: str):
        ctk.CTkLabel(master, text=text, font=theme.FONT_LABEL, text_color=theme.COLOR_TEXT).pack(
            anchor="w", pady=(14, 4)
        )

    def _build_field_language(self, master):
        self._section_label(master, "Language")
        labels = [info["label"] for info in UI_LANGUAGES.values()]
        self._lang_label_to_key = {info["label"]: key for key, info in UI_LANGUAGES.items()}
        current = self.data.get("language", DEFAULT_UI_LANGUAGE)
        current_label = UI_LANGUAGES.get(current, UI_LANGUAGES[DEFAULT_UI_LANGUAGE])["label"]
        self.lang_var = ctk.StringVar(value=current_label)
        ctk.CTkOptionMenu(master, values=labels, variable=self.lang_var, width=320).pack(anchor="w")

    def _build_field_theme(self, master):
        self._section_label(master, "Theme")
        row = ctk.CTkFrame(master, fg_color="transparent")
        row.pack(anchor="w")
        self.theme_var = ctk.StringVar(value=self.data.get("theme", "dark"))
        self.dark_btn = ctk.CTkButton(row, text="🌙 Dark", width=110, corner_radius=theme.RADIUS,
                                       command=lambda: self._pick_theme("dark"))
        self.dark_btn.pack(side="left", padx=(0, 6))
        self.light_btn = ctk.CTkButton(row, text="☀ Light", width=110, corner_radius=theme.RADIUS,
                                        command=lambda: self._pick_theme("light"))
        self.light_btn.pack(side="left")
        self._refresh_theme_buttons()

    def _pick_theme(self, val: str):
        self.theme_var.set(val)
        theme.apply_theme(val)
        self._refresh_theme_buttons()

    def _refresh_theme_buttons(self):
        selected = self.theme_var.get()
        for btn, key in ((self.dark_btn, "dark"), (self.light_btn, "light")):
            if key == selected:
                btn.configure(fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                              text_color="#ffffff", border_width=2, border_color=theme.ACCENT)
            else:
                btn.configure(fg_color="transparent", hover_color=theme.COLOR_ENTRY,
                              text_color=theme.COLOR_TEXT, border_width=1, border_color=theme.COLOR_BORDER)

    def _build_field_provider_and_key(self, master):
        self._section_label(master, "AI provider")
        provider_labels = [info["label"] for info in AI_PROVIDERS.values()]
        self._provider_label_to_key = {info["label"]: key for key, info in AI_PROVIDERS.items()}
        self.provider_var = ctk.StringVar(
            value=AI_PROVIDERS.get(self.data.get("ai_provider", DEFAULT_PROVIDER), AI_PROVIDERS[DEFAULT_PROVIDER])["label"]
        )
        ctk.CTkOptionMenu(master, values=provider_labels, variable=self.provider_var, width=320).pack(anchor="w")

        self._section_label(master, "API key")
        key_row = ctk.CTkFrame(master, fg_color="transparent")
        key_row.pack(anchor="w", fill="x")
        self.key_entry = _paste_entry(key_row, width=380, show="•", corner_radius=theme.RADIUS)
        self.key_entry.pack(side="left")
        if self.data.get("gemini_api_key"):
            self.key_entry.insert(0, self.data["gemini_api_key"])
        self.show_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            key_row, text="Show", variable=self.show_var, font=theme.FONT_SMALL,
            command=lambda: self.key_entry.configure(show="" if self.show_var.get() else "•"),
        ).pack(side="left", padx=(12, 0))

    def _build_field_identity(self, master):
        self._section_label(master, "Assistant name")
        self.name_entry = _paste_entry(master, width=320, corner_radius=theme.RADIUS)
        self.name_entry.pack(anchor="w")
        self.name_entry.insert(0, self.data.get("assistant_name", "Pixie"))

        self._section_label(master, "Voice")
        self.voice_var = ctk.StringVar(value=self.data.get("voice_name", GEMINI_VOICES[0]))
        ctk.CTkOptionMenu(master, values=GEMINI_VOICES, variable=self.voice_var, width=320).pack(anchor="w")

        self._section_label(master, "Personality")
        self._personality_label_to_key = {v["label"]: k for k, v in PERSONALITY_PRESETS.items()}
        current_personality = self.data.get("personality", DEFAULT_PERSONALITY)
        self.personality_var = ctk.StringVar(
            value=PERSONALITY_PRESETS.get(current_personality, PERSONALITY_PRESETS[DEFAULT_PERSONALITY])["label"]
        )
        ctk.CTkOptionMenu(
            master, values=[v["label"] for v in PERSONALITY_PRESETS.values()],
            variable=self.personality_var, width=320,
        ).pack(anchor="w")

    def _build_field_project(self, master):
        self._section_label(master, "Project type")
        self._project_label_to_key = {v["label"]: k for k, v in PROJECT_TYPES.items()}
        current_project = self.data.get("project_type", DEFAULT_PROJECT_TYPE)
        self.project_var = ctk.StringVar(
            value=PROJECT_TYPES.get(current_project, PROJECT_TYPES[DEFAULT_PROJECT_TYPE])["label"]
        )
        ctk.CTkOptionMenu(
            master, values=[v["label"] for v in PROJECT_TYPES.values()],
            variable=self.project_var, width=320,
        ).pack(anchor="w")

    def _build_field_ue(self, master):
        self._section_label(master, "UE project folder")
        row = ctk.CTkFrame(master, fg_color="transparent")
        row.pack(anchor="w", fill="x")
        self.path_entry = _paste_entry(row, width=380, corner_radius=theme.RADIUS)
        self.path_entry.pack(side="left")
        self.path_entry.insert(0, self.data.get("ue_project_path", ""))
        ctk.CTkButton(
            row, text="Browse…", width=90, corner_radius=theme.RADIUS,
            fg_color="transparent", border_width=1, border_color=theme.COLOR_BORDER,
            text_color=theme.COLOR_TEXT, hover_color=theme.COLOR_ENTRY,
            command=self._browse_folder,
        ).pack(side="left", padx=(8, 0))

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select your Unreal Engine project folder")
        if folder:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, folder)

    def _build_field_gdd(self, master):
        self._section_label(master, "Game Design Document")
        row = ctk.CTkFrame(master, fg_color="transparent")
        row.pack(anchor="w", fill="x")
        self._gdd_path_value = self.data.get("gdd_path", "")
        self.gdd_label = ctk.CTkLabel(
            row, text=self._gdd_display(self._gdd_path_value), font=theme.FONT_BODY,
            text_color=theme.COLOR_TEXT_DIM,
        )
        self.gdd_label.pack(side="left")
        ctk.CTkButton(
            row, text="Upload…", width=90, corner_radius=theme.RADIUS,
            fg_color="transparent", border_width=1, border_color=theme.COLOR_BORDER,
            text_color=theme.COLOR_TEXT, hover_color=theme.COLOR_ENTRY,
            command=self._browse_gdd,
        ).pack(side="left", padx=(12, 0))

    @staticmethod
    def _gdd_display(path: str) -> str:
        return f"Attached: {Path(path).name}" if path else "No document attached"

    def _browse_gdd(self):
        file_path = filedialog.askopenfilename(
            title="Select your Game Design Document",
            filetypes=[("PDF or text", "*.pdf *.txt"), ("All files", "*.*")],
        )
        if not file_path:
            return
        try:
            dest_name = "gdd" + Path(file_path).suffix.lower()
            dest_path = BASE_DIR / dest_name
            shutil.copy(file_path, dest_path)
            self._gdd_path_value = f"./{dest_name}"
            self.gdd_label.configure(text=self._gdd_display(self._gdd_path_value))
        except OSError as exc:
            self.gdd_label.configure(text=f"Failed to copy file: {exc}")

    # --- Сохранение ---

    def _collect(self) -> dict:
        self.data["language"] = self._lang_label_to_key.get(self.lang_var.get(), DEFAULT_UI_LANGUAGE)
        self.data["theme"] = self.theme_var.get()
        self.data["ai_provider"] = self._provider_label_to_key.get(self.provider_var.get(), DEFAULT_PROVIDER)
        self.data["gemini_api_key"] = self.key_entry.get().strip()
        self.data["assistant_name"] = self.name_entry.get().strip() or "Pixie"
        self.data["voice_name"] = self.voice_var.get()
        self.data["personality"] = self._personality_label_to_key.get(self.personality_var.get(), DEFAULT_PERSONALITY)
        self.data["project_type"] = self._project_label_to_key.get(self.project_var.get(), DEFAULT_PROJECT_TYPE)
        self.data["ue_project_path"] = self.path_entry.get().strip()
        self.data["gdd_path"] = self._gdd_path_value
        self.data["onboarding_complete"] = True
        return self.data

    def _save(self):
        data = self._collect()
        save_config(data)
        self.saved = True
        self.status_label.configure(text="✓ Saved")
        self.after(1500, lambda: self.status_label.configure(text=""))

    def _on_close(self):
        self.destroy()


def run_onboarding(edit_mode: bool = False) -> dict:
    """Точка входа.

    edit_mode=False (первый запуск, onboarding_complete=False) → полный
    анимированный wizard по шагам (OnboardingWizard).

    edit_mode=True (пользователь уже настроен и открыл "Settings" из
    дашборда) → компактный QuickSettingsWindow со всеми полями на одном
    экране, без повторного прохождения шагов с нуля.
    """
    if edit_mode:
        app = QuickSettingsWindow()
    else:
        app = OnboardingWizard()
    app.mainloop()
    return load_config()


if __name__ == "__main__":
    run_onboarding()
