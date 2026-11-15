"""Layer boundary: the pure core must never import anki, aqt or PyQt.

The core is deliberately importable with no Anki installed, which is what
lets the headless audit builder and the test suite run anywhere. Only the
three Qt-facing modules may touch Anki; everything else stays pure.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = "mining_fixer"

# The only modules allowed to import anki/aqt/PyQt: the menu entry point,
# the collection adapter, and the preview dialog.
AQT_FACING = ("__init__.py", "collection_io.py", "preview_dialog.py", "batch_dialog.py")

FORBIDDEN = ("anki", "aqt", "PyQt5", "PyQt6")


def _imported_roots(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
    roots: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.append(node.module)
    return roots


def test_core_has_no_gui_backend_imports():
    root = Path(__file__).resolve().parent.parent / PACKAGE
    checked = 0
    for path in sorted(root.glob("*.py")):
        if path.name in AQT_FACING:
            continue
        checked += 1
        for module_name in _imported_roots(path):
            assert module_name.split(".")[0] not in FORBIDDEN, (path.name, module_name)
    assert checked >= 6, f"expected the pure core, found {checked} modules"


def test_core_uses_relative_intra_package_imports():
    # Absolute imports of our own modules would collide with other add-ons
    # (Anki puts the shared add-ons root on sys.path).
    root = Path(__file__).resolve().parent.parent / PACKAGE
    own = {p.stem for p in root.glob("*.py")}
    for path in sorted(root.glob("*.py")):
        for module_name in _imported_roots(path):
            assert module_name.split(".")[0] not in own, (path.name, module_name)


def test_aqt_facing_modules_exist():
    root = Path(__file__).resolve().parent.parent / PACKAGE
    for name in AQT_FACING:
        assert (root / name).exists(), name
