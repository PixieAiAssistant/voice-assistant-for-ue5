# UE 5.8 — Ассеты и пути

```python
# Пути всегда /Game/Folder/AssetName
paths = unreal.EditorAssetLibrary.list_assets("/Game/Blueprints", recursive=True)
asset = unreal.EditorAssetLibrary.load_asset("/Game/Blueprints/BP_Hero")

registry = unreal.AssetRegistryHelpers.get_asset_registry()
filt = unreal.ARFilter(recursive_paths=True, package_paths=[unreal.Name("/Game")])
assets = registry.get_assets(filt)
```
