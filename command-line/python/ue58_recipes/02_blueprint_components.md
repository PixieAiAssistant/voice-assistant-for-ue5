# UE 5.8 — Компоненты Blueprint-актора

```python
# get_components_by_class часто НЕ видит компоненты BP-актора!
sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
bp = unreal.BlueprintEditorLibrary.get_blueprint_asset(actor)
handles = sds.k2_gather_subobject_data_for_instance(actor)

for handle in handles:
    data = unreal.SubobjectDataBlueprintFunctionLibrary.get_data(handle)
    if unreal.SubobjectDataBlueprintFunctionLibrary.is_actor(data):
        continue
    comp = unreal.SubobjectDataBlueprintFunctionLibrary.get_associated_object(data)
    name = unreal.SubobjectDataBlueprintFunctionLibrary.get_display_name(data)
    # comp — SpringArmComponent, CameraComponent, ...
```
