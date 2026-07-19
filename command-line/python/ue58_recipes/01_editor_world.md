# UE 5.8 — Мир редактора

```python
# ПРАВИЛЬНО (5.8):
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = ues.get_editor_world()

# PIE / игра:
game_world = ues.get_game_world()

# НЕПРАВИЛЬНО (удалено):
# unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_editor_world()
```
