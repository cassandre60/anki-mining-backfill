"""Layer boundary: the pure core must never import anki, aqt or PyQt."""

from __future__ import annotations

import ast
from pathlib import Path

CORE_MODULES = ["normalize.py", "fieldconfig.py", "matching.py", "plan.py", "report.py"]
FORBIDDEN = ("anki", "aqt", "PyQt5", "PyQt6")


def test_core_has_no_gui_backend_imports():
    root = Path(__file__).resolve().parent.parent
    for name in CORE_MODULES:
        tree = ast.parse((root / name).read_text(encoding="utf-8"), filename=name)
        for node in ast.walk(tree):
            module_name = None
            if isinstance(node, ast.Import):
                module_name = node.names[0].name
            elif isinstance(node, ast.ImportFrom) and node.module:
                module_name = node.module
            if module_name is None:
                continue
            assert module_name.split(".")[0] not in FORBIDDEN, (name, module_name)
