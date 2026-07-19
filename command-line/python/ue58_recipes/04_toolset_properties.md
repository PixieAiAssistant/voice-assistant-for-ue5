# UE 5.8 — Details panel через ToolsetLibrary

```python
# Чтение:
props = unreal.ToolsetLibrary.get_object_properties(obj, ["TargetArmLength", "RelativeRotation"])

# Запись (JSON):
unreal.ToolsetLibrary.set_object_properties(obj, '{"TargetArmLength": 350.0}')

# Fallback если ToolsetLibrary недоступен:
obj.set_editor_property("target_arm_length", 350.0)
```
