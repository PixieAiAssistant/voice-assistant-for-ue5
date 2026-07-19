"""Quick UE connection smoke test."""
from ue_bridge import get_bridge

b = get_bridge()
r = b.run('_output({"ok": True, "msg": "connected"})')
print("success:", r.get("success"))
print("output:", r.get("output"))
print("result:", r.get("result"))
