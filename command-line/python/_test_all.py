"""
COMPREHENSIVE UE 5.8 TEST SUITE
Each test: records BEFORE, performs operation, records AFTER, VERIFIES change.
"""
import sys, json, traceback
sys.path.insert(0, ".")
from ue_bridge import get_bridge

B = get_bridge()
RESULTS = {"passed": 0, "failed": 0, "details": []}

def _run(script):
    d = B.run(script)
    if not d.get("success"):
        return {"_error": d.get("result", "unknown")}
    output = d.get("output", [])
    text = ""
    for item in output:
        if isinstance(item, dict) and "output" in item:
            text = item["output"]
        elif isinstance(item, str):
            text = item
    if not text:
        return {"_error": "no output"}
    if text.startswith("{"):
        return json.loads(text)
    if text.startswith("["):
        return json.loads(text)
    return {"_raw": text}

def test(name, verifier):
    global RESULTS
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print('-'*60)
    try:
        passed, msg = verifier()
        if passed:
            RESULTS["passed"] += 1
            RESULTS["details"].append(f"✅ {name}: {msg}")
            print(f"  ✅ PASS: {msg}")
        else:
            RESULTS["failed"] += 1
            RESULTS["details"].append(f"❌ {name}: {msg}")
            print(f"  ❌ FAIL: {msg}")
    except Exception as e:
        RESULTS["failed"] += 1
        RESULTS["details"].append(f"💥 {name}: CRASH {e}")
        print(f"  💥 CRASH: {e}")
        traceback.print_exc()

# ========================================================================
# TESTS
# ========================================================================

def test_project_context():
    def _():
        r = _run("""_output({"ok": True, "msg": "UE connected"})""")
        if "_error" in r:
            return False, r["_error"]
        return True, "UE connected"
    test("01_ue_connection", _)

def test_find_assets():
    def _():
        r = _run("""
bp = _load_blueprint("/Game/Variant_SideScrolling/Blueprints/BP_SideScrollingCharacter")
if bp:
    _output({"found": True, "name": bp.get_name()})
else:
    _output({"found": False, "error": "BP not found"})
""")
        if "_error" in r:
            return False, r["_error"]
        if not r.get("found"):
            return False, r.get("error", "BP not found")
        return True, f"Found BP: {r.get('name')}"
    test("02_find_BP_SideScrollingCharacter", _)

def test_get_blueprint_info():
    def _():
        r = _run("""
bp = _load_blueprint("/Game/Variant_SideScrolling/Blueprints/BP_SideScrollingCharacter")
if not bp:
    _output({"error": "BP not found"})
else:
    cdo = _get_blueprint_cdo(bp)
    comps = []
    if cdo:
        for comp, display in _list_components(cdo, blueprint=bp):
            snap = _component_snapshot(comp, display)
            snap["source"] = "blueprint_cdo"
            comps.append(snap)
    _output({"name": bp.get_name(), "component_count": len(comps), "components": comps})
""")
        if "_error" in r:
            return False, r["_error"]
        comps = r.get("components", [])
        has_camera = any("Camera" in c.get("name","") for c in comps)
        if not has_camera:
            names = [c.get("name","") for c in comps]
            return False, f"No Camera component. Found: {names}"
        loc = "?"
        for c in comps:
            if "Camera" in c.get("name",""):
                loc = c.get("relative_location", "?")
        return True, f"BP components: {len(comps)} including Camera loc={loc}"
    test("03_ue_get_blueprint_info", _)

def test_blueprint_camera_before():
    def _():
        """Record BP camera location BEFORE any changes."""
        r = _run("""
bp = _load_blueprint("/Game/Variant_SideScrolling/Blueprints/BP_SideScrollingCharacter")
cdo = _get_blueprint_cdo(bp)
c, d = _find_component(cdo, "Camera")
if c:
    loc = c.get_editor_property("relative_location")
    rot = c.get_editor_property("relative_rotation")
    fov = c.get_editor_property("field_of_view")
    _output({"loc": [round(loc.x,1),round(loc.y,1),round(loc.z,1)],
             "rot": [round(rot.pitch,1),round(rot.yaw,1),round(rot.roll,1)],
             "fov": fov, "bUsePawn": c.get_editor_property("bUsePawnControlRotation")})
else:
    _output({"error": "camera not found"})
""")
        if "_error" in r:
            return False, r["_error"]
        if "error" in r:
            return False, r["error"]
        loc = r.get("loc", [])
        if len(loc) != 3:
            return False, f"Bad location: {loc}"
        return True, f"BP Camera default: loc={loc}, rot={r.get('rot')}, fov={r.get('fov')}"
    test("04_BP_camera_before", _)

def test_blueprint_set_property():
    def _():
        """Set FOV, verify change."""
        bef = _run("""
bp = _load_blueprint("/Game/Variant_SideScrolling/Blueprints/BP_SideScrollingCharacter")
cdo = _get_blueprint_cdo(bp)
c, d = _find_component(cdo, "Camera")
_output({"fov": c.get_editor_property("field_of_view")}) if c else _output({"error":"no camera"})
""")
        before_fov = bef.get("fov", 0)
        set_r = _run("""
bp = _load_blueprint("/Game/Variant_SideScrolling/Blueprints/BP_SideScrollingCharacter")
cdo = _get_blueprint_cdo(bp)
c, d = _find_component(cdo, "Camera")
if c:
    c.modify()
    c.set_editor_property("field_of_view", 90.0)
    _compile_and_save_blueprint(bp)
    _output({"set": True})
else:
    _output({"error": "no camera"})
""")
        aft = _run("""
bp = _load_blueprint("/Game/Variant_SideScrolling/Blueprints/BP_SideScrollingCharacter")
cdo = _get_blueprint_cdo(bp)
c, d = _find_component(cdo, "Camera")
_output({"fov": c.get_editor_property("field_of_view")}) if c else _output({"error":"no camera"})
""")
        after_fov = aft.get("fov", 0)
        if abs(after_fov - 90.0) > 0.1:
            return False, f"FOV not changed: {before_fov} -> {after_fov}"
        return True, f"FOV set: {before_fov} -> {after_fov}"
    test("05_ue_set_blueprint_property", _)

def test_actor_components():
    def _():
        sel = get_sel_name()
        if not sel:
            return False, "No actor selected"
        r = _run(f"""
actor = _find_actor("{sel}")
if actor:
    rows = [_component_snapshot(comp, display) for comp, display in _list_components(actor)]
    _output({{"count": len(rows), "comps": rows}})
else:
    _output({{"error": "not found"}})
""")
        if "_error" in r:
            return False, r["_error"]
        comps = r.get("comps", [])
        has_cam = any("Camera" in c.get("name","") for c in comps)
        if not has_cam:
            return False, f"No Camera. Comps: {[c.get('name') for c in comps]}"
        return True, f"Actor has {r.get('count')} components including Camera"
    test("06_ue_list_actor_components", _)

def get_sel_name():
    r = _run("sel=_eas().get_selected_level_actors(); a=sel[0] if sel else None; _output({'n':a.get_name()}) if a else _output({'e':'none'})")
    return r.get("n","")

def test_configure_camera():
    def _():
        sel = get_sel_name()
        if not sel:
            return False, "No actor selected"

        # BEFORE
        bef = _run(f"""
a = _find_actor("{sel}")
c, d = _find_component(a, "Camera")
if c:
    loc = _serialize(c.get_editor_property("relative_location"))
    rot = _serialize(c.get_editor_property("relative_rotation"))
    bp = _get_blueprint_for_actor(a)
    arm = None
    if bp:
        cdo = _get_blueprint_cdo(bp)
        sa, sd = _find_component(cdo, "SpringArm")
        if sa:
            arm = sa.get_editor_property("target_arm_length")
    _output({{"loc": loc, "rot": rot, "arm": arm}})
else:
    _output({{"error": "no camera on actor"}})
""")
        if "_error" in bef:
            return False, bef["_error"]
        if "error" in bef:
            return False, bef["error"]

        # Execute camera configure
        exec_r = _run(f"""
a = _find_actor("{sel}")
if a:
    bp = _get_blueprint_for_actor(a)
    changes = _configure_camera_on_owner(a, "first_person", None, None, None)
    if bp:
        bpc, bpe = _configure_blueprint_camera(bp, "first_person", None, None, None)
        changes.extend(bpc)
    _output({{"changes": changes}})
else:
    _output({{"error": "actor not found"}})
""")
        if "_error" in exec_r:
            return False, exec_r["_error"]

        # AFTER - verify on instance
        aft = _run(f"""
a = _find_actor("{sel}")
c, d = _find_component(a, "Camera")
if c:
    loc = _serialize(c.get_editor_property("relative_location"))
    rot = _serialize(c.get_editor_property("relative_rotation"))
    bp = _get_blueprint_for_actor(a)
    arm = None
    if bp:
        cdo = _get_blueprint_cdo(bp)
        sa, sd = _find_component(cdo, "SpringArm")
        if sa:
            arm = sa.get_editor_property("target_arm_length")
    _output({{"loc": loc, "rot": rot, "arm": arm}})
else:
    _output({{"error": "no camera"}})
""")
        if "_error" in aft:
            return False, aft["_error"]

        # VERIFY changes
        bef_loc = bef.get("loc", [])
        aft_loc = aft.get("loc", [])
        bef_rot = bef.get("rot", [])
        aft_rot = aft.get("rot", [])

        errors = []
        if len(aft_loc) == 3 and abs(aft_loc[2] - 70.0) > 5:
            errors.append(f"location Z not ~70: {aft_loc}")
        if len(aft_rot) == 3 and abs(aft_rot[0]) > 5:
            errors.append(f"rotation pitch not 0: {aft_rot}")
        if errors:
            return False, f"Camera config incomplete: {'; '.join(errors)}. Before: loc={bef_loc} rot={bef_rot}. After: loc={aft_loc} rot={aft_rot}"

        return True, f"Camera configured: loc {bef_loc} -> {aft_loc}, rot {bef_rot} -> {aft_rot}, arm={aft.get('arm')}"
    test("07_ue_configure_camera_first_person", _)

def test_auto_route_set_property():
    def _():
        """Test SET_PROPERTY_SCRIPT auto-routing: set relative_location on actor, should route to Camera."""
        sel = get_sel_name()
        if not sel:
            return False, "No actor selected"

        # Try SET_PROPERTY_SCRIPT with relative_location on actor
        r = _run(f"""
actor = _find_actor("{sel}")
if not actor:
    _output({{"error": "actor not found"}})
else:
    # Try set on actor first
    prop = "relative_location"
    target = actor
    found = False
    try:
        values_json = json.dumps({{prop: [0.0, 0.0, 80.0]}}, ensure_ascii=False)
        ok = _toolset_set_properties(target, values_json)
        if ok:
            val = _serialize(target.get_editor_property(prop))
            _output({{"target": "actor", "value": val}})
            found = True
    except:
        pass
    if not found:
        # Try each component
        for comp, display in _list_components(actor):
            try:
                comp.modify()
                values_json = json.dumps({{prop: [0.0, 0.0, 80.0]}}, ensure_ascii=False)
                if _toolset_set_properties(comp, values_json):
                    val = _serialize(comp.get_editor_property(prop))
                    _output({{"target": str(display or ""), "value": val}})
                    found = True
                    break
            except Exception as e:
                pass
        if not found:
            _output({{"error": "no component accepted relative_location"}})
""")
        if "_error" in r:
            return False, r["_error"]
        if "error" in r:
            return False, r["error"]
        target = r.get("target", "?")
        val = r.get("value", [])
        if len(val) == 3 and abs(val[2] - 80.0) < 5:
            return True, f"relative_location set to {val} on '{target}'"
        return False, f"relative_location wrong: {val} on '{target}'"
    test("08_auto_route_set_property", _)

def test_compile_blueprint():
    def _():
        r = _run("""
bp = _load_blueprint("/Game/Variant_SideScrolling/Blueprints/BP_SideScrollingCharacter")
if bp:
    ok = _compile_and_save_blueprint(bp)
    _output({"compiled": ok})
else:
    _output({"error": "BP not found"})
""")
        if "_error" in r:
            return False, r["_error"]
        if not r.get("compiled"):
            return False, "Compile failed"
        return True, "BP compiled and saved"
    test("09_ue_compile_blueprint", _)

def test_set_component_property():
    def _():
        sel = get_sel_name()
        if not sel:
            return False, "No actor selected"
        bef = _run(f"""
a = _find_actor("{sel}")
c, d = _find_component(a, "Camera")
_output({{"fov": c.get_editor_property("field_of_view")}}) if c else _output({{"error":"no cam"}})
""")
        if "_error" in bef:
            return False, bef["_error"]
        set_r = _run(f"""
a = _find_actor("{sel}")
c, d = _find_component(a, "Camera")
if c:
    c.modify()
    c.set_editor_property("field_of_view", 90.0)
    _output({{"set": True}})
else:
    _output({{"error": "no camera"}})
""")
        aft = _run(f"""
a = _find_actor("{sel}")
c, d = _find_component(a, "Camera")
_output({{"fov": c.get_editor_property("field_of_view")}}) if c else _output({{"error":"no cam"}})
""")
        if abs(aft.get("fov", 0) - 90.0) > 0.1:
            return False, f"FOV not changed: {bef.get('fov')} -> {aft.get('fov')}"
        return True, f"Camera FOV: {bef.get('fov')} -> {aft.get('fov')}"
    test("10_ue_set_component_property", _)

def test_teleport_actor():
    def _():
        sel = get_sel_name()
        if not sel:
            return False, "No actor selected"
        bef = _run(f"""
a = _find_actor("{sel}")
if a:
    loc = a.get_actor_location()
    _output({{"loc": [round(loc.x,1), round(loc.y,1), round(loc.z,1)]}})
else:
