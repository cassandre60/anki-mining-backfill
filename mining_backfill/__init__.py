"""Mining Backfill — Anki add-on entry point.

Wires two Tools-menu actions: preview & apply, and undo last run.

The pure core (``plan``, ``matching``, ``applier``, …) must stay importable
without Anki — the headless audit builder and the test suite depend on it —
so the ``aqt`` import is optional here and every handler imports Anki's
utilities lazily. Nothing in this module may raise: an exception at import
time is what Anki shows users as "add-on failed to load".
"""

from __future__ import annotations

import contextlib
import json
import traceback
from pathlib import Path

try:
    from aqt import gui_hooks, mw
except ImportError:  # headless import of the package (tests, audit builder)
    gui_hooks = None
    mw = None

PREVIEW_LABEL = "Mining Backfill: preview and apply…"
UNDO_LABEL = "Mining Backfill: undo last run"
SELECTION_LABEL = "Mining Backfill: preview and apply on selection"

_menu_added = False


def addon_version() -> str:
    """``human_version`` from the packaged manifest, for the load banner."""
    try:
        manifest = Path(__file__).with_name("manifest.json")
        return str(json.loads(manifest.read_text(encoding="utf-8")).get("human_version", "?"))
    except Exception:
        return "?"


def _run_preview(scope_note_ids=None) -> None:
    from aqt.utils import showWarning

    try:
        from .preview_dialog import open_preview_dialog

        open_preview_dialog(scope_note_ids)
    except Exception:
        print(f"Mining Backfill: preview failed\n{traceback.format_exc()}")
        showWarning("Mining Backfill: preview failed — see the debug console.")


def _on_preview() -> None:
    _run_preview()


def _on_selection_preview(note_ids) -> None:
    _run_preview(list(note_ids))


def _on_browser_context_menu(browser, menu) -> None:
    """Offer the selection action in the Browser's right-click menu.

    Only when something is selected: the Tools entry already covers whole-deck
    runs, and an action that does nothing is worse than no action. The ids are
    captured now, so a selection change between opening the menu and clicking
    cannot silently retarget the run.
    """
    try:
        selected = list(browser.selected_notes())
    except Exception:
        return
    if not selected:
        return
    try:
        action = menu.addAction(SELECTION_LABEL)
        action.triggered.connect(lambda _checked=False: _on_selection_preview(selected))
    except Exception:
        print(f"Mining Backfill: could not add the Browser action\n{traceback.format_exc()}")


def _on_undo() -> None:
    from aqt.utils import showInfo, showWarning

    try:
        from .collection_io import apply_decision, latest_run_log, restore_from_log

        if mw is None or mw.col is None:
            showInfo("Open a profile first.")
            return
        found = latest_run_log()
        if found is None:
            showInfo("Mining Backfill: no run to undo.")
            return
        path, log = found
        decision = restore_from_log(mw.col, log)
        if not decision.row_count() and not decision.skipped:
            showInfo("Mining Backfill: that run is already undone.")
            return
        notes = apply_decision(mw.col, decision)
        lines = [f"Restored {decision.row_count()} value(s) across {notes} note(s)."]
        if decision.skipped:
            lines.append(
                f"{len(decision.skipped)} note(s) were edited since the run and were left alone:"
            )
            lines.extend(
                f"  {skipped.note_id} — {skipped.reason}" for skipped in decision.skipped[:10]
            )
        # Archive the log so the same run cannot be undone twice by accident.
        path.rename(path.with_name(f"undone-{path.name.removeprefix('run-')}"))
        showInfo("\n".join(lines))
    except Exception:
        print(f"Mining Backfill: undo failed\n{traceback.format_exc()}")
        showWarning("Mining Backfill: undo failed — see the debug console.")


def _add_menu_entries() -> None:
    """Add the Tools entries once the main window (and its menu) exists."""
    global _menu_added
    if _menu_added or mw is None or not hasattr(mw, "form"):
        return
    try:
        menu = mw.form.menuTools
        preview_action = menu.addAction(PREVIEW_LABEL)
        preview_action.triggered.connect(lambda _checked=False: _on_preview())
        undo_action = menu.addAction(UNDO_LABEL)
        undo_action.triggered.connect(lambda _checked=False: _on_undo())
        menu.insertSeparator(preview_action)
        _menu_added = True
    except Exception:
        print(f"Mining Backfill: could not add the Tools menu entries\n{traceback.format_exc()}")


if mw is not None:
    _add_menu_entries()
    with contextlib.suppress(Exception):  # a banner must never break startup
        print(f"Mining Backfill {addon_version()} loaded.")

# main_window_did_init fires once the menu bar exists; the import-time call
# above covers the common case, and this makes the entry point robust if
# Anki ever loads add-ons earlier in startup.
if gui_hooks is not None:
    gui_hooks.main_window_did_init.append(_add_menu_entries)
    gui_hooks.browser_will_show_context_menu.append(_on_browser_context_menu)
