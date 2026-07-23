"""presets.py — общие пресеты для онбординга и системного промпта.

Единый источник правды для голосов Gemini, пресетов характера ассистента,
типов проекта и списка AI-провайдеров (сейчас активен только Gemini,
остальные зарезервированы под будущие релизы — без привязки к подписке).
"""

from __future__ import annotations

# Голоса, доступные в Gemini Live API (prebuilt voice config).
GEMINI_VOICES: list[str] = ["Aoede", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Zephyr"]

PERSONALITY_PRESETS: dict[str, dict[str, str]] = {
    "witty_gamer": {
        "label": "Witty Gamer Buddy",
        "description": "Casual, jokes, zero corporate tone — like a friend who codes with you.",
        "prompt": "witty, casual, gamer-friendly spoken language, zero corporate tone, occasional light humor",
    },
    "professional": {
        "label": "Professional Assistant",
        "description": "Concise, businesslike, no slang — straight answers only.",
        "prompt": "professional, concise, businesslike and polite tone, no slang",
    },
    "calm_focused": {
        "label": "Calm & Focused",
        "description": "Minimal chatter, no jokes, just gets the job done.",
        "prompt": "calm, focused, minimal chatter, straight to the point, no jokes",
    },
    "hype": {
        "label": "Energetic Hype-man",
        "description": "Enthusiastic, celebrates wins, keeps the energy up.",
        "prompt": "energetic, enthusiastic, hype and encouraging tone, celebrates small wins",
    },
}

PROJECT_TYPES: dict[str, dict[str, str]] = {
    "ue_shooter": {
        "label": "Unreal Engine — Shooter",
        "prompt": "The user is developing a shooter game in Unreal Engine 5.8.",
    },
    "ue_platformer": {
        "label": "Unreal Engine — Platformer / Side-scroller",
        "prompt": "The user is developing a platformer / side-scrolling game in Unreal Engine 5.8.",
    },
    "ue_rpg": {
        "label": "Unreal Engine — RPG / Adventure",
        "prompt": "The user is developing an RPG or adventure game in Unreal Engine 5.8.",
    },
    "ue_other": {
        "label": "Unreal Engine — Other genre",
        "prompt": "The user is developing a game in Unreal Engine 5.8 (genre not specified).",
    },
    "no_ue": {
        "label": "Not using Unreal Engine (Windows assistant only)",
        "prompt": "The user is not using Unreal Engine — act purely as a general Windows voice assistant.",
    },
}

AI_PROVIDERS: dict[str, dict[str, object]] = {
    "gemini": {
        "label": "Google Gemini Live",
        "enabled": True,
        "key_help_url": "https://aistudio.google.com/app/apikey",
        "key_help_text": "Open Google AI Studio → \u201cGet API key\u201d → create a key and paste it here.",
    },
    "openai": {
        "label": "OpenAI (coming soon)",
        "enabled": False,
        "key_help_url": "",
        "key_help_text": "",
    },
    "claude": {
        "label": "Anthropic Claude (coming soon)",
        "enabled": False,
        "key_help_url": "",
        "key_help_text": "",
    },
}

DEFAULT_PROVIDER = "gemini"
DEFAULT_PERSONALITY = "witty_gamer"
DEFAULT_PROJECT_TYPE = "ue_shooter"

# Языки интерфейса/общения ассистента — 7 самых популярных языков в мире
# (по числу носителей+изучающих), выбираются на самом первом шаге онбординга.
# code — BCP-47 код, используется как language_code для Gemini Live speech_config.
UI_LANGUAGES: dict[str, dict[str, str]] = {
    "en": {"label": "🇬🇧 English", "code": "en-US"},
    "ru": {"label": "🇷🇺 Русский", "code": "ru-RU"},
    "es": {"label": "🇪🇸 Español", "code": "es-ES"},
    "zh": {"label": "🇨🇳 中文", "code": "cmn-CN"},
    "hi": {"label": "🇮🇳 हिन्दी", "code": "hi-IN"},
    "fr": {"label": "🇫🇷 Français", "code": "fr-FR"},
    "de": {"label": "🇩🇪 Deutsch", "code": "de-DE"},
}

DEFAULT_UI_LANGUAGE = "en"
