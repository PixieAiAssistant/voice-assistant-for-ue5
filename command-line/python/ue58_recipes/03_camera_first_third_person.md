# UE 5.8 — Камера first / third person

```python
# SpringArm: TargetArmLength 0 = first person, ~350 = third person
# Если SpringArm нет (SideScrolling и т.п.) — third person через Camera RelativeLocation X = -arm_length

for comp, label in components:  # через SubobjectData (см. recipe 02)
    if isinstance(comp, unreal.SpringArmComponent):
        comp.set_editor_property("target_arm_length", 0.0)  # FPS
    if isinstance(comp, unreal.CameraComponent):
        rot = comp.get_relative_rotation()
        comp.set_editor_property("relative_rotation", unreal.Rotator(0.0, rot.yaw, rot.roll))

# Без SpringArm — third person: Camera relative_location = Vector(-350, 0, 70)

# Blueprint (постоянно): править SCS template + compile_blueprint + save
```
