"""Расширенные UE-инструменты: проект, ассеты, Blueprint, камера (UE 5.8)."""

from __future__ import annotations

import json

from ue_bridge import get_bridge
import licensing


GET_PROJECT_CONTEXT_SCRIPT = """
world = _get_editor_world()
try:
    engine_version = unreal.SystemLibrary.get_engine_version()
except Exception:
    engine_version = "unknown"
project_file = unreal.Paths.get_project_file_path()
project_name = unreal.Paths.get_base_filename(project_file) if project_file else ""

project_dir = unreal.SystemLibrary.get_project_directory()
content_dir = unreal.Paths.project_content_dir()

map_path = ""
map_name = ""
les = _les()
if les:
    try:
        level = les.get_current_level()
        if level:
            map_path = level.get_path_name()
            map_name = level.get_name()
    except Exception:
        pass
if not map_name and world:
    map_name = world.get_name()

game_mode_class = ""
default_pawn = ""
if world:
    ws = world.get_world_settings()
    if ws:
        try:
            gm = ws.get_editor_property("default_game_mode")
            if gm:
                game_mode_class = gm.get_path_name()
                gm_cdo = unreal.get_default_object(gm)
                pawn = gm_cdo.get_editor_property("default_pawn_class")
                if pawn:
                    default_pawn = pawn.get_path_name()
        except Exception:
            pass

selected = _eas().get_selected_level_actors()
sel_rows = [{"name": a.get_name(), "label": _safe_label(a)} for a in selected[:8]]

_output({
    "engine": "UE5.8",
    "engine_version": engine_version,
    "project_name": project_name,

    "project_file": project_file,
    "project_dir": project_dir,
    "content_dir": content_dir,
    "current_map_name": map_name,
    "current_map_path": map_path,
    "default_game_mode": game_mode_class,
    "default_pawn_class": default_pawn,
    "selected_actors": sel_rows,
    "content_root": "/Game",
})
"""

LIST_ASSETS_SCRIPT = """
folder = _normalize_game_path(folder_path) or "/Game"
query = query.lower().strip()
class_filter = class_filter.lower().strip()
recursive = recursive
limit = limit

paths = unreal.EditorAssetLibrary.list_assets(folder, recursive)
rows = []
for path in paths:
    if query and query not in path.lower():
        continue
    asset = unreal.EditorAssetLibrary.load_asset(path)
    if not asset:
        continue
    cls = asset.get_class().get_name() if asset.get_class() else ""
    if class_filter and class_filter not in cls.lower():
        continue
    rows.append({"path": path, "name": path.split("/")[-1], "class": cls})
    if len(rows) >= limit:
        break

_output({"folder": folder, "count": len(rows), "assets": rows})
"""

FIND_ASSETS_SCRIPT = r"""
query = (query or "").lower().strip()
class_filter = (class_filter or "").lower().strip()
_limit = int(limit)

if not query:
    _output({"error": "query обязателен"})
else:
    rows = []
    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        filter_data = unreal.ARFilter(
            recursive_paths=True,
            package_paths=[unreal.Name("/Game")],
        )
        assets = registry.get_assets(filter_data)
        for data in assets:
            name = ""
            pkg = ""
            obj_path = ""
            cls = ""

            if hasattr(data, "asset_name"):
                name = str(data.asset_name).lower()
            if hasattr(data, "package_name"):
                pkg = str(data.package_name).lower()
            if hasattr(data, "object_path"):
                obj_path = str(data.object_path)
            elif hasattr(data, "package_name"):
                obj_path = str(data.package_name)
            if hasattr(data, "asset_class"):
                ac = data.asset_class
                if ac is not None:
                    cls = str(ac).lower()
            elif hasattr(data, "asset_class_path"):
                acp = data.asset_class_path
                if acp is not None:
                    acp_str = str(acp).lower()
                    cls = acp_str.split(".")[-1].split("/")[-1] if "." in acp_str or "/" in acp_str else acp_str

            if query not in name and query not in pkg:
                continue
            if class_filter and class_filter not in cls:
                continue

            rows.append({"path": obj_path, "name": name, "class": cls})
            if len(rows) >= _limit:
                break
    except Exception:
        paths = unreal.EditorAssetLibrary.list_assets("/Game", True)
        for path in paths:
            if query and query not in path.lower():
                continue
            asset = unreal.EditorAssetLibrary.load_asset(path)
            if not asset:
                continue
            cls = ""
            try:
                cls = asset.get_class().get_name() if asset.get_class() else ""
            except Exception:
                cls = ""
            if class_filter and class_filter not in cls.lower():
                continue
            rows.append({"path": path, "name": path.split("/")[-1], "class": cls})
            if len(rows) >= _limit:
                break

    _output({"query": query, "count": len(rows), "assets": rows})
"""

LIST_ACTOR_COMPONENTS_SCRIPT = r"""
actor = _find_actor(identifier)
if not actor:
    _output({"error": "Актор не найден", "identifier": identifier})
else:
    rows = [_component_snapshot(comp, display) for comp, display in _list_components(actor)]
    bp_path = _resolve_blueprint_path(actor)
    _output({
        "actor": actor.get_name(),
        "label": _safe_label(actor),
        "class": actor.get_class().get_name(),
        "blueprint_path": bp_path,
        "components": rows,
        "hint": "Для правки камеры используй ue_configure_camera с apply_to=both",
    })
"""

GET_BLUEPRINT_INFO_SCRIPT = r"""
bp = _load_blueprint(blueprint_path)
if not bp:
    _output({"error": "Blueprint не найден", "path": blueprint_path})
else:
    rows = []
    cdo = _get_blueprint_cdo(bp)
    if cdo:
        for comp, display in _list_components(cdo, blueprint=bp):
            snap = _component_snapshot(comp, display)
            snap["source"] = "blueprint_cdo"
            rows.append(snap)

    class_props = {}
    if cdo:
        for prop in (class_properties or []):
            try:
                class_props[prop] = _serialize(cdo.get_editor_property(prop))
            except Exception as exc:
                class_props[prop] = f"<ошибка: {exc}>"

    parent_cls = ""
    try:
        p = bp.get_blueprint_parent_class()
        if p:
            parent_cls = p.get_name()
    except Exception:
        parent_cls = "(недоступно)"

    _output({
        "path": _normalize_game_path(blueprint_path),
        "name": bp.get_name(),
        "parent_class": parent_cls,
        "components": rows,
        "class_default_properties": class_props,
        "note": "SCS nodes not accessible via Python in this UE5.8 build; using CDO components",
    })
"""

SET_BLUEPRINT_PROPERTY_SCRIPT = r"""
bp = _load_blueprint(blueprint_path)
if not bp:
    _output({"error": "Blueprint не найден", "path": blueprint_path})
else:
    _component_name = (component_name or "").strip()
    _property_name = (property_name or "").strip()
    target = None
    matched = None

    if _component_name:
        cdo = _get_blueprint_cdo(bp)
        if cdo:
            comp, display = _find_component(cdo, _component_name)
            if comp:
                target = comp
                matched = display
    else:
        target = _get_blueprint_cdo(bp)
        matched = "ClassDefaults"

    if not target:
        _output({"error": "Компонент или ClassDefaults не найдены", "component_name": component_name})
    else:
        prop = _property_name if _property_name else ""
        values_json = json.dumps({prop: _parse_value(value)}, ensure_ascii=False)
        used_toolset = _toolset_set_properties(target, values_json)
        if not used_toolset:
            new_val = _apply_property(target, prop, value)
        else:
            new_val = target.get_editor_property(prop)
        _compile_and_save_blueprint(bp)
        _output({
            "blueprint": bp.get_name(),
            "target": matched,
            "property": _property_name,
            "value": _serialize(new_val),
            "saved": True,
        })
"""

CONFIGURE_CAMERA_SCRIPT = r"""
target = (target or "").strip()
mode = (mode or "").strip().lower() or "custom"
apply_to = (apply_to or "").strip().lower() or "both"
_arm_length = arm_length
_camera_pitch = camera_pitch
_camera_yaw = camera_yaw

if mode == "fix_horizon" and _camera_pitch is None:
    _camera_pitch = 0.0

result = {"target": target, "mode": mode, "apply_to": apply_to, "changes": []}
errors = []
is_asset = target.startswith("/Game") or target.startswith("Game/")

if apply_to in ("instance", "both") and not is_asset:
    actor = _find_actor(target)
    if actor:
        result["actor"] = actor.get_name()
        result["blueprint_path"] = _resolve_blueprint_path(actor)
        result["changes"].extend(_configure_camera_on_owner(actor, mode, _arm_length, _camera_pitch, _camera_yaw))
        try:
            actor.modify()
        except Exception:
            pass
    else:
        errors.append(f"Актор '{target}' не найден на уровне")

bp_path = _normalize_game_path(target) if is_asset else _resolve_blueprint_path_from_target(target)
if apply_to in ("blueprint", "both") and bp_path:
    bp = _load_blueprint(bp_path)
    if bp:
        bp_changes, bp_err = _configure_blueprint_camera(bp, mode, _arm_length, _camera_pitch, _camera_yaw)
        result["blueprint_path"] = bp_path
        result["changes"].extend(bp_changes)
        if bp_err:
            errors.append(bp_err)
    else:
        errors.append(f"Blueprint не найден: {bp_path}")

if mode == "fix_horizon":
    result["note"] = "fix_horizon: camera pitch=0 (горизонт)"

if errors:
    result["errors"] = errors
if not result["changes"] and errors:
    result["error"] = "; ".join(errors)

_output(result)
"""

COMPILE_BLUEPRINT_SCRIPT = r"""
bp = _load_blueprint(blueprint_path)
if not bp:
    _output({"error": "Blueprint не найден", "path": blueprint_path})
else:
    _compile_and_save_blueprint(bp)
    _output({"compiled": True, "path": _normalize_game_path(blueprint_path), "name": bp.get_name()})
"""

OPEN_ASSET_SCRIPT = r"""
path = _normalize_game_path(asset_path)
if not path:
    _output({"error": "asset_path пуст"})
else:
    asset = _load_asset(path)
    if asset is None:
        _output({"error": f"Ассет не загружен: {path}"})
    else:
        opened = False
        note = ""
        try:
            if hasattr(unreal, "AssetEditorSubsystem"):
                aes = unreal.get_editor_subsystem(unreal.AssetEditorSubsystem)
                if aes and hasattr(aes, "open_editor_for_assets"):
                    aes.open_editor_for_assets([asset])
                    opened = True
        except Exception as exc:
            note = f"AssetEditorSubsystem: {exc}"
        if not opened:
            try:
                if hasattr(unreal.EditorAssetLibrary, "open_editor_for_assets"):
                    unreal.EditorAssetLibrary.open_editor_for_assets([asset])
                    opened = True
            except Exception as exc:
                note = (note + "; " if note else "") + f"EditorAssetLibrary: {exc}"
        _output({
            "opened": opened,
            "loaded": True,
            "path": path,
            "note": note or ("opened in editor" if opened else "asset loaded; open Content Browser manually if editor did not open"),
        })
"""

RUN_CONSOLE_SCRIPT = """
world = _get_active_world()
cmd = command.strip()
if not cmd:
    _output({"error": "command пуст"})
else:
    if not world:
        _output({"error": "Мир не найден. Убедись, что UE запущен и Remote Execution доступен."})
    elif cmd.lower().strip().startswith(("open", "changelevel", "servertravel", "map", "travel", "quit", "exit", "restart", "stat")):
        _output({"error": "Команда консоли слишком опасна для ue_run_console. Используй безопасные ue_* инструменты."})
    else:
        try:
            unreal.SystemLibrary.execute_console_command(world, cmd)
            _output({"executed": cmd, "world": world.get_name()})
        except Exception as exc:
            _output({"error": f"Ошибка исполнения команды: {exc}"})
"""

SET_COMPONENT_PROPERTY_SCRIPT = r"""
_actor_ident, _comp_hint = _split_actor_identifier(identifier)
_comp_name = (component_name or "").strip() or _comp_hint
actor = _find_actor(_actor_ident)
if not actor:
    _output({"error": "Актор не найден", "identifier": identifier})
else:
    _cls_name = (component_class or "").strip()
    cls = getattr(unreal, _cls_name, None) if _cls_name else None
    target, display = _find_component(actor, _comp_name, cls)
    if not target:
        _output({
            "error": "Компонент не найден",
            "identifier": identifier,
            "component_name": _comp_name or component_name,
            "component_class": component_class,
        })
    else:
        prop = _normalize_prop_name((property_name or "").strip())
        values_json = json.dumps({prop: _parse_value(value)}, ensure_ascii=False)
        if not _toolset_set_properties(target, values_json):
            new_val = _apply_property(target, prop, value)
        else:
            new_val = target.get_editor_property(prop)
        _output({
            "actor": actor.get_name(),
            "component": display,
            "class": target.get_class().get_name(),
            "property": prop,
            "value": _serialize(new_val),
        })
"""

INSPECT_OBJECT_SCRIPT = r"""
target = (target or "").strip()
_properties = [p.strip() for p in (properties or "").split(",") if p.strip()]
_component_name = (component_name or "").strip()
_actor_ident, _comp_hint = _split_actor_identifier(target)
if not _component_name and _comp_hint:
    _component_name = _comp_hint

if target.startswith("/Game") or target.startswith("Game/"):
    asset = _load_asset(target)
    if not asset:
        _output({"error": "Ассет не найден", "target": target})
    else:
        obj = asset
        if isinstance(asset, unreal.Blueprint):
            obj = _get_blueprint_cdo(asset) or asset
        if _component_name and isinstance(obj, unreal.Actor):
            comp, display = _find_component(obj, _component_name)
            if comp:
                obj = comp
        rows = _toolset_get_properties(obj, _properties)
        _output({"type": "asset", "path": _normalize_game_path(target), "properties": rows})
else:
    actor = _find_actor(_actor_ident or target)
    if not actor:
        _output({"error": "Объект не найден", "target": target})
    else:
        obj = actor
        comp_display = None
        if _component_name:
            comp, comp_display = _find_component(actor, _component_name)
            if comp:
                obj = comp
        rows = _toolset_get_properties(obj, _properties)
        _output({
            "type": "actor",
            "name": actor.get_name(),
            "blueprint_path": _resolve_blueprint_path(actor),
            "component": comp_display,
            "properties": rows,
        })
"""


SPAWN_ACTOR_SCRIPT = r"""
_class_path = (class_path or "").strip()
if not _class_path:
    _output({"error": "class_path обязателен, например StaticMeshActor, PointLight, /Game/Blueprints/BP_Enemy"})
else:
    actor_class = None
    if _class_path.startswith("/Game") or _class_path.startswith("Game/"):
        loaded = unreal.EditorAssetLibrary.load_asset(_normalize_game_path(_class_path))
        if loaded and isinstance(loaded, unreal.Blueprint):
            actor_class = loaded.generated_class()
        elif loaded:
            actor_class = loaded.get_class()
    else:
        actor_class = getattr(unreal, _class_path, None)

    if not actor_class:
        _output({"error": f"Класс/Blueprint не найден: {_class_path}"})
    else:
        loc = _parse_value(location) if location else None
        rot = _parse_value(rotation) if rotation else None
        new_loc = unreal.Vector(*[float(v) for v in loc]) if isinstance(loc, (list, tuple)) and len(loc) == 3 else unreal.Vector(0.0, 0.0, 0.0)
        new_rot = unreal.Rotator(*[float(v) for v in rot]) if isinstance(rot, (list, tuple)) and len(rot) == 3 else unreal.Rotator(0.0, 0.0, 0.0)
        subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        actor = subsystem.spawn_actor_from_class(actor_class, new_loc, new_rot)
        if not actor:
            _output({"error": f"Не удалось создать актора класса {_class_path}"})
        else:
            if label:
                try:
                    actor.set_actor_label(label)
                except Exception:
                    pass
            _output({
                "spawned": True,
                "name": actor.get_name(),
                "label": _safe_label(actor),
                "class": actor.get_class().get_name(),
                "location": [round(new_loc.x, 2), round(new_loc.y, 2), round(new_loc.z, 2)],
            })
"""

DELETE_ACTOR_SCRIPT = r"""
actor = _find_actor(identifier)
if not actor:
    _output({"error": "Актор не найден", "identifier": identifier})
else:
    name = actor.get_name()
    label = _safe_label(actor)
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    ok = subsystem.destroy_actor(actor)
    _output({"deleted": bool(ok), "name": name, "label": label})
"""

DUPLICATE_ACTOR_SCRIPT = r"""
actor = _find_actor(identifier)
if not actor:
    _output({"error": "Актор не найден", "identifier": identifier})
else:
    off = _parse_value(offset) if offset else None
    off_vec = unreal.Vector(*[float(v) for v in off]) if isinstance(off, (list, tuple)) and len(off) == 3 else unreal.Vector(100.0, 0.0, 0.0)
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    dup = subsystem.duplicate_actor(actor, None, off_vec)
    if not dup:
        _output({"error": "Не удалось дублировать актора", "identifier": identifier})
    else:
        if label:
            try:
                dup.set_actor_label(label)
            except Exception:
                pass
        loc = dup.get_actor_location()
        _output({
            "duplicated": True,
            "source": actor.get_name(),
            "name": dup.get_name(),
            "label": _safe_label(dup),
            "location": [round(loc.x, 2), round(loc.y, 2), round(loc.z, 2)],
        })
"""

SAVE_LEVEL_SCRIPT = r"""
les = _les()
if not les:
    _output({"error": "LevelEditorSubsystem не найден"})
else:
    try:
        if save_all:
            les.save_all_dirty_levels()
            _output({"saved_all": True})
        else:
            ok = les.save_current_level()
            _output({"saved_current_level": bool(ok)})
    except Exception as exc:
        _output({"error": f"Ошибка сохранения: {exc}"})
"""

PLAY_IN_EDITOR_SCRIPT = r"""
les = _les()
if not les:
    _output({"error": "LevelEditorSubsystem не найден"})
else:
    try:
        if les.is_in_play_in_editor():
            _output({"already_playing": True})
        else:
            les.editor_request_begin_play()
            _output({"play_requested": True})
    except Exception as exc:
        _output({"error": f"Ошибка запуска Play In Editor: {exc}"})
"""

STOP_PLAY_SCRIPT = r"""
les = _les()
if not les:
    _output({"error": "LevelEditorSubsystem не найден"})
else:
    try:
        if not les.is_in_play_in_editor():
            _output({"not_playing": True})
        else:
            les.editor_request_end_play()
            _output({"stop_requested": True})
    except Exception as exc:
        _output({"error": f"Ошибка остановки Play In Editor: {exc}"})
"""

SET_ACTOR_LABEL_SCRIPT = r"""
actor = _find_actor(identifier)
if not actor:
    _output({"error": "Актор не найден", "identifier": identifier})
else:
    old_label = _safe_label(actor)
    try:
        actor.set_actor_label(new_label)
        _output({"renamed": True, "old_label": old_label, "new_label": _safe_label(actor), "name": actor.get_name()})
    except Exception as exc:
        _output({"error": f"Не удалось переименовать: {exc}"})
"""

ATTACH_ACTOR_SCRIPT = r"""
child = _find_actor(child_identifier)
parent = _find_actor(parent_identifier)
if not child:
    _output({"error": "Дочерний актор не найден", "identifier": child_identifier})
elif not parent:
    _output({"error": "Родительский актор не найден", "identifier": parent_identifier})
else:
    try:
        socket = socket_name.strip() if socket_name else ""
        child.attach_to_actor(
            parent,
            socket,
            unreal.AttachmentRule.KEEP_WORLD,
            unreal.AttachmentRule.KEEP_WORLD,
            unreal.AttachmentRule.KEEP_WORLD,
            False,
        )

        _output({
            "attached": True,
            "child": child.get_name(),
            "parent": parent.get_name(),
            "socket": socket or None,
        })
    except Exception as exc:
        _output({"error": f"Не удалось прикрепить: {exc}"})
"""


def _python_literal(value):

    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        items = ", ".join(_python_literal(v) for v in value)
        return f"[{items}]"
    if isinstance(value, dict):
        items = ", ".join(
            f"{_python_literal(k)}: {_python_literal(v)}" for k, v in value.items()
        )
        return f"{{{items}}}"
    return repr(value)


def _prepare_script(script: str, args: dict) -> str:
    bindings = "\n".join(
        f"{name} = {_python_literal(value)}" for name, value in args.items()
    )
    return f"{bindings}\n{script}" if bindings else script


def _run(script: str, **kwargs) -> str:
    prepared = _prepare_script(script, kwargs)
    return get_bridge().run_and_format(prepared)


@licensing.requires_pro("UE tools")
def ue_get_project_context() -> str:
    return _run(GET_PROJECT_CONTEXT_SCRIPT)


@licensing.requires_pro("UE asset tools")
def ue_list_assets(folder_path: str = "/Game", query: str = "", class_filter: str = "", recursive: bool = True, limit: int = 60) -> str:

    return _run(
        LIST_ASSETS_SCRIPT,
        folder_path=folder_path,
        query=query,
        class_filter=class_filter,
        recursive=recursive,
        limit=max(1, min(limit, 200)),
    )


@licensing.requires_pro("UE asset tools")
def ue_find_assets(query: str, class_filter: str = "", limit: int = 40) -> str:

    if not query.strip():
        return "❌ query обязателен для поиска ассетов."
    return _run(
        FIND_ASSETS_SCRIPT,
        query=query.strip(),
        class_filter=class_filter,
        limit=max(1, min(limit, 100)),
    )


@licensing.requires_pro("UE actor tools")
def ue_list_actor_components(identifier: str) -> str:
    if not identifier.strip():
        return "❌ Укажи identifier актора."
    return _run(LIST_ACTOR_COMPONENTS_SCRIPT, identifier=identifier.strip())


@licensing.requires_pro("UE Blueprint tools")
def ue_get_blueprint_info(blueprint_path: str, class_properties: str = "") -> str:
    if not blueprint_path.strip():
        return "❌ Укажи blueprint_path, например /Game/Blueprints/BP_Character."
    props = [p.strip() for p in class_properties.split(",") if p.strip()] if class_properties else []
    return _run(GET_BLUEPRINT_INFO_SCRIPT, blueprint_path=blueprint_path.strip(), class_properties=props)


@licensing.requires_pro("UE Blueprint tools")
def ue_set_blueprint_property(blueprint_path: str, property_name: str, value: str, component_name: str = "") -> str:

    if not blueprint_path.strip() or not property_name.strip():
        return "❌ Нужны blueprint_path и property_name."
    return _run(
        SET_BLUEPRINT_PROPERTY_SCRIPT,
        blueprint_path=blueprint_path.strip(),
        component_name=component_name,
        property_name=property_name.strip(),
        value=value,
    )


@licensing.requires_pro("UE camera tools")
def ue_configure_camera(
    target: str, mode: str = "custom", apply_to: str = "both",

    arm_length: str = "", camera_pitch: str = "", camera_yaw: str = "",
) -> str:
    if not target.strip():
        return "❌ Укажи target: имя актора на уровне или путь Blueprint (/Game/...)."

    def _opt(s: str):
        s = (s or "").strip()
        if not s or s.lower() in ("none", "null"):
            return None
        return s

    return _run(
        CONFIGURE_CAMERA_SCRIPT,
        target=target.strip(),
        mode=mode.strip().lower(),
        apply_to=apply_to.strip().lower(),
        arm_length=_opt(arm_length),
        camera_pitch=_opt(camera_pitch),
        camera_yaw=_opt(camera_yaw),
    )


@licensing.requires_pro("UE Blueprint tools")
def ue_compile_blueprint(blueprint_path: str) -> str:

    if not blueprint_path.strip():
        return "❌ Укажи blueprint_path."
    return _run(COMPILE_BLUEPRINT_SCRIPT, blueprint_path=blueprint_path.strip())


@licensing.requires_pro("UE tools")
def ue_open_asset(asset_path: str) -> str:

    if not asset_path.strip():
        return "❌ Укажи asset_path."
    return _run(OPEN_ASSET_SCRIPT, asset_path=asset_path.strip())


@licensing.requires_pro("UE tools")
def ue_run_console(command: str) -> str:

    if not command.strip():
        return "❌ Укажи command."
    command_lower = command.strip().lower()
    dangerous_prefixes = ("open", "changelevel", "servertravel", "map", "travel", "quit", "exit", "restart")
    if command_lower.startswith(dangerous_prefixes) or any(k in command_lower for k in (" map ", "openmap", "servertravel", "changelevel", "travel ")):
        return "❌ ue_run_console запрещено для смены карт или перемещения. Используй безопасные UE-инструменты и скрипты."
    return _run(RUN_CONSOLE_SCRIPT, command=command.strip())


@licensing.requires_pro("UE actor tools")
def ue_set_component_property(

    identifier: str, property_name: str, value: str,
    component_name: str = "", component_class: str = "",
) -> str:
    if not identifier.strip() or not property_name.strip():
        return "❌ Нужны identifier и property_name."
    return _run(
        SET_COMPONENT_PROPERTY_SCRIPT,
        identifier=identifier.strip(),
        component_name=component_name,
        component_class=component_class,
        property_name=property_name.strip(),
        value=value,
    )


@licensing.requires_pro("UE actor tools")
def ue_inspect_properties(target: str, properties: str, component_name: str = "") -> str:

    if not target.strip() or not properties.strip():
        return "❌ Нужны target и properties (через запятую)."
    return _run(
        INSPECT_OBJECT_SCRIPT,
        target=target.strip(),
        properties=properties,
        component_name=component_name,
    )


LOAD_LEVEL_SCRIPT = """
level_path = _normalize_game_path(level_path)
if not level_path:
    _output({"error": "level_path пуст"})
else:
    les = _les()
    if not les:
        _output({"error": "LevelEditorSubsystem не найден"})
    else:
        try:
            loaded = les.load_level(level_path)
            if loaded:
                _output({"loaded": True, "level_path": level_path, "level_name": loaded.get_name() if hasattr(loaded, 'get_name') else None})
            else:
                _output({"error": "Не удалось загрузить уровень", "level_path": level_path})
        except Exception as exc:
            _output({"error": f"Ошибка загрузки уровня: {exc}"})
"""

TELEPORT_ACTOR_SCRIPT = """
identifier = identifier.strip()
actor = _find_actor(identifier)
if not actor:
    _output({"error": "Актор не найден", "identifier": identifier})
else:
    loc = _parse_value(location)
    rot = _parse_value(rotation)
    result = {"actor": actor.get_name(), "identifier": identifier}
    if isinstance(loc, (list, tuple)) and len(loc) == 3:
        new_loc = unreal.Vector(float(loc[0]), float(loc[1]), float(loc[2]))
        try:
            actor.set_actor_location(new_loc, False, True)
            result["location"] = [new_loc.x, new_loc.y, new_loc.z]
        except Exception as exc:
            result["location_error"] = str(exc)
    if isinstance(rot, (list, tuple)) and len(rot) == 3:
        new_rot = unreal.Rotator(float(rot[0]), float(rot[1]), float(rot[2]))
        try:
            actor.set_actor_rotation(new_rot, False)
            result["rotation"] = [new_rot.pitch, new_rot.yaw, new_rot.roll]
        except Exception as exc:
            result["rotation_error"] = str(exc)
    _output(result)
"""


@licensing.requires_pro("UE tools")
def ue_load_level(level_path: str) -> str:
    if not level_path.strip():
        return "❌ Укажи level_path, например /Game/Variant_Combat/Lvl_Combat"
    return _run(LOAD_LEVEL_SCRIPT, level_path=level_path.strip())


@licensing.requires_pro("UE actor tools")
def ue_teleport_actor(identifier: str, location: str = "", rotation: str = "") -> str:

    if not identifier.strip():
        return "❌ Укажи identifier актора."
    return _run(TELEPORT_ACTOR_SCRIPT, identifier=identifier.strip(), location=location or "", rotation=rotation or "")


@licensing.requires_pro("UE actor tools")
def ue_spawn_actor(class_path: str, location: str = "", rotation: str = "", label: str = "") -> str:
    if not class_path.strip():
        return "❌ Укажи class_path, например StaticMeshActor, PointLight или /Game/Blueprints/BP_Enemy."
    return _run(
        SPAWN_ACTOR_SCRIPT,
        class_path=class_path.strip(),
        location=location or "",
        rotation=rotation or "",
        label=label.strip(),
    )


@licensing.requires_pro("UE actor tools")
def ue_delete_actor(identifier: str) -> str:
    if not identifier.strip():
        return "❌ Укажи identifier актора для удаления."
    return _run(DELETE_ACTOR_SCRIPT, identifier=identifier.strip())


@licensing.requires_pro("UE actor tools")
def ue_duplicate_actor(identifier: str, offset: str = "", label: str = "") -> str:
    if not identifier.strip():
        return "❌ Укажи identifier актора для дублирования."
    return _run(DUPLICATE_ACTOR_SCRIPT, identifier=identifier.strip(), offset=offset or "", label=label.strip())


@licensing.requires_pro("UE tools")
def ue_save_level(save_all: bool = False) -> str:
    return _run(SAVE_LEVEL_SCRIPT, save_all=bool(save_all))


@licensing.requires_pro("UE tools")
def ue_play_in_editor() -> str:
    return _run(PLAY_IN_EDITOR_SCRIPT)


@licensing.requires_pro("UE tools")
def ue_stop_play_in_editor() -> str:
    return _run(STOP_PLAY_SCRIPT)


@licensing.requires_pro("UE actor tools")
def ue_set_actor_label(identifier: str, new_label: str) -> str:
    if not identifier.strip() or not new_label.strip():
        return "❌ Нужны identifier и new_label."
    return _run(SET_ACTOR_LABEL_SCRIPT, identifier=identifier.strip(), new_label=new_label.strip())


@licensing.requires_pro("UE actor tools")
def ue_attach_actor(child_identifier: str, parent_identifier: str, socket_name: str = "") -> str:
    if not child_identifier.strip() or not parent_identifier.strip():
        return "❌ Нужны child_identifier и parent_identifier."
    return _run(
        ATTACH_ACTOR_SCRIPT,
        child_identifier=child_identifier.strip(),
        parent_identifier=parent_identifier.strip(),
        socket_name=socket_name.strip(),
    )


