"""
Мост к Unreal Engine через Python Remote Execution.
Переиспользует соединение и даёт готовые операции для поиска объектов и правки свойств.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import remote_execution
from ue58_core import PIXIE_COMMON_HELPERS

_DISCOVERY_WAIT = 0.8
_OUTPUT_LIMIT = 8000


class UEBridge:
    """Потокобезопасный клиент Remote Execution с переиспользованием сессии."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._remote: remote_execution.RemoteExecution | None = None
        self._node_id: str | None = None

    def _ensure_connected(self) -> tuple[remote_execution.RemoteExecution, str]:
        if self._remote and self._node_id and self._remote.has_command_connection():
            nodes = self._remote.remote_nodes
            if any(n.get("node_id") == self._node_id for n in nodes):
                return self._remote, self._node_id

        self.disconnect()

        remote = remote_execution.RemoteExecution()
        remote.start()
        deadline = time.time() + 5.0
        nodes: list[dict[str, Any]] = []
        while time.time() < deadline:
            nodes = remote.remote_nodes
            if nodes:
                break
            time.sleep(_DISCOVERY_WAIT)

        if not nodes:
            remote.stop()
            raise RuntimeError(
                "UE5 не обнаружен. Включи Python Remote Execution в настройках проекта "
                "(Edit → Project Settings → Plugins → Python → Enable Remote Execution)."
            )

        node_id = nodes[0]["node_id"]
        remote.open_command_connection(node_id)
        self._remote = remote
        self._node_id = node_id
        return remote, node_id

    def disconnect(self) -> None:
        if not self._remote:
            return
        try:
            self._remote.close_command_connection()
            self._remote.stop()
        except Exception:
            pass
        finally:
            self._remote = None
            self._node_id = None

    def run(self, script_body: str, exec_mode: str | None = None) -> dict[str, Any]:
        wrapped = (
            "import unreal\n"
            "import json\n"
            "import warnings\n"
            "warnings.filterwarnings('ignore')\n"
            f"{PIXIE_COMMON_HELPERS}\n"
            f"{script_body}\n"
        )
        with self._lock:
            remote, _ = self._ensure_connected()
            mode = exec_mode or remote_execution.MODE_EXEC_FILE
            try:
                data = remote.run_command(wrapped, unattended=True, exec_mode=mode)
            except Exception:
                # РЕАЛЬНАЯ ошибка транспорта (сокет/протокол) — тут действительно
                # нужно порвать и переоткрыть TCP-соединение.
                self.disconnect()
                remote, _ = self._ensure_connected()
                data = remote.run_command(wrapped, unattended=True, exec_mode=mode)

            # ИСПРАВЛЕНО: раньше здесь было `if not data.get("success", False): self.disconnect()`.
            # Это была ГЛАВНАЯ причина симптома "после ошибки текстурирования агент теряет
            # возможность работать с UE, помогает только перезапуск":
            # ЛЮБАЯ обычная ошибка Python-скрипта внутри UE (например AttributeError в
            # execute_unreal_python) возвращается сервером как success=False, но TCP-канал
            # при этом абсолютно исправен. Разрыв соединения на этот случай заставлял
            # каждый следующий вызов заново: убить старый listen-socket на 127.0.0.1:6776,
            # заново забиндить его и подождать (до 5с) UDP-дискавери ноды UE. Из-за таймингов
            # Windows (TIME_WAIT/повторный bind) новые попытки могли не успевать законнектиться
            # раньше следующего вызова инструмента — соединение "залипало" в плохом состоянии,
            # и помогал только полный перезапуск процесса (который освобождает сокет через ОС).
            # Теперь разрыв соединения происходит ТОЛЬКО при настоящей ошибке транспорта
            # (см. except выше), а обычные ошибки скрипта в UE просто возвращаются как текст
            # ошибки без разрушения рабочего соединения.
            return data

    def run_and_format(self, script_body: str, exec_mode: str | None = None) -> str:
        try:
            data = self.run(script_body, exec_mode=exec_mode)
        except Exception as exc:
            return f"❌ Ошибка UE5: {exc}"

        if not data.get("success", True):
            err = data.get("result") or data.get("output") or "неизвестная ошибка"
            return f"❌ Скрипт в UE5 завершился с ошибкой:\n{str(err)[:_OUTPUT_LIMIT]}"

        text = _normalize_ue_output(data.get("output") if data.get("output") is not None else data.get("result", "OK"))
        if not text:
            text = "OK (без вывода)"

        payload_error = _payload_error_from_text(text)
        if payload_error:
            return f"❌ UE5: {payload_error[:_OUTPUT_LIMIT]}"

        if len(text) > _OUTPUT_LIMIT:
            text = text[:_OUTPUT_LIMIT] + "\n… (вывод обрезан)"
        return f"✅ UE5:\n{text}"


_bridge = UEBridge()


def _normalize_ue_output(raw: Any) -> str:
    """Извлекает текстовый вывод из ответа Remote Execution (list/dict/str)."""
    if raw is None:
        return ""
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                parts.append(str(item.get("output", item)))
            else:
                parts.append(str(item))
        return "\n".join(parts).strip()
    return str(raw).strip()


def _payload_error_from_text(text: str) -> str | None:
    """Возвращает текст ошибки, если JSON-ответ скрипта содержит поле error."""
    for candidate in (text, *text.splitlines()):
        candidate = candidate.strip()
        if not candidate.startswith("{"):
            continue
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, dict) and obj.get("error"):
            return str(obj["error"])
    return None


def get_bridge() -> UEBridge:
    return _bridge


# ---------- БЕЗОПАСНАЯ ПОДСТАНОВКА АРГУМЕНТОВ ----------
# Исправление корневого бага: вместо script.format(...) в main.py (который
# падает с KeyError/SyntaxError на аргументах со скобками/кавычками),
# подставляем значения как валидные Python-литералы через repr().
# Это иммунно к содержимому аргументов (повторяет подход ue_tools._prepare_script).

def _py_literal(value: Any) -> str:
    """Преобразует значение в валидный Python-литерал для вставки в UE-скрипт."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        items = ", ".join(_py_literal(v) for v in value)
        return f"[{items}]"
    if isinstance(value, dict):
        items = ", ".join(f"{_py_literal(k)}: {_py_literal(v)}" for k, v in value.items())
        return f"{{{items}}}"
    return repr(value)


def run_with_args(template: str, **bindings: Any) -> str:
    """Подставляет именованные аргументы в шаблон БЕЗ .format().

    Шаблоны объявляют переменные с теми же именами, что и ключи bindings
    (query, class_filter, identifiers, identifier, ...). Значения превращаются
    в корректные Python-литералы, поэтому любой текст от модели
    (с кавычками/скобками) не сломает синтаксис.

    Аналог _prepare_script() из ue_tools.py — унифицирует подход.
    """
    header_lines = []
    for name, value in bindings.items():
        header_lines.append(f"{name} = {_py_literal(value)}")
    header = "\n".join(header_lines)
    script = f"{header}\n{template}" if header else template
    return _bridge.run_and_format(script)


# ---------- Встроенные скрипты для типовых задач ----------
# ВАЖНО: шаблоны НЕ используют .format() для подстановки данных.
# Значения переменных (query, class_filter, identifiers, identifier, ...)
# задаются через run_with_args() как обычные Python-переменные.
# Убрано экранирование {{ / }} и суффиксы !r — всё работает через
# безопасные литералы из _py_literal().

def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


LIST_ACTORS_SCRIPT = r"""
def _actor_row(actor):
    try:
        label = _safe_label(actor)
    except Exception:
        label = ""
    loc = actor.get_actor_location()
    return {
        "name": actor.get_name(),
        "label": label,
        "class": actor.get_class().get_name() if actor.get_class() else "",
        "location": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)],
    }

subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = subsystem.get_all_level_actors()
_query = (query or "").lower().strip()
_class_filter = (class_filter or "").lower().strip()
_limit = int(limit)

rows = []
for actor in actors:
    row = _actor_row(actor)
    if _class_filter and _class_filter not in row["class"].lower():
        continue
    if _query:
        hay = " ".join([row["name"], row["label"], row["class"]]).lower()
        if _query not in hay:
            continue
    rows.append(row)
    if len(rows) >= _limit:
        break

_output({"count": len(rows), "total_in_level": len(actors), "actors": rows})
"""

FIND_ACTORS_SCRIPT = r"""
def _match(actor, name_part, label_part, class_part):
    name = actor.get_name().lower()
    try:
        label = actor.get_actor_label().lower()
    except Exception:
        label = ""
    cls = actor.get_class().get_name().lower() if actor.get_class() else ""
    if name_part and name_part not in name and name_part not in label:
        return False
    if label_part and label_part not in label and label_part not in name:
        return False
    if class_part and class_part not in cls:
        return False
    return True

subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
matches = []
for actor in subsystem.get_all_level_actors():
    if _match(actor, (name_part or "").lower(), (label_part or "").lower(), (class_part or "").lower()):
        loc = actor.get_actor_location()
        matches.append({
            "name": actor.get_name(),
            "label": _safe_label(actor),
            "class": actor.get_class().get_name(),
            "location": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)],
        })

_output({"matches": matches, "count": len(matches)})
"""

GET_ACTOR_INFO_SCRIPT = r"""
actor = _find_actor(identifier)
if not actor:
    _output({"error": "Актор не найден", "identifier": identifier})
else:
    props = {}
    for prop in (properties or []):
        try:
            props[prop] = _serialize(actor.get_editor_property(_normalize_prop_name(prop)))
        except Exception as exc:
            props[prop] = f"<ошибка: {exc}>"

    loc = actor.get_actor_location()
    rot = actor.get_actor_rotation()
    scl = actor.get_actor_scale3d()
    info = {
        "name": actor.get_name(),
        "label": _safe_label(actor),
        "class": actor.get_class().get_name(),
        "location": [round(loc.x, 2), round(loc.y, 2), round(loc.z, 2)],
        "rotation": [round(rot.pitch, 2), round(rot.yaw, 2), round(rot.roll, 2)],
        "scale": [round(scl.x, 2), round(scl.y, 2), round(scl.z, 2)],
        "properties": props,
    }
    _output(info)
"""

SELECT_ACTORS_SCRIPT = r"""
def _find(identifier):
    ident = (identifier or "").lower().strip()
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in subsystem.get_all_level_actors():
        name = actor.get_name().lower()
        try:
            label = actor.get_actor_label().lower()
        except Exception:
            label = ""
        if ident == name or ident == label or ident in name or ident in label:
            return actor
    return None

targets = []
missing = []
for ident in (identifiers or []):
    actor = _find(ident)
    if actor:
        targets.append(actor)
    else:
        missing.append(ident)

subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
subsystem.set_selected_level_actors(targets)

_output({
    "selected": [a.get_name() for a in targets],
    "missing": missing,
    "count": len(targets),
})
"""

FOCUS_ACTORS_SCRIPT = r"""
def _find(identifier):
    ident = (identifier or "").lower().strip()
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in subsystem.get_all_level_actors():
        name = actor.get_name().lower()
        try:
            label = actor.get_actor_label().lower()
        except Exception:
            label = ""
        if ident == name or ident == label or ident in name or ident in label:
            return actor
    return None

targets = []
for ident in (identifiers or []):
    actor = _find(ident)
    if actor:
        targets.append(actor)

if not targets:
    _output({"error": "Ни один актор не найден", "requested": list(identifiers or [])})
else:
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    subsystem.set_selected_level_actors(targets)
    world = _get_editor_world()
    if world:
        unreal.SystemLibrary.execute_console_command(world, "FOCUS SELECTED")
    _output({
        "focused": [a.get_name() for a in targets],
        "count": len(targets),
    })
"""

SET_PROPERTY_SCRIPT = r"""
_COMPONENT_PROPS = {
    "relative_location", "relative_rotation", "field_of_view",
    "target_arm_length", "relative_scale3d",
}
_CAMERA_PROPS = {
    "relative_location", "relative_rotation", "field_of_view", "target_arm_length",
}

def _try_set(obj, obj_name, prop_name, val):
    try:
        norm_prop = _normalize_prop_name(prop_name)
        values_json = json.dumps({norm_prop: _parse_value(val)}, ensure_ascii=False)
        if _toolset_set_properties(obj, values_json):
            new_val = obj.get_editor_property(norm_prop)
        else:
            new_val = _apply_property(obj, norm_prop, val)
        return {"ok": True, "target": obj_name, "value": _serialize(new_val)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def _sort_components(comp_list, camera_only=False):
    def _priority(item):
        comp = item[0]
        if isinstance(comp, unreal.CameraComponent):
            return 0
        if isinstance(comp, unreal.SpringArmComponent):
            return 1
        if isinstance(comp, unreal.MeshComponent):
            return 2
        return 3

    items = comp_list
    if camera_only:
        items = [
            (comp, display)
            for comp, display in comp_list
            if isinstance(comp, (unreal.CameraComponent, unreal.SpringArmComponent))
        ]
    return sorted(items, key=_priority)

_actor_ident, _component_hint = _split_actor_identifier(identifier)

actor = _find_actor(_actor_ident)
if not actor:
    _output({"error": "Актор не найден", "identifier": identifier})
else:
    _component_class = (component_class or "").strip()
    prop = _normalize_prop_name((property_name or "").strip())
    target = actor
    target_display = actor.get_name()
    result = {"ok": False, "error": "не выполнено"}

    routed = False
    if _component_hint:
        comp, display = _find_component(actor, _component_hint)
        if comp:
            target = comp
            target_display = display or comp.get_name()
            routed = True
        else:
            _output({
                "error": f"Компонент '{_component_hint}' не найден на актере {actor.get_name()}",
                "identifier": identifier,
            })

    elif _component_class:
        cls = getattr(unreal, _component_class, None)
        comp, display = _find_component(actor, "", cls)
        if comp:
            target = comp
            target_display = display or comp.get_name()
            routed = True
        else:
            _output({
                "error": f"Компонент {_component_class} не найден на актере {actor.get_name()}",
            })

    if routed or ((not _component_hint and not _component_class) or target != actor):
        prop_key = prop.lower()
        camera_only = prop_key in _CAMERA_PROPS

        if target == actor and prop_key in _COMPONENT_PROPS:
            result = {"ok": False}
            for comp, display in _sort_components(_list_components(actor), camera_only=camera_only):
                result2 = _try_set(comp, display or comp.get_name(), prop, value)
                if result2["ok"]:
                    result = result2
                    result["auto_routed"] = True
                    break
            if not result["ok"] and not camera_only:
                result = _try_set(target, target_display, prop, value)
            elif not result["ok"]:
                result = {
                    "ok": False,
                    "error": "Свойство камеры не найдено на Camera/SpringArm компонентах",
                }
        else:
            result = _try_set(target, target_display, prop, value)
            if not result["ok"] and target == actor:
                for comp, display in _sort_components(_list_components(actor)):
                    result2 = _try_set(comp, display or comp.get_name(), prop, value)
                    if result2["ok"]:
                        result = result2
                        result["auto_routed"] = True
                        break

        if result["ok"]:
            _output({
                "actor": actor.get_name(),
                "target": result["target"],
                "property": prop,
                "value": result["value"],
                "auto_routed": result.get("auto_routed", False),
            })
        else:
            _output({
                "error": f"Не удалось установить {prop} на {actor.get_name()}: {result.get('error')}",
            })
"""

GET_SELECTION_SCRIPT = r"""
subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
selected = subsystem.get_selected_level_actors() or []
rows = []
for actor in selected:
    loc = actor.get_actor_location()
    rows.append({
        "name": actor.get_name(),
        "label": _safe_label(actor),
        "class": actor.get_class().get_name(),
        "location": [round(loc.x, 1), round(loc.y, 1), round(loc.z, 1)],
    })
_output({"selected": rows, "count": len(rows)})
"""

COMMON_ACTOR_PROPERTIES = [
    "bHidden",
    "bIsEditorOnlyActor",
    "ActorLabel",
    "FolderPath",
    "Tags",
]
