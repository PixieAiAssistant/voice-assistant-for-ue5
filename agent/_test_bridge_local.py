"""Локальные тесты без UE: синтаксис шаблонов и форматирование ответов."""
import ast
import sys

sys.path.insert(0, ".")

from ue_bridge import (
    SET_PROPERTY_SCRIPT,
    LIST_ACTORS_SCRIPT,
    FIND_ACTORS_SCRIPT,
    GET_SELECTION_SCRIPT,
    GET_ACTOR_INFO_SCRIPT,
    _normalize_ue_output,
    _payload_error_from_text,
)
from ue_tools import (
    FIND_ASSETS_SCRIPT,
    GET_PROJECT_CONTEXT_SCRIPT,
    SET_COMPONENT_PROPERTY_SCRIPT,
    INSPECT_OBJECT_SCRIPT,
    CONFIGURE_CAMERA_SCRIPT,
)


def test_script_syntax(name: str, source: str) -> None:
    ast.parse(source)
    print(f"  syntax {name}: OK")


def test_normalize_output() -> None:
    raw = [{"type": "Info", "output": '{"count": 2, "actors": []}\r\n'}]
    text = _normalize_ue_output(raw)
    assert '"count": 2' in text
    print("  normalize list output: OK")


def test_payload_error_detection() -> None:
    assert _payload_error_from_text('{"error": "Актор не найден"}') == "Актор не найден"
    assert _payload_error_from_text('{"loaded": true}') is None
    print("  payload error detection: OK")


def main() -> int:
    print("Local bridge tests (no UE required)")
    scripts = {
        "SET_PROPERTY": SET_PROPERTY_SCRIPT,
        "LIST_ACTORS": LIST_ACTORS_SCRIPT,
        "FIND_ACTORS": FIND_ACTORS_SCRIPT,
        "GET_SELECTION": GET_SELECTION_SCRIPT,
        "GET_ACTOR_INFO": GET_ACTOR_INFO_SCRIPT,
        "FIND_ASSETS": FIND_ASSETS_SCRIPT,
        "GET_PROJECT_CONTEXT": GET_PROJECT_CONTEXT_SCRIPT,
        "SET_COMPONENT_PROPERTY": SET_COMPONENT_PROPERTY_SCRIPT,
        "INSPECT_OBJECT": INSPECT_OBJECT_SCRIPT,
        "CONFIGURE_CAMERA": CONFIGURE_CAMERA_SCRIPT,
    }
    for name, src in scripts.items():
        test_script_syntax(name, src)
    test_normalize_output()
    test_payload_error_detection()
    print("All local tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
