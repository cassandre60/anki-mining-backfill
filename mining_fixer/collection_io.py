"""Anki-facing adapter: read the collection, execute an apply decision.

Only this module (and ``preview_dialog.py`` / ``__init__.py``) may touch
Anki or Qt. All decision logic lives in :mod:`mining_fixer.applier`, so
the safety rules stay testable without Anki installed.

Nothing here runs automatically: the dialog calls :func:`plan_preview` to
read, and :func:`apply_decision` only after the user accepted rows.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from aqt import mw

from .applier import (
    ApplyDecision,
    NoteState,
    build_run_log,
    decide,
    decide_undo,
    decision_subset,
    latest_run_log_in,
    merge_run_logs,
    run_log_records,
    verify_writes,
)
from .batch import default_ops, select
from .matching import NoteRecord
from .plan import Plan, build_plan, scope_from_selection

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

ADDON_MODULE = "mining_fixer"
UNDO_FOLDER = "mining_fixer"
#: Undo logs written before the add-on was renamed from Mining Backfill.
#: Runs logged by the old build stay undoable; this folder is only ever
#: read — new runs are logged under ``UNDO_FOLDER``.
LEGACY_UNDO_FOLDER = "mining_backfill"
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
    scope_label: str = ""
    excluded: tuple[int, ...] = ()
    missing: tuple[int, ...] = ()
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
        "select distinct n.id, n.mid, n.flds, n.tags from cards c "
        "join notes n on n.id=c.nid where c.did=? and n.mid=?",
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


def _record_for_note(note) -> NoteRecord:
    """One live note as a :class:`NoteRecord` (used for selections outside the deck)."""
    return NoteRecord(
        note_id=note.id,
        notetype_id=note.mid,
        fields=dict(note.items()),
        tags=frozenset(note.tags),
    )


def _japanese_support_mecab():
    """The installed Japanese Support controller, or ``None``.

    The add-on package's ``__init__`` imports ``reading`` as a submodule and
    the controller lives *there*: ``reading.py`` ends with
    ``mecab = MecabController()``. The package itself has no ``mecab``
    attribute, so looking only at the package always returned ``None`` — the
    furigana dimension silently reported itself unavailable, and a sentence
    completion that needed a rebuilt ruby shipped unchecked (the 正道 card
    kept its two-line fragment for exactly this reason). Guarded: any failure
    means ``None``, so the caller reports the dimension unavailable rather
    than guessing.
    """
    package = sys.modules.get("3918629684")
    reading = sys.modules.get("3918629684.reading")
    if reading is None and package is not None:
        reading = getattr(package, "reading", None)
    if reading is None:
        try:
            reading = __import__("3918629684.reading", fromlist=["mecab"])
        except Exception:
            reading = None
    for module in (reading, package):
        mecab = getattr(module, "mecab", None) if module is not None else None
        if mecab is not None and hasattr(mecab, "reading"):
            return mecab
    return None


def japanese_support_furigana_generator(col):
    """The reading engine of the installed Japanese Support add-on, or None.

    Bulk-fix dimension 3's bridge: returns ``sentence -> furigana`` backed
    by the add-on's own MeCab/Kakasi subprocesses — the collection's oracle
    for ruby, never a home-grown generator. Lazy and guarded: the add-on
    module only exists inside a running Anki, so headless tooling and the
    test suite get ``None`` and the planner reports the dimension as
    unavailable instead of writing anything. Entry points re-verified
    2026-11-15 against the installed source (`reading.mecab.reading` is
    the string function `regenerateReading` itself uses; the add-on's own
    public entry refuses non-empty destination fields).
    """
    mecab = _japanese_support_mecab()
    if mecab is None:
        return None
    media_strip = col.media.strip

    def generate(sentence: str) -> str | None:
        try:
            out = mecab.reading(media_strip(sentence or ""))
        except Exception:
            return None
        return out or None

    return generate


def plan_preview(col, cfg: dict, scope_note_ids=None) -> Preview:
    """Build the plan for a Browser selection, or for the newest notes.

    With ``scope_note_ids`` (the notes selected in the Browser) only those
    notes are *targets* — but every note of the configured deck stays
    available as a source, so a selection still finds its scene parent or word
    sibling. Selected notes from another note type are reported, not silently
    dropped, and selected notes outside the configured deck are loaded as
    targets too.
    """
    deck_name = str(cfg.get("deck_name") or "")
    note_type_name = str(cfg.get("note_type_name") or "")
    records = deck_records(col, deck_name, note_type_name)
    if records is None:
        return Preview(error=f"Deck “{deck_name}” or note type “{note_type_name}” not found.")
    if not records:
        return Preview(error=f"No notes in deck “{deck_name}” use note type “{note_type_name}”.")
    note_type_id = col.models.id_for_name(note_type_name)
    by_id = {r.note_id: r for r in records}

    excluded: list[int] = []
    missing: list[int] = []
    if scope_note_ids is None:
        records.sort(key=lambda r: r.note_id, reverse=True)
        last_n = int(cfg.get("preview_last_n") or DEFAULT_PREVIEW_LAST_N)
        scope = [r.note_id for r in records[:last_n]]
        scope_label = f"newest {len(scope)} note(s) in “{deck_name}”"
    else:
        wanted = list(dict.fromkeys(int(nid) for nid in scope_note_ids))
        for note_id in wanted:
            if note_id in by_id:
                continue
            try:
                note = col.get_note(note_id)
            except Exception:
                missing.append(note_id)  # deleted since the Browser rendered
                continue
            if note.mid != note_type_id:
                excluded.append(note_id)
                continue
            record = _record_for_note(note)
            records.append(record)
            by_id[note_id] = record
        scope, _unknown = scope_from_selection(wanted, by_id)
        if not scope:
            return Preview(
                error=(
                    f"None of the {len(wanted)} selected note(s) use note type “{note_type_name}”."
                ),
                excluded=tuple(excluded),
                missing=tuple(missing),
                scope_label=f"selection ({len(wanted)} selected)",
            )
        scope_label = f"selection ({len(scope)} note(s))"
        if missing:
            scope_label += f" · {len(missing)} selected note(s) no longer exist"

    plan = build_plan(
        records,
        cfg,
        scope_note_ids=scope,
        media_exists=lambda name: _media_exists(col, name),
        furigana_generator=japanese_support_furigana_generator(col),
    )
    return Preview(
        plan=plan,
        records_by_id=by_id,
        scope=tuple(scope),
        scope_label=scope_label,
        excluded=tuple(excluded),
        missing=tuple(missing),
    )


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


def build_batch_decision(col, plan: Plan, rows, cfg: dict) -> ApplyDecision:
    """Re-assert a batch selection: one ``(note_id, field)`` key per row."""
    return build_decision(col, plan, [(w.note_id, w.field) for w in rows], cfg)


def apply_decision(col, decision: ApplyDecision) -> int:
    """Perform the writes. Returns the number of notes modified.

    One ``update_note`` per note, so Anki's own undo entry stays meaningful.
    A note that vanished or refused the write is skipped with a printed
    warning instead of aborting the rest of the run — verification then
    reports whatever did not land, and the log still allows an exact undo.
    """
    fields_by_note: dict[int, list] = {}
    for write in decision.field_writes:
        fields_by_note.setdefault(write.note_id, []).append(write)
    modified = 0
    for note_id, writes in fields_by_note.items():
        try:
            note = col.get_note(note_id)
            for write in writes:
                note[write.field] = write.new_value
            col.update_note(note)
            modified += 1
        except Exception as exc:
            print(f"Mining Fixer: could not write note {note_id}: {exc}")
    for tags_write in decision.tags_writes:
        try:
            note = col.get_note(tags_write.note_id)
            for tag in set(tags_write.new_tags) - set(tags_write.old_tags):
                note.add_tag(tag)
            for tag in set(tags_write.old_tags) - set(tags_write.new_tags):
                note.remove_tag(tag)
            col.update_note(note)
            if tags_write.note_id not in fields_by_note:
                modified += 1
        except Exception as exc:
            print(f"Mining Fixer: could not tag note {tags_write.note_id}: {exc}")
    return modified


def undo_folder() -> Path:
    path = Path(mw.pm.profileFolder()) / UNDO_FOLDER / "undo"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_run_log(decision: ApplyDecision, meta: dict) -> Path:
    """Persist the run's exact inverse next to the profile."""
    log = build_run_log(decision, meta)
    # Microseconds: two runs inside the same second must not overwrite each
    # other's undo log.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = undo_folder() / f"run-{stamp}.json"
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def latest_run_log() -> tuple[Path, dict] | None:
    """The newest undo log, including runs logged by the pre-rename build."""
    return latest_run_log_in([undo_folder(), legacy_undo_folder()])


def legacy_undo_folder() -> Path:
    """Where the pre-rename build kept its undo logs; read only."""
    return Path(mw.pm.profileFolder()) / LEGACY_UNDO_FOLDER / "undo"


def restore_from_log(col, log: dict) -> ApplyDecision:
    """Decide how to undo a logged run against the live collection."""
    return decide_undo(
        run_log_records(log),
        read_state=lambda note_id: read_state(col, note_id),
    )


# --- batch runs -------------------------------------------------------

#: Notes written per backend pass. Keeps a bulk run responsive and means an
#: interruption leaves a partially applied, fully logged run instead of a
#: single half-finished transaction.
BATCH_CHUNK_NOTES = 100


@dataclass
class BatchResult:
    writes: int = 0
    modified: int = 0
    log_path: Path | None = None
    backup_created: bool | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _take_backup(col) -> tuple[bool | None, str | None]:
    """Anki's own backup, forced, before a bulk run touches anything."""
    try:
        created = col.create_backup(
            backup_folder=mw.pm.backupFolder(),
            force=True,
            wait_for_completion=True,
        )
        return bool(created), None
    except Exception as exc:
        return None, str(exc)


def preflight_fields(col, decision: ApplyDecision) -> list[str]:
    """Refuse a run whose field names do not exist on the target note type.

    The configured field list can drift from the collection (renamed note
    type, edited config). Writing an unknown field would raise halfway
    through a bulk run, so this is checked up front, before anything is
    touched.
    """
    problems: list[str] = []
    expected: dict[int, set[str]] = {}
    for note_id in decision.touched_notes:
        try:
            note = col.get_note(note_id)
        except Exception:
            continue  # vanished notes are reported by verification instead
        expected[note_id] = set(note.keys())
    for write in decision.field_writes:
        names = expected.get(write.note_id)
        if names is not None and write.field not in names:
            problems.append(f"note {write.note_id}: field “{write.field}” is not on its note type")
    return problems


def apply_batch(
    col, decision: ApplyDecision, meta: dict, *, take_backup: bool = True
) -> BatchResult:
    """Write a bulk decision: preflight, backup, log first, chunk, verify.

    The run log is written *before* the first write, so an interrupted or
    crashed run is still exactly reversible — undo only restores fields that
    still hold the value this run wrote. A failed backup aborts the run: no
    write happens without the safety net the user was promised.

    ``take_backup=False`` skips the backup for a *later* pass of one Apply:
    the fixpoint backs up once, before its first pass, not once per pass (a
    full copy per pass would be four collection copies of one Apply).
    """
    result = BatchResult(writes=decision.row_count())
    if not decision.row_count():
        return result
    field_problems = preflight_fields(col, decision)
    if field_problems:
        result.problems.extend(field_problems)
        result.problems.append("nothing was written")
        return result
    if take_backup:
        created, error = _take_backup(col)
        result.backup_created = created
        if error is not None:
            result.problems.append(f"backup failed, nothing was written: {error}")
            return result
    result.log_path = write_run_log(decision, meta)
    notes = decision.touched_notes
    for start in range(0, len(notes), BATCH_CHUNK_NOTES):
        chunk = notes[start : start + BATCH_CHUNK_NOTES]
        result.modified += apply_decision(col, decision_subset(decision, chunk))
    result.problems.extend(
        verify_writes(
            decision,
            lambda nid: read_state(col, nid),
            media_exists=lambda name: _media_exists(col, name),
        )
    )
    return result


#: One Apply may re-plan this many times to reach a fixpoint (QUALITY Q-A2).
#: A residual after this bound is a defect the scene audit's class F reports.
MAX_APPLY_PASSES = 4


def apply_plan_to_fixpoint(
    col, cfg: dict, scope, meta: dict, first_decision: ApplyDecision | None = None
) -> BatchResult:
    """One Apply is the whole fix (QUALITY Q-A2).

    A card completed by this pass becomes a scene source; a neighbour that
    needs its media would otherwise wait for the next Apply. So each pass
    re-plans on the *current* collection (real post-write state, never a
    simulation), selects the default rows, decides and writes — and the loop
    stops when a pass has nothing to write. It backs up once, before the
    first real pass, and reports a residual if the pass bound is hit. The
    per-pass undo logs are merged into one, so Undo reverses the whole Apply.
    """
    combined = BatchResult()
    log_paths: list[Path] = []
    decision = first_decision
    cleared = False
    backed_up = False
    for _pass in range(MAX_APPLY_PASSES):
        if decision is None:
            preview = plan_preview(col, cfg, scope_note_ids=list(scope))
            if preview.plan is None or preview.error:
                combined.problems.append(preview.error or "could not rebuild the plan")
                break
            selection = select(preview.plan, default_ops(cfg))
            decision = build_batch_decision(col, preview.plan, selection.rows, cfg)
        if not decision.row_count():
            cleared = True
            break
        result = apply_batch(col, decision, meta, take_backup=not backed_up)
        backed_up = True  # one backup per Apply, before its first real pass
        combined.writes += result.writes
        combined.modified += result.modified
        combined.problems.extend(result.problems)
        if result.backup_created:
            combined.backup_created = True
        if result.log_path is not None:
            log_paths.append(result.log_path)
        if result.problems:
            break
        decision = None  # next pass plans again on the state this pass wrote
    if not cleared and not combined.problems:
        # The pass bound was hit while the last pass still wrote. Re-plan once
        # and say so; a silent residual would break Q-A2 without a trace.
        preview = plan_preview(col, cfg, scope_note_ids=list(scope))
        if preview.plan is not None:
            remaining = select(preview.plan, default_ops(cfg))
            if remaining.rows:
                combined.problems.append(
                    f"still {len(remaining.rows)} row(s) to write after "
                    f"{MAX_APPLY_PASSES} passes — press Apply again"
                )
    merge_run_logs(log_paths)
    return combined


def dry_run_folder() -> Path:
    path = Path(mw.pm.profileFolder()) / UNDO_FOLDER / "dry-runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_dry_run(plan: Plan, records_by_id: dict[int, NoteRecord], selection, meta: dict) -> Path:
    """Write the readable preview for a batch the user did not apply."""
    from .report import render_batch_summary

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = dry_run_folder() / f"batch-{stamp}.md"
    path.write_text(render_batch_summary(plan, records_by_id, selection, meta), encoding="utf-8")
    return path
