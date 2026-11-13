"""Anki-facing adapter: read the collection, execute an apply decision.

Only this module (and ``preview_dialog.py`` / ``__init__.py``) may touch
Anki or Qt. All decision logic lives in :mod:`mining_backfill.applier`, so
the safety rules stay testable without Anki installed.

Nothing here runs automatically: the dialog calls :func:`plan_preview` to
read, and :func:`apply_decision` only after the user accepted rows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aqt import mw

from .applier import ApplyDecision, NoteState, build_run_log, decide, decide_undo, run_log_records
from .matching import NoteRecord
from .plan import Plan, build_plan

__all__ = [
    "Preview",
    "apply_decision",
    "build_decision",
    "deck_records",
    "latest_run_log",
    "load_config",
    "plan_preview",
    "read_state",
    "restore_from_log",
    "write_run_log",
]

ADDON_MODULE = "mining_backfill"
UNDO_FOLDER = "mining_backfill"
DEFAULT_PREVIEW_LAST_N = 30


def _addon_name() -> str:
    try:
        return mw.addonManager.addon_from_module(__name__) or ADDON_MODULE
    except Exception:
        return ADDON_MODULE


def load_config() -> dict:
    """The add-on config: packaged ``config.json`` defaults merged with edits."""
    try:
        return dict(mw.addonManager.getConfig(_addon_name()) or {})
    except Exception:
        return {}


@dataclass
class Preview:
    """Everything the dialog needs, already computed and read-only."""

    plan: Plan | None = None
    records_by_id: dict[int, NoteRecord] | None = None
    scope: tuple[int, ...] = ()
    error: str | None = None


def deck_records(col, deck_name: str, note_type_name: str) -> list[NoteRecord] | None:
    """Mining-note records for the configured deck and note type.

    Returns ``None`` when the deck or the note type does not exist, so the
    caller can say so instead of silently doing nothing.
    """
    deck_id = col.decks.id_for_name(deck_name)
    note_type_id = col.models.id_for_name(note_type_name)
    if deck_id is None or note_type_id is None:
        return None
    rows = col.db.execute(
        "select n.id, n.mid, n.flds, n.tags from cards c join notes n on n.id=c.nid "
        "where c.did=? and n.mid=?",
        deck_id,
        note_type_id,
    )
    field_order = [f["name"] for f in col.models.get(note_type_id)["flds"]]
    out: list[NoteRecord] = []
    for note_id, notetype_id, fields, tags in rows:
        values = fields.split("\x1f")
        out.append(
            NoteRecord(
                note_id=note_id,
                notetype_id=notetype_id,
                fields=dict(zip(field_order, values, strict=False)),
                tags=frozenset(tags.split()),
            )
        )
    return out


def _media_exists(col, filename: str) -> bool:
    try:
        return (Path(col.media.dir()) / filename).exists()
    except Exception:
        return True  # never drop a fill because the check itself failed


def plan_preview(col, cfg: dict, scope: list[int] | None = None) -> Preview:
    """Build the plan for the newest ``preview_last_n`` notes of the deck."""
    deck_name = str(cfg.get("deck_name") or "")
    note_type_name = str(cfg.get("note_type_name") or "")
    records = deck_records(col, deck_name, note_type_name)
    if records is None:
        return Preview(error=f"Deck “{deck_name}” or note type “{note_type_name}” not found.")
    if not records:
        return Preview(error=f"No notes in deck “{deck_name}” use note type “{note_type_name}”.")

    records.sort(key=lambda r: r.note_id, reverse=True)
    if scope is None:
        last_n = int(cfg.get("preview_last_n") or DEFAULT_PREVIEW_LAST_N)
        scope = [r.note_id for r in records[:last_n]]
    by_id = {r.note_id: r for r in records}
    plan = build_plan(
        records,
        cfg,
        scope_note_ids=scope,
        media_exists=lambda name: _media_exists(col, name),
    )
    return Preview(plan=plan, records_by_id=by_id, scope=tuple(scope))


def read_state(col, note_id: int) -> NoteState:
    note = col.get_note(note_id)
    return NoteState(
        fields=dict(note.items()),
        tags=frozenset(note.tags),
    )


def build_decision(col, plan: Plan, checked, cfg: dict) -> ApplyDecision:
    """Re-assert the checked rows against the live collection."""
    return decide(
        plan,
        checked,
        read_state=lambda note_id: read_state(col, note_id),
        applied_tag=cfg.get("applied_tag") or None,
    )


def apply_decision(col, decision: ApplyDecision) -> int:
    """Perform the writes. Returns the number of notes modified.

    One ``update_note`` per note, so Anki's own undo entry stays meaningful.
    """
    fields_by_note: dict[int, list] = {}
    for write in decision.field_writes:
        fields_by_note.setdefault(write.note_id, []).append(write)
    for note_id, writes in fields_by_note.items():
        note = col.get_note(note_id)
        for write in writes:
            note[write.field] = write.new_value
        col.update_note(note)
    for tags_write in decision.tags_writes:
        note = col.get_note(tags_write.note_id)
        for tag in set(tags_write.new_tags) - set(tags_write.old_tags):
            note.add_tag(tag)
        for tag in set(tags_write.old_tags) - set(tags_write.new_tags):
            note.remove_tag(tag)
        col.update_note(note)
    return len(
        {w.note_id for w in decision.field_writes} | {t.note_id for t in decision.tags_writes}
    )


def undo_folder() -> Path:
    path = Path(mw.pm.profileFolder()) / UNDO_FOLDER / "undo"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_run_log(decision: ApplyDecision, meta: dict) -> Path:
    """Persist the run's exact inverse next to the profile."""
    log = build_run_log(decision, meta)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = undo_folder() / f"run-{stamp}.json"
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def latest_run_log() -> tuple[Path, dict] | None:
    folder = undo_folder()
    logs = sorted(folder.glob("run-*.json"))
    if not logs:
        return None
    path = logs[-1]
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def restore_from_log(col, log: dict) -> ApplyDecision:
    """Decide how to undo a logged run against the live collection."""
    return decide_undo(
        run_log_records(log),
        read_state=lambda note_id: read_state(col, note_id),
    )
