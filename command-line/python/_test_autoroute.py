import sys; sys.path.insert(0,".")
from ue_bridge import get_bridge, run_with_args, SET_PROPERTY_SCRIPT
B = get_bridge()
# Test 1: Auto-route relative_location to Camera
r1 = run_with_args(SET_PROPERTY_SCRIPT, identifier="BP_SideScrollingCharacter", property_name="relative_location", value="[0,0,80]", component_class="")
print("TEST 1 (auto-route relative_location):", r1[:300] if not r1.startswith("FAIL") else r1)
# Test 2: Verify it went to Camera, not Actor
B.run_and_format("sel=_eas().get_selected_level_actors(); a=sel[0] if sel else None; print(a.get_name())")
B.run_and_format("""
a=_find_actor('BP_SideScrollingCharacter')
c,d=_find_component(a,'Camera')
if c:
    loc = c.get_editor_property('relative_location')
    print('Camera loc:', loc.x, loc.y, loc.z)
""")