"""
config_loader.py — единая точка загрузки config.json (имя ассистента, голос,
язык, пути, лицензия) + совместимость с Nuitka --onefile/--standalone.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def get_base_dir() -> Path:
    """Папка, где реально лежит .exe (или main.py при разработке).

    ВАЖНО для Nuitka --onefile: __file__ там указывает на временную
    распакованную папку, поэтому в frozen-режиме ориентируемся на
    sys.executable.
    """
    is_frozen = getattr(sys, "frozen", False) or "nuitka" in sys.modules or "__compiled__" in globals()
    if is_frozen:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
CONFIG_PATH = BASE_DIR / "config.json"

DEFAULTS: dict[str, Any] = {
    "gemini_api_key": "",
    "language": "en",
    "assistant_name": "Pixie",
    "voice_name": "Aoede",
    "ue_project_path": "",
    "ue_engine_path": "",
    "ue_recipes_path": "./ue58_recipes",

    "gdd_path": "./gdd.pdf",
    "license_key": "",
    "license_auto_check": True,
    "theme": "dark",
    "telemetry": True,
}


def load_config() -> dict[str, Any]:
    """Загружает config.json, дополняя отсутствующие поля значениями по умолчанию.

    Если файла нет — создаёт его с дефолтами (удобно для первого запуска).
    """
    data: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    merged = {**DEFAULTS, **data}
    if not CONFIG_PATH.exists():
        save_config(merged)
    return merged


def save_config(data: dict[str, Any]) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def update_config(**kwargs: Any) -> dict[str, Any]:
    """Частичное обновление config.json (например, из окна настроек)."""
    data = load_config()
    data.update(kwargs)
    save_config(data)
    return data


def resolve_path(relative_or_absolute: str) -> Path:
    """Резолвит путь из конфига относительно BASE_DIR, если он не абсолютный."""
    p = Path(relative_or_absolute)
    if p.is_absolute():
        return p
    return (BASE_DIR / p).resolve()


if __name__ == "__main__":
    cfg = load_config()
    print(json.dumps(cfg, ensure_ascii=False, indent=2))
