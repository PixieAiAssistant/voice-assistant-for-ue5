"""Общие Python-хелперы для Unreal Engine 5.8 (Remote Execution)."""

UE58_API_CHEATSHEET = """
UNREAL ENGINE 5.8 — КРИТИЧЕСКИЕ ПРАВИЛА API
==========================================
1. Мир редактора: unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
   НЕ используй EditorActorSubsystem.get_editor_world() — удалено в 5.8.
2. PIE-мир: UnrealEditorSubsystem.get_game_world()
3. Акторы уровня: EditorActorSubsystem (get_all_level_actors, spawn_actor_from_class, set_selected_level_actors)
4. Текущая карта: LevelEditorSubsystem.get_current_level()
5. EditorLevelLibrary — устарел, не использовать.
6. Blueprint-компоненты: get_components_by_class НЕ работает на BP-акторах!
   Используй SubobjectDataSubsystem (см. _iter_actor_components в хелперах).
7. Свойства объектов/BP: unreal.ToolsetLibrary.get_object_properties / set_object_properties (JSON).
8. Blueprint CDO: unreal.get_default_object(blueprint.generated_class())
9. Компиляция BP: unreal.BlueprintEditorLibrary.compile_blueprint(bp)
10. Пути ассетов: /Game/Folder/AssetName
"""

PIXIE_COMMON_HELPERS = '''
import ast
import re

def _camel_to_snake(name):
    """TargetArmLength -> target_arm_length"""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\\1_\\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\\1_\\2", s)
    return s.lower()

# Свойства, которые в UE 5.8 используют snake_case (не все! bUsePawnControlRotation — CamelCase)
_KNOWN_SNAKE_PROPS = {
    "target_arm_length", "relative_rotation", "relative_location",
    "field_of_view", "actor_label", "folder_path", "default_game_mode",
    "default_pawn_class", "blueprint_variable_category",
    "blueprint_variable_replication", "component_name", "component_template",
    "package_paths", "recursive_paths", "asset_name", "package_name",
    "object_path", "asset_class", "asset_class_path",
}

def _normalize_prop_name(name):
    lowered = name.lower()
    if lowered in _KNOWN_SNAKE_PROPS:
        return lowered
    snaked = _camel_to_snake(name)
    if snaked != name.lower() and snaked in _KNOWN_SNAKE_PROPS:
        return snaked
    # Fall back to original name (supports both CamelCase and snake_case)
    return name

def _text(value):
    """unreal.Text -> str, str -> str"""
    if isinstance(value, unreal.Text):
        return str(value)
    return value if isinstance(value, str) else str(value) if value is not None else ""

def _output(obj):
    """Safe JSON output. Converts unreal.Text to str."""
    try:
        print(json.dumps(obj, default=str, ensure_ascii=False))
    except Exception:
        print(json.dumps(obj, default=lambda o: _text(o) if isinstance(o, unreal.Text) else str(o), ensure_ascii=False))

def _serialize(value):
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    if isinstance(value, unreal.Text):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    if isinstance(value, unreal.Vector):
        return [round(value.x, 3), round(value.y, 3), round(value.z, 3)]
    if isinstance(value, unreal.Rotator):
        return [round(value.pitch, 3), round(value.yaw, 3), round(value.roll, 3)]
    if hasattr(value, "get_name"):
        try:
            return value.get_name()
        except Exception:
            pass
    return str(value)

def _parse_value(raw):
    if isinstance(raw, (bool, int, float)):
        return raw
    text = str(raw).strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        return ast.literal_eval(text)
    except Exception:
        return text

def _ues():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)

def _eas():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

def _les():
    return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)

def _sds():
    return unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)

def _get_editor_world():
    ues = _ues()
    return ues.get_editor_world() if ues else None

def _get_active_world():
    ues = _ues()
    if not ues:
        return None
    game = ues.get_game_world()
    return game if game else ues.get_editor_world()

def _normalize_game_path(path):
    path = (path or "").strip().replace("\\\\", "/")
    if not path:
        return ""
    if not path.startswith("/Game"):
        if path.startswith("Game/"):
            path = "/" + path
        else:
            path = "/Game/" + path.lstrip("/")
    return path

def _load_asset(path):
    path = _normalize_game_path(path)
    if not path:
        return None
    return unreal.EditorAssetLibrary.load_asset(path)

def _load_blueprint(path):
    asset = _load_asset(path)
    if asset and isinstance(asset, unreal.Blueprint):
        return asset
    return None

def _get_blueprint_cdo(bp):
    if not bp:
        return None
    gen = bp.generated_class()
    return unreal.get_default_object(gen) if gen else None

def _safe_label(actor):
    """actor.get_actor_label() -> str (converts unreal.Text)"""
    try:
        label = actor.get_actor_label()
        return str(label) if isinstance(label, unreal.Text) else label
    except Exception:
        try:
            return actor.get_name()
        except:
            return ""

def _split_actor_identifier(identifier):
    """'BP_Hero.Camera' -> ('BP_Hero', 'Camera'); без точки -> (identifier, '')."""
    text = (identifier or "").strip()
    if "." in text:
        actor_part, comp_part = text.rsplit(".", 1)
        return actor_part.strip(), comp_part.strip()
    return text, ""

def _find_actor(identifier):
    if not identifier:
        return None
    actor_part, _ = _split_actor_identifier(identifier)
    ident = actor_part.lower().strip()
    best = None
    for actor in _eas().get_all_level_actors():
        name = actor.get_name().lower()
        try:
            label = _safe_label(actor).lower()
        except Exception:
            label = ""
        if ident == name or ident == label:
            return actor
        if ident in name or ident in label:
            best = best or actor
    return best

def _get_blueprint_for_actor(actor):
    try:
        bp = unreal.BlueprintEditorLibrary.get_blueprint_asset(actor)
        if bp:
            return bp
    except Exception:
        pass
    try:
        cls = actor.get_class()
        if hasattr(unreal.EditorAssetLibrary, "get_blueprint_asset_for_class"):
            bp = unreal.EditorAssetLibrary.get_blueprint_asset_for_class(cls)
            if bp:
                return bp
    except Exception:
        pass
    try:
        return unreal.BlueprintEditorLibrary.get_blueprint_asset(actor.get_outer())
    except Exception:
        return None

def _gather_subobject_handles(actor, blueprint=None):
    sds = _sds()
    if blueprint:
        return list(sds.k2_gather_subobject_data_for_blueprint(blueprint))
    return list(sds.k2_gather_subobject_data_for_instance(actor))

def _iter_actor_components(actor, blueprint=None, component_class=None):
    if blueprint is None and isinstance(actor, unreal.Actor):
        blueprint = _get_blueprint_for_actor(actor)
    # Проверка: component_class должен быть реальным классом UE, а не случайным объектом
    if component_class is not None and hasattr(component_class, 'static_class'):
        filter_cls = component_class
    else:
        filter_cls = unreal.ActorComponent.static_class()
    seen = set()
    for handle in _gather_subobject_handles(actor, blueprint):
        data = unreal.SubobjectDataBlueprintFunctionLibrary.get_data(handle)
        if unreal.SubobjectDataBlueprintFunctionLibrary.is_actor(data):
            continue
        obj = unreal.SubobjectDataBlueprintFunctionLibrary.get_associated_object(data)
        if not isinstance(obj, unreal.ActorComponent):
            continue
        if not unreal.MathLibrary.class_is_child_of(obj.get_class(), filter_cls):
            continue
        oid = id(obj)
        if oid in seen:
            continue
        seen.add(oid)
        try:
            display = unreal.SubobjectDataBlueprintFunctionLibrary.get_display_name(data)
        except Exception:
            display = obj.get_name()
        yield obj, display or obj.get_name()

def _list_components(actor, component_class=None, blueprint=None):
    rows = []
    if isinstance(actor, unreal.Blueprint):
        cdo = _get_blueprint_cdo(actor)
        if not cdo:
            return rows
        src_actor = cdo
        src_bp = actor if blueprint is None else blueprint
    else:
        src_actor = actor
        src_bp = blueprint if blueprint else _get_blueprint_for_actor(actor)

    got = list(_iter_actor_components(src_actor, src_bp, component_class))
    if got:
        for comp, display in got:
            rows.append((comp, display))
    elif isinstance(actor, unreal.Actor):
        cls = component_class if component_class else unreal.ActorComponent
        for comp in actor.get_components_by_class(cls):
            rows.append((comp, comp.get_name()))
    return rows

def _find_component(owner, component_name="", component_class=None):
    name_part = (component_name or "").lower().strip()
    cls_name = component_class if isinstance(component_class, str) else ""
    for comp, display in _list_components(owner, getattr(unreal, cls_name, None) if cls_name else component_class):
        disp_text = str(display or "").lower() if display else ""
        names = [comp.get_name().lower(), disp_text]
        if not name_part:
            return comp, display
        if any(name_part in n or n == name_part for n in names):
            return comp, display
    return None, None

def _toolset_get_properties(obj, properties):
    """Returns a dict (parsed from ToolsetLibrary JSON string)."""
    if hasattr(unreal, "ToolsetLibrary"):
        try:
            raw = unreal.ToolsetLibrary.get_object_properties(obj, [_normalize_prop_name(p) for p in properties])
            if isinstance(raw, str):
                return json.loads(raw)
            return raw if isinstance(raw, dict) else {}
        except Exception:
            pass
    result = {}
    for prop in properties:
        snaked = _normalize_prop_name(prop)
        try:
            result[prop] = _serialize(obj.get_editor_property(snaked))
        except Exception as exc:
            result[prop] = f"<error: {exc}>"
    return result

def _toolset_set_properties(obj, values_json):
    if hasattr(unreal, "ToolsetLibrary"):
        try:
            obj.modify()
            return unreal.ToolsetLibrary.set_object_properties(obj, values_json)
        except Exception:
            pass
    data = _parse_value(values_json)
    if not isinstance(data, dict):
        return False
    obj.modify()
    for key, val in data.items():
        snaked = _normalize_prop_name(key)
        _apply_property(obj, snaked, json.dumps(val) if isinstance(val, (dict, list)) else str(val))
    return True

def _apply_property(obj, prop, raw_value):
    prop = _normalize_prop_name(prop)
    value = _parse_value(raw_value)
    current = None
    try:
        current = obj.get_editor_property(prop)
    except Exception:
        current = None
    if isinstance(current, unreal.Vector):
        vals = _parse_value(raw_value)
        value = unreal.Vector(float(vals[0]), float(vals[1]), float(vals[2]))
    elif isinstance(current, unreal.Rotator):
        vals = _parse_value(raw_value)
        value = unreal.Rotator(float(vals[0]), float(vals[1]), float(vals[2]))
    elif isinstance(current, unreal.LinearColor) and isinstance(value, (list, tuple)) and len(value) >= 3:
        alpha = float(value[3]) if len(value) > 3 else 1.0
        value = unreal.LinearColor(float(value[0]), float(value[1]), float(value[2]), alpha)
    obj.modify()
    obj.set_editor_property(prop, value)
    return obj.get_editor_property(prop)

def _component_snapshot(comp, display=None):
    row = {
        "name": comp.get_name(),
        "display_name": display or comp.get_name(),
        "class": comp.get_class().get_name() if comp.get_class() else "",
    }
    if isinstance(comp, unreal.SpringArmComponent):
        row["target_arm_length"] = comp.get_editor_property("target_arm_length")
        row["relative_rotation"] = _serialize(comp.get_editor_property("relative_rotation"))
        row["relative_location"] = _serialize(comp.get_editor_property("relative_location"))
        row["bUsePawnControlRotation"] = comp.get_editor_property("bUsePawnControlRotation")
    elif isinstance(comp, unreal.CameraComponent):
        row["relative_rotation"] = _serialize(comp.get_editor_property("relative_rotation"))
        row["relative_location"] = _serialize(comp.get_editor_property("relative_location"))
        row["field_of_view"] = comp.get_editor_property("field_of_view")
        row["bUsePawnControlRotation"] = comp.get_editor_property("bUsePawnControlRotation")
    else:
        try:
            row["relative_location"] = _serialize(comp.get_editor_property("relative_location"))
        except Exception:
            pass
        try:
            row["relative_rotation"] = _serialize(comp.get_editor_property("relative_rotation"))
        except Exception:
            pass
    return row

def _configure_camera_on_owner(owner, mode, arm_length, camera_pitch, camera_yaw, blueprint=None):
    changes = []
    target_arm = arm_length
    if target_arm is None:
        if mode == "first_person":
            target_arm = 0.0
        elif mode == "third_person":
            target_arm = 350.0
    pitch = 0.0 if camera_pitch is None else float(camera_pitch)
    yaw_override = None if camera_yaw is None else float(camera_yaw)

    for comp, display in _list_components(owner, unreal.SpringArmComponent, blueprint=blueprint):
        comp.modify()
        if target_arm is not None:
            before = comp.get_editor_property("target_arm_length")
            comp.set_editor_property("target_arm_length", float(target_arm))
            changes.append({"component": display, "property": "target_arm_length", "before": before, "after": float(target_arm)})
        if mode == "first_person":
            comp.set_editor_property("bUsePawnControlRotation", True)
            changes.append({"component": display, "property": "bUsePawnControlRotation", "after": True})
        elif mode == "third_person":
            comp.set_editor_property("bUsePawnControlRotation", True)
            changes.append({"component": display, "property": "bUsePawnControlRotation", "after": True})

    spring_arm_list = list(_list_components(owner, unreal.SpringArmComponent, blueprint=blueprint))

    for comp, display in _list_components(owner, unreal.CameraComponent, blueprint=blueprint):
        comp.modify()
        rot = comp.get_editor_property("relative_rotation")
        new_yaw = yaw_override if yaw_override is not None else rot.yaw
        before = _serialize(rot)
        comp.set_editor_property("relative_rotation", unreal.Rotator(pitch, new_yaw, rot.roll))
        changes.append({"component": display, "property": "relative_rotation", "before": before, "after": [pitch, new_yaw, rot.roll]})
        if mode in ("first_person", "third_person"):
            comp.set_editor_property("bUsePawnControlRotation", False)
            changes.append({"component": display, "property": "bUsePawnControlRotation", "after": False})
        if mode == "first_person":
            loc_before = _serialize(comp.get_editor_property("relative_location"))
            comp.set_editor_property("relative_location", unreal.Vector(0.0, 0.0, 70.0))
            changes.append({"component": display, "property": "relative_location", "before": loc_before, "after": [0.0, 0.0, 70.0]})
        elif mode == "third_person" and not spring_arm_list:
            loc_before = _serialize(comp.get_editor_property("relative_location"))
            arm = float(target_arm if target_arm is not None else 300.0)
            x_offset = -arm
            comp.set_editor_property("relative_location", unreal.Vector(x_offset, 0.0, 70.0))
            changes.append({
                "component": display,
                "property": "relative_location",
                "before": loc_before,
                "after": [x_offset, 0.0, 70.0],
                "note": "no SpringArm — camera X offset from arm_length/target_arm",
            })

    owner.modify()
    return changes

def _configure_blueprint_camera(bp, mode, arm_length, camera_pitch, camera_yaw):
    changes = []
    err = None
    target_arm = arm_length
    if target_arm is None:
        if mode == "first_person":
            target_arm = 0.0
        elif mode == "third_person":
            target_arm = 350.0
    pitch = 0.0 if camera_pitch is None else float(camera_pitch)
    yaw_override = None if camera_yaw is None else float(camera_yaw)

    cdo = _get_blueprint_cdo(bp)
    if cdo:
        changes.extend(_configure_camera_on_owner(cdo, mode, arm_length, camera_pitch, camera_yaw, blueprint=bp))

    if changes:
        _compile_and_save_blueprint(bp)
    elif not cdo:
        err = "Blueprint без CDO или компонентов камеры"
    return changes, err

def _resolve_blueprint_path(actor):
    bp = _get_blueprint_for_actor(actor)
    if bp:
        try:
            return bp.get_path_name()
        except Exception:
            pass
    try:
        cls_path = actor.get_class().get_path_name()
        if "_C" in cls_path:
            path = cls_path.split(".")[0]
            if path.startswith("/Game"):
                return path
    except Exception:
        pass
    return ""

def _resolve_blueprint_path_from_target(target):
    target = (target or "").strip()
    if target.startswith("/Game") or target.startswith("Game/"):
        return _normalize_game_path(target)
    actor = _find_actor(target)
    if actor:
        return _resolve_blueprint_path(actor)
    return ""

def _compile_and_save_blueprint(bp):
    """Скомпилировать и сохранить Blueprint (и пакет ассета).

    РАНЬШЕ ЭТОЙ ФУНКЦИИ НЕ БЫЛО в PIXIE_COMMON_HELPERS — её вызывали
    SET_BLUEPRINT_PROPERTY_SCRIPT / CONFIGURE_CAMERA_SCRIPT / COMPILE_BLUEPRINT_SCRIPT,
    поэтому любая правка/сохранение Blueprint падали в NameError при рантайме в UE.
    """
    if not bp:
        return False
    try:
        if hasattr(unreal, "BlueprintEditorLibrary"):
            unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        elif hasattr(bp, "compile"):
            bp.compile()
    except Exception as exc:
        _output({"warning": f"compile failed: {exc}"})
    try:
        path = bp.get_path_name()
        pkg = path.split(".")[0] if "." in path else path
        if hasattr(unreal, "EditorAssetLibrary"):
            return bool(unreal.EditorAssetLibrary.save_asset(pkg, only_if_is_dirty=False))
        return True
    except Exception:
        return False
'''
