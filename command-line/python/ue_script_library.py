"""
Локальная библиотека UE Python-скриптов.
Индексирует примеры из движка/проекта без загрузки в промпт.
Пикси ищет по запросу и подгружает только нужный фрагмент.
"""

from __future__ import annotations

import json
import os
import re
import time
from fnmatch import fnmatch
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent
_CONFIG_PATH = _BASE_DIR / "pixie_config.json"
_APP_CONFIG_PATH = _BASE_DIR / "config.json"
_INDEX_PATH = _BASE_DIR / "script_library_index.json"

_SKIP_PARTS = {
    "binaries", "intermediate", "saved", "deriveddatacache",
    "pipinstallutils", "thirdparty", "node_modules", ".venv",
}


def _load_config() -> dict:
    """Собирает эффективный конфиг библиотеки скриптов.

    Приоритет путей движка/проекта:
    1. Явные значения в pixie_config.json (advanced tuning, не трогаем ради совместимости).
    2. Если их нет — авто-строим из config.json: ue_engine_path (Engine\\Plugins) +
       ue_project_path (Content\\Python), чтобы пользователь мог указать СВОЮ
       версию/копию движка без ручной правки pixie_config.json.
    """
    defaults = {
        "engine_version": "5.8",
        "script_library_paths": ["E:\\UE_5.8\\Engine\\Plugins"],
        "script_scan_globs": ["**/Content/Python/**/*.py"],
        "max_index_entries": 180,
        "max_snippet_chars": 3500,
        "local_recipes_dir": "ue58_recipes",
    }

    has_explicit_pixie_config = _CONFIG_PATH.exists()
    if has_explicit_pixie_config:
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                defaults.update(json.load(f))
        except (OSError, json.JSONDecodeError):
            pass

    # Автостроение путей из основного config.json, если pixie_config.json
    # не переопределяет script_library_paths явно.
    if _APP_CONFIG_PATH.exists():
        try:
            with open(_APP_CONFIG_PATH, encoding="utf-8") as f:
                app_cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            app_cfg = {}

        engine_path = (app_cfg.get("ue_engine_path") or "").strip()
        project_path = (app_cfg.get("ue_project_path") or "").strip()

        # Если пользователь ничего не переопределил вручную в pixie_config.json,
        # собираем script_library_paths из config.json.
        pixie_overrides_paths = has_explicit_pixie_config and "script_library_paths" in defaults and defaults["script_library_paths"] != ["E:\\UE_5.8\\Engine\\Plugins"]
        if not pixie_overrides_paths and (engine_path or project_path):
            auto_paths = []
            if engine_path:
                auto_paths.append(str(Path(engine_path) / "Engine" / "Plugins"))
            if project_path:
                auto_paths.append(project_path)
            if auto_paths:
                defaults["script_library_paths"] = auto_paths

    return defaults



def _should_skip(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    return bool(parts & _SKIP_PARTS)


def _extract_summary(text: str) -> str:
    text = text.strip()
    if text.startswith('"""') or text.startswith("'''"):
        end = text.find('"""', 3) if text.startswith('"""') else text.find("'''", 3)
        if end > 0:
            return text[3:end].strip().split("\n")[0][:200]
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") and len(line) > 2:
            return line.lstrip("# ").strip()[:200]
        if line and not line.startswith("import"):
            return line[:200]
    return ""


def _extract_apis(text: str) -> list[str]:
    apis = set()
    for m in re.finditer(r"unreal\.([A-Za-z0-9_]+)", text):
        apis.add(m.group(1))
    for m in re.finditer(r"get_editor_subsystem\(unreal\.([A-Za-z0-9_]+)\)", text):
        apis.add(m.group(1))
    return sorted(apis)[:20]


def _extract_tags(path: Path, text: str) -> list[str]:
    tags = set()
    lower = str(path).lower()
    for kw in (
        "sequencer", "blueprint", "camera", "asset", "material", "mesh",
        "animation", "metahuman", "render", "ingest", "example", "editor",
        "actor", "component", "property", "spawn", "level",
    ):
        if kw in lower or kw in text.lower():
            tags.add(kw)
    if path.name.startswith("example"):
        tags.add("example")
    return sorted(tags)


def _score_entry(entry: dict, query: str) -> int:
    q = query.lower().strip()
    if not q:
        return 0
    score = 0
    blob = " ".join([
        entry.get("title", ""),
        entry.get("summary", ""),
        entry.get("path", ""),
        " ".join(entry.get("tags", [])),
        " ".join(entry.get("apis", [])),
    ]).lower()
    for word in q.split():
        if word in blob:
            score += 10
        if word in entry.get("title", "").lower():
            score += 15
        if any(word in t for t in entry.get("tags", [])):
            score += 8
        if any(word in a.lower() for a in entry.get("apis", [])):
            score += 5
    return score


def _index_file(path: Path, source: str) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if len(text) < 20:
        return None
    rel = str(path)
    return {
        "id": rel,
        "path": rel,
        "source": source,
        "title": path.stem,
        "summary": _extract_summary(text),
        "tags": _extract_tags(path, text),
        "apis": _extract_apis(text),
        "size": len(text),
    }


def _scan_glob(root: Path, pattern: str) -> list[Path]:
    if not root.exists():
        return []
    glob_pattern = pattern.replace("\\", "/")
    if glob_pattern.startswith("**/"):
        suffix = glob_pattern[3:]
        results = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d.lower() not in _SKIP_PARTS]
            if _should_skip(Path(dirpath)):
                continue
            for name in filenames:
                if fnmatch(name.lower(), suffix.split("/")[-1].lower()) or fnmatch(name, suffix.split("/")[-1]):
                    full = Path(dirpath) / name
                    if full.suffix.lower() == ".py" and not _should_skip(full):
                        results.append(full)
        return results
    return [p for p in root.rglob(glob_pattern) if p.is_file() and not _should_skip(p)]


def build_index(force: bool = False) -> str:
    cfg = _load_config()
    if _INDEX_PATH.exists() and not force:
        age = time.time() - _INDEX_PATH.stat().st_mtime
        if age < 7 * 86400:
            with open(_INDEX_PATH, encoding="utf-8") as f:
                data = json.load(f)
            return f"✅ Индекс актуален ({data.get('count', 0)} записей)."

    entries: list[dict] = []
    seen: set[str] = set()

    recipes_dir = _BASE_DIR / cfg.get("local_recipes_dir", "ue58_recipes")
    if recipes_dir.exists():
        for p in sorted(recipes_dir.glob("*")):
            if p.suffix.lower() not in (".py", ".md"):
                continue
            item = _index_file(p, "pixie_recipe")
            if item and item["path"] not in seen:
                seen.add(item["path"])
                entries.append(item)

    for root_str in cfg.get("script_library_paths", []):
        root = Path(root_str)
        if not root.exists():
            continue
        for pattern in cfg.get("script_scan_globs", []):
            for p in _scan_glob(root, pattern):
                if str(p) in seen:
                    continue
                item = _index_file(p, "engine" if "UE_5.8" in str(p) else "project")
                if item:
                    seen.add(item["path"])
                    entries.append(item)

    max_entries = int(cfg.get("max_index_entries", 180))
    entries.sort(key=lambda e: (0 if e["source"] == "pixie_recipe" else 1, e["title"]))
    entries = entries[:max_entries]

    payload = {
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "engine_version": cfg.get("engine_version", "5.8"),
        "count": len(entries),
        "entries": entries,
    }
    with open(_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return f"✅ Индекс построен: {len(entries)} скриптов/recipes."


def _load_index() -> dict:
    if not _INDEX_PATH.exists():
        build_index(force=True)
    with open(_INDEX_PATH, encoding="utf-8") as f:
        return json.load(f)


def search_library(query: str, limit: int = 6) -> str:
    if not query.strip():
        return "❌ Укажи query для поиска (например: camera, blueprint, sequencer)."
    build_index()
    data = _load_index()
    scored = []
    for entry in data.get("entries", []):
        s = _score_entry(entry, query)
        if s > 0:
            scored.append((s, entry))
    scored.sort(key=lambda x: (-x[0], x[1]["title"]))
    results = [e for _, e in scored[: max(1, min(limit, 10))]]
    if not results:
        return f"❌ Ничего не найдено по запросу '{query}'. Попробуй: camera, asset, blueprint, subobject, toolset."
    compact = [{
        "id": r["path"],
        "title": r["title"],
        "source": r["source"],
        "summary": r.get("summary", "")[:120],
        "tags": r.get("tags", [])[:6],
        "apis": r.get("apis", [])[:8],
    } for r in results]
    return f"✅ Найдено {len(compact)}:\n{json.dumps(compact, ensure_ascii=False, indent=2)}"


def load_snippet(script_id: str, max_chars: int | None = None) -> str:
    if not script_id.strip():
        return "❌ Укажи script_id из ue_library_search."
    cfg = _load_config()
    max_chars = max_chars or int(cfg.get("max_snippet_chars", 3500))

    path = Path(script_id.strip())
    if not path.is_absolute():
        path = _BASE_DIR / path
    if not path.exists():
        build_index()
        data = _load_index()
        match = None
        want = script_id.lower()
        for entry in data.get("entries", []):
            if want in entry["path"].lower() or want == entry["title"].lower():
                match = Path(entry["path"])
                break
        if match and match.exists():
            path = match
        else:
            return f"❌ Файл не найден: {script_id}"

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return f"❌ Не удалось прочитать: {exc}"

    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n… (обрезано, всего {len(text)} символов)"
    return f"✅ Snippet `{path.name}`:\n```python\n{text}\n```"


def get_recipes_manifest() -> str:
    """Короткий список локальных recipes для system prompt (без токенов движка)."""
    cfg = _load_config()
    recipes_dir = _BASE_DIR / cfg.get("local_recipes_dir", "ue58_recipes")
    if not recipes_dir.exists():
        return ""
    lines = ["ЛОКАЛЬНЫЕ UE 5.8 RECIPES (полный текст через ue_library_load_snippet):"]
    for p in sorted(recipes_dir.glob("*")):
        if p.suffix.lower() not in (".py", ".md"):
            continue
        summary = ""
        try:
            summary = _extract_summary(p.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            pass
        lines.append(f"- {p.name}: {summary or p.stem}")
    lines.append("Примеры движка E:\\UE_5.8 — только через ue_library_search + ue_library_load_snippet.")
    return "\n".join(lines)


UE58_ERROR_CATALOG = """
ЧАСТЫЕ ОШИБКИ UE 5.8 PYTHON (избегай):
1. EditorActorSubsystem.get_editor_world() — УДАЛЕНО. Используй UnrealEditorSubsystem.get_editor_world().
2. EditorLevelLibrary — устарел, не использовать.
3. get_components_by_class на Blueprint-акторе — часто пусто. Используй SubobjectDataSubsystem (см. ue_list_actor_components).
4. Путь без /Game/ — ассет не найдётся.
5. value как строка вместо числа/Vector/JSON — type error. Vector: "[0,0,200]", Rotator: "[0,90,0]".
6. Ассет открыт в редакторе — save/compile может fail. Закрой или сохрани вручную.
7. Не угадывай имена — сначала ue_list_actors / ue_find_assets / ue_library_search.
"""

