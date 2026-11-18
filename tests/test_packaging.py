"""Structural invariants for the .ankiaddon archive.

Verifies that build_ankiaddon.py produces a zip whose layout Anki accepts:
root-level manifest.json and __init__.py, no dev artefacts, no extra nesting.
"""

from __future__ import annotations

import importlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

# Import the builder from scripts/ (not a package).
_scripts = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)
_mod = importlib.import_module("build_ankiaddon")
build = _mod.build
ADDON_DIR = _mod.ADDON_DIR


@pytest.fixture()
def ankiaddon_path(tmp_path: Path) -> Path:
    """Build the archive into a temp directory and return its path."""
    dest = tmp_path / "mining_fixer.ankiaddon"
    return build(dest)


def test_archive_is_valid_zip(ankiaddon_path: Path) -> None:
    assert ankiaddon_path.exists()
    assert zipfile.is_zipfile(ankiaddon_path)


def test_root_contains_manifest_and_init(ankiaddon_path: Path) -> None:
    with zipfile.ZipFile(ankiaddon_path) as zf:
        names = zf.namelist()
    assert "manifest.json" in names
    assert "__init__.py" in names


def test_no_nested_directories_at_root(ankiaddon_path: Path) -> None:
    """Every entry must be a file at the top level (no mining_fixer/ prefix)."""
    with zipfile.ZipFile(ankiaddon_path) as zf:
        for name in zf.namelist():
            assert "/" not in name.rstrip("/") or not name.startswith("mining_fixer/"), (
                f"Archive entry {name!r} has an unexpected nested prefix"
            )


def test_excludes_dev_artefacts(ankiaddon_path: Path) -> None:
    with zipfile.ZipFile(ankiaddon_path) as zf:
        names = set(zf.namelist())
    assert "meta.json" not in names
    for name in names:
        assert "__pycache__" not in name, f"Found __pycache__ entry: {name}"
        assert not name.endswith(".pyc"), f"Found .pyc entry: {name}"
        assert "user_files" not in name, f"Found user_files entry: {name}"


def test_all_addon_source_files_included(ankiaddon_path: Path) -> None:
    """Every .py and .json that ships must be in the archive."""
    expected = set()
    for p in ADDON_DIR.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ADDON_DIR)
        # Skip excluded files
        parts = rel.parts
        if any(
            part in {"meta.json", "__pycache__", "user_files"} or part.startswith(".")
            for part in parts
        ):
            continue
        if rel.suffix in {".pyc", ".pyo"}:
            continue
        expected.add(str(rel))

    with zipfile.ZipFile(ankiaddon_path) as zf:
        actual = set(zf.namelist())

    assert expected == actual, f"Missing: {expected - actual}, Extra: {actual - expected}"


def test_manifest_is_valid_json(ankiaddon_path: Path) -> None:
    with zipfile.ZipFile(ankiaddon_path) as zf:
        raw = zf.read("manifest.json")
    data = json.loads(raw)
    assert "package" in data
    assert "name" in data
    assert "human_version" in data


def test_manifest_version_matches_pyproject(ankiaddon_path: Path) -> None:
    """manifest.json human_version must equal pyproject.toml version."""
    with zipfile.ZipFile(ankiaddon_path) as zf:
        manifest = json.loads(zf.read("manifest.json"))

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    text = pyproject.read_text()
    # Simple parse: find version = "..."
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("version") and "=" in stripped:
            # version = "0.2.0"
            version = stripped.split("=", 1)[1].strip().strip('"').strip("'")
            break
    else:
        pytest.fail("Could not find version in pyproject.toml")

    assert manifest["human_version"] == version
