"""Apply engine: turn a checked plan into writes, atomically per note.

Pure module: no anki/aqt imports, so every safety rule is unit-testable
without Anki. The collection adapter supplies the live values through
``read_state`` and performs the returned writes.

Rules enforced here:

- **Per-note atomicity.** If any checked row of a note no longer matches the
  collection, *no* row of that note is written. A half-applied card — full
  scene sentence copied but the bold repair skipped, or tags added without
  the fills — is worse than an untouched card.
- **Already-applied rows are recognised**, never double-written, so running
  the same plan twice is a no-op instead of an error.
- **The tag operation only ever adds.** A note that gained tags since the
  preview keeps them; the op is applied as a union.
- **Undo is exact**: it restores the values this run replaced and removes
  exactly the tags this run added, with the same atomicity rule.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from .plan import OP_ADD_TAGS, Plan, PlannedWrite

__all__ = [
    "OP_RESTORE",
    "ApplyDecision",
    "FieldWrite",
    "NoteState",
    "SelectionKey",
    "SkippedNote",
    "TagsWrite",
    "build_run_log",
    "decide",
    "decide_undo",
    "run_log_records",
]

#: Op label for writes that put a previous value back during an undo.
OP_RESTORE = "restore"

#: ``(note_id, field)`` — identifies one preview row / one checkbox.
SelectionKey = tuple[int, str]

#: Reads the live state of a note from whatever backend is in use.
StateReader = Callable[[int], "NoteState"]


@dataclass(frozen=True)
class NoteState:
    """One note as the apply step sees it: field values and tags."""

    fields: Mapping[str, str]
    tags: frozenset[str]


@dataclass(frozen=True)
class FieldWrite:
    note_id: int
    field: str
    op: str
    old_value: str
    new_value: str


@dataclass(frozen=True)
class TagsWrite:
    note_id: int
    op: str
    old_tags: tuple[str, ...]
    new_tags: tuple[str, ...]


@dataclass(frozen=True)
class SkippedNote:
    """A note the plan wanted to touch but the apply step declined to."""

    note_id: int
    reason: str
    rows: tuple[str, ...]


@dataclass
class ApplyDecision:
    field_writes: list[FieldWrite] = field(default_factory=list)
    tags_writes: list[TagsWrite] = field(default_factory=list)
    skipped: list[SkippedNote] = field(default_factory=list)

    @property
    def touched_notes(self) -> list[int]:
        return sorted(
            {w.note_id for w in self.field_writes} | {w.note_id for w in self.tags_writes}
        )

    def row_count(self) -> int:
        return len(self.field_writes) + len(self.tags_writes)


def _row_label(write: PlannedWrite) -> str:
    return f"{write.field}:{write.op}"


def _already_applied(write: PlannedWrite, state: NoteState) -> bool:
    if write.op == OP_ADD_TAGS:
        return set(write.new_value.split()) <= set(state.tags)
    return state.fields.get(write.field, "") == write.new_value


def _is_stale(write: PlannedWrite, state: NoteState) -> bool:
    if write.op == OP_ADD_TAGS:
        # Adding is safe as long as the note still carries the tags the
        # preview assumed; tags gained since then are kept, not removed.
        return not set(write.old_value.split()) <= set(state.tags)
    return state.fields.get(write.field, "") != write.old_value


def decide(
    plan: Plan,
    checked: Iterable[SelectionKey],
    read_state: StateReader,
    applied_tag: str | None = None,
) -> ApplyDecision:
    """Decide what to write for the checked rows of ``plan``.

    ``checked`` holds the ``(note_id, field)`` rows the user accepted;
    ``applied_tag`` (config ``applied_tag``) is added to every note this run
    writes, so a filled card is recognisable later.
    """
    wanted = set(checked)
    rows_by_note: dict[int, list[PlannedWrite]] = {}
    for write in plan.writes:
        if (write.note_id, write.field) in wanted:
            rows_by_note.setdefault(write.note_id, []).append(write)

    decision = ApplyDecision()
    for note_id in sorted(rows_by_note):
        rows = rows_by_note[note_id]
        state = read_state(note_id)

        # A row that already holds its target value is a repeat, not a
        # conflict — that is what makes re-running a plan a no-op.
        pending: list[PlannedWrite] = []
        stale: list[str] = []
        for write in rows:
            if _already_applied(write, state):
                continue
            if _is_stale(write, state):
                stale.append(_row_label(write))
            else:
                pending.append(write)

        if stale:
            decision.skipped.append(SkippedNote(note_id, "changed since preview", tuple(stale)))
            continue

        if not pending:
            decision.skipped.append(
                SkippedNote(note_id, "already applied", tuple(_row_label(w) for w in rows))
            )
            continue

        for write in pending:
            if write.op == OP_ADD_TAGS:
                continue  # folded into the single tag write below
            decision.field_writes.append(
                FieldWrite(
                    note_id=note_id,
                    field=write.field,
                    op=write.op,
                    old_value=write.old_value,
                    new_value=write.new_value,
                )
            )

        final_tags = set(state.tags)
        for write in pending:
            if write.op == OP_ADD_TAGS:
                final_tags |= set(write.new_value.split())
        if applied_tag:
            final_tags.add(applied_tag)
        if final_tags != set(state.tags):
            decision.tags_writes.append(
                TagsWrite(
                    note_id=note_id,
                    op=OP_ADD_TAGS,
                    old_tags=tuple(sorted(state.tags)),
                    new_tags=tuple(sorted(final_tags)),
                )
            )
    return decision


def build_run_log(decision: ApplyDecision, meta: Mapping[str, object]) -> dict:
    """JSON-ready record of a run: enough to reverse exactly what it did."""
    by_note: dict[int, dict] = {}
    for write in decision.field_writes:
        record = by_note.setdefault(
            write.note_id,
            {"note_id": write.note_id, "fields": [], "tags_applied": [], "tags_prior": []},
        )
        record["fields"].append(
            {"field": write.field, "prior": write.old_value, "applied": write.new_value}
        )
    for write in decision.tags_writes:
        record = by_note.setdefault(
            write.note_id,
            {"note_id": write.note_id, "fields": [], "tags_applied": [], "tags_prior": []},
        )
        record["tags_prior"] = list(write.old_tags)
        record["tags_applied"] = list(write.new_tags)
    return {**meta, "records": [by_note[nid] for nid in sorted(by_note)]}


def run_log_records(log: Mapping[str, object]) -> list[dict]:
    """The per-note records of a run log, defensively typed."""
    records = log.get("records")
    if not isinstance(records, Sequence):
        return []
    return [r for r in records if isinstance(r, dict)]


def decide_undo(records: Iterable[Mapping[str, object]], read_state: StateReader) -> ApplyDecision:
    """Decide how to reverse a run logged by :func:`build_run_log`.

    A note is restored only when every field it received still holds the
    value the run wrote; anything edited since is reported, not clobbered.
    Fields already back at their prior value are left alone, so an undo is
    idempotent too.
    """
    decision = ApplyDecision()
    for record in records:
        note_id = int(record["note_id"])
        state = read_state(note_id)
        fields = [f for f in record.get("fields", []) if isinstance(f, dict)]

        stale: list[str] = []
        restores: list[FieldWrite] = []
        for entry in fields:
            field_name = str(entry["field"])
            applied = str(entry["applied"])
            prior = str(entry["prior"])
            current = state.fields.get(field_name, "")
            if current == prior:
                continue  # already restored
            if current != applied:
                stale.append(f"{field_name}:edited-since-run")
                continue
            restores.append(FieldWrite(note_id, field_name, OP_RESTORE, applied, prior))

        to_remove = set(record.get("tags_applied", [])) - set(record.get("tags_prior", []))
        remaining_tags = set(state.tags) - to_remove

        if stale:
            decision.skipped.append(SkippedNote(note_id, "changed since the run", tuple(stale)))
            continue

        decision.field_writes.extend(restores)
        if remaining_tags != set(state.tags):
            decision.tags_writes.append(
                TagsWrite(
                    note_id=note_id,
                    op=OP_RESTORE,
                    old_tags=tuple(sorted(state.tags)),
                    new_tags=tuple(sorted(remaining_tags)),
                )
            )
    return decision
