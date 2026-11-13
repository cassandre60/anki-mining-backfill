"""The add-on must import exactly the way Anki imports it.

Anki imports the add-on folder as a package (``__import__(dir_name)``) and
puts a startup error in front of the user if that raises. These tests
reproduce that contract with a minimal ``aqt`` stub, which is also the only
way to exercise the entry point without a running Anki.
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest

MENU_LABELS: list[str] = []


class _Menu:
    def addAction(self, label):
        MENU_LABELS.append(label)
        return types.SimpleNamespace(
            label=label, triggered=types.SimpleNamespace(connect=lambda _fn: None)
        )

    def insertSeparator(self, _action):
        return None


def _purge(prefix: str) -> None:
    for name in [n for n in sys.modules if n == prefix or n.startswith(f"{prefix}.")]:
        del sys.modules[name]


@pytest.fixture
def loaded_addon(monkeypatch):
    """Install a stub ``aqt``, then import the add-on as Anki would."""
    MENU_LABELS.clear()
    _purge("aqt")
    _purge("mining_backfill")

    aqt = types.ModuleType("aqt")
    aqt.mw = types.SimpleNamespace(form=types.SimpleNamespace(menuTools=_Menu()))
    aqt.gui_hooks = types.SimpleNamespace(main_window_did_init=[])
    utils = types.ModuleType("aqt.utils")
    utils.showInfo = lambda *a, **k: None
    utils.showWarning = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "aqt", aqt)
    monkeypatch.setitem(sys.modules, "aqt.utils", utils)

    module = importlib.import_module("mining_backfill")
    yield module
    _purge("mining_backfill")


def test_entry_point_adds_the_tools_menu_entries(loaded_addon):
    # Pinned literally: these are the strings the user sees in the menu.
    assert MENU_LABELS == [
        "Mining Backfill: preview and apply…",
        "Mining Backfill: undo last run",
    ]


def test_menu_labels_have_no_qt_mnemonic_ampersand(loaded_addon):
    # Qt turns a bare "&" into an accelerator underline (and hides it), so a
    # label like "preview & apply" would render as "preview apply" with a
    # stray underline on the 'a'.
    assert all("&" not in label for label in MENU_LABELS)


def test_menu_registration_is_idempotent(loaded_addon):
    # The same callable is wired to main_window_did_init; if the menu were
    # added twice the user would see duplicate entries.
    hook = sys.modules["aqt"].gui_hooks.main_window_did_init
    assert len(hook) == 1
    hook[0]()
    hook[0]()
    assert MENU_LABELS == [loaded_addon.PREVIEW_LABEL, loaded_addon.UNDO_LABEL]


def test_entry_point_reports_the_packaged_version(loaded_addon):
    assert loaded_addon.addon_version() == "0.2.0"


def test_entry_point_survives_a_missing_main_window(monkeypatch):
    _purge("aqt")
    _purge("mining_backfill")
    aqt = types.ModuleType("aqt")
    aqt.mw = types.SimpleNamespace(form=None)  # main window not built yet
    aqt.gui_hooks = types.SimpleNamespace(main_window_did_init=[])
    utils = types.ModuleType("aqt.utils")
    utils.showInfo = lambda *a, **k: None
    utils.showWarning = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "aqt", aqt)
    monkeypatch.setitem(sys.modules, "aqt.utils", utils)
    module = importlib.import_module("mining_backfill")
    assert module._menu_added is False
    _purge("mining_backfill")


def test_preview_dialog_imports_with_real_anki():
    # Skipped where Anki is not installed (CI installs only pytest + ruff);
    # this is the check that the Qt module has no broken imports or names.
    pytest.importorskip("aqt", reason="needs a real Anki/PyQt6 install")
    importlib.import_module("aqt.qt")  # no stub: fail loudly if only a stub is around
    dialog = importlib.import_module("mining_backfill.preview_dialog")
    assert isinstance(dialog.PreviewDialog, type)
    assert callable(dialog.open_preview_dialog)
    _purge("mining_backfill.preview_dialog")
