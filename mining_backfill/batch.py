"""Batch policy: what a bulk run may write, without a per-row review.

Pure module: no anki/aqt imports.

The preview dialog is for one card at a time. A bulk run over hundreds of
notes cannot ask the user to audit hundreds of rows, so it applies a
*policy* instead:

- **Lossless (default).** Fills into empty fields, markup-only bold repair,
  tag union. Nothing that already holds content is replaced.
- **Also replace Source** — the asbplayer blob URL becomes the timestamped
  source (the URL is kept in the run log).
- **Also expand Sentence** — the mined fragment becomes the full scene
  sentence, with the scene's bold moved onto this card's word (the fragment
  survives in ``cloze-*``).

Two structural rules keep a bulk run honest:

- **Group atomicity.** Rows the plan emitted as one group (a scene expansion
  together with its furigana/audio/picture/source rows) are written together
  or not at all. A full-scene furigana under a fragment sentence is exactly
  the half-apply the grouping exists to prevent.
- **Guarded rows are never written in bulk.** A row the plan left unchecked
  needs a human: the batch lists its note under "needs review" and moves on.

The selection is *derived*, never edited: the batch window shows counts, not
checkboxes per row.
"""

from __future__ import annotations

from dataclasses import dataclass

from .plan import (
    OP_ADD_TAGS,
    OP_BOLD_CLOZE_WORD,
    OP_EXPAND_SENTENCE,
    OP_FILL,
    OP_REPLACE_SOURCE,
    Plan,
    PlannedWrite,
)

__all__ = [
    "OPTIONAL_OPS",
    "SAFE_OPS",
    "BatchSelection",
    "ReviewNote",
    "allowed_ops",
    "select",
]

#: Writes that cannot lose information: empty-field fills, markup-only bold,
#: and tag additions.
SAFE_OPS = frozenset({OP_FILL, OP_BOLD_CLOZE_WORD, OP_ADD_TAGS})

#: Information-preserving replaces, each opt-in for a batch run.
OPTIONAL_OPS = frozenset({OP_REPLACE_SOURCE, OP_EXPAND_SENTENCE})

#: Reasons that deserve a human look rather than a silent "nothing to do".
REVIEW_REASONS = frozenset({"cloze-word-ambiguous", "cloze-word-not-in-sentence"})

_REASON_TEXT = {
    "no-parent-that-fills": "no enriched sibling found",
    "nothing-to-fill": "already complete",
    "opted-out": "opted out with the opt-out tag",
    "cloze-word-ambiguous": "bold ambiguous — left alone",
    "cloze-word-not-in-sentence": "bold not found — left alone",
}


@dataclass(frozen=True)
class ReviewNote:
    note_id: int
    reason: str
    rows: tuple[str, ...] = ()


@dataclass(frozen=True)
class BatchSelection:
    """What one batch run will do, as counts plus a review shortlist."""

    rows: tuple[PlannedWrite, ...] = ()
    review: tuple[ReviewNote, ...] = ()
    untouched: int = 0
    excluded_notes: int = 0

    @property
    def notes(self) -> int:
        return len({w.note_id for w in self.rows})

    def count_by_op(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for write in self.rows:
            counts[write.op] = counts.get(write.op, 0) + 1
        return counts

    def reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.review:
            counts[item.reason] = counts.get(item.reason, 0) + 1
        return counts


def allowed_ops(expand_sentence: bool = False, replace_source: bool = False) -> frozenset[str]:
    """The op set for the chosen batch options (the default is lossless)."""
    ops = set(SAFE_OPS)
    if expand_sentence:
        ops.add(OP_EXPAND_SENTENCE)
    if replace_source:
        ops.add(OP_REPLACE_SOURCE)
    return frozenset(ops)


def _reason_text(reason: str) -> str:
    return _REASON_TEXT.get(reason, reason)


def select(plan: Plan, ops: frozenset[str]) -> BatchSelection:
    """The rows a batch run may write under ``ops``, plus the review shortlist.

    Two levels of atomicity:

    - **Note level**: a note with any guarded (unchecked) row is never written
      in bulk — it goes to review whole. Writing its other rows would apply
      half a plan the user never accepted.
    - **Group level**: within a writable note, a scene group is written
      together or not at all (all rows must be allowed by the policy).

    The in-scope notes are exactly those the plan mentions: every written note
    plus every note carrying a reason.
    """
    rows_by_note: dict[int, list[PlannedWrite]] = {}
    for write in plan.writes:
        rows_by_note.setdefault(write.note_id, []).append(write)
    scope_notes = set(plan.reasons) | set(rows_by_note)

    selected: list[PlannedWrite] = []
    review: dict[int, ReviewNote] = {}
    excluded_notes: set[int] = set()

    for note_id, note_rows in rows_by_note.items():
        guarded = [write for write in note_rows if not write.default_checked]
        if guarded:
            labels = tuple(f"{write.field}:{write.op}" for write in guarded)
            badges = {badge for write in guarded for badge in write.badges}
            if "divergent-parents" in badges:
                why = "scene sources disagree — left alone"
            elif "far-from-source" in badges:
                why = "scene source far away in time — left alone"
            else:
                why = "guarded row needs a human"
            review[note_id] = ReviewNote(note_id, why, labels)
            continue
        groups: dict[str, list[PlannedWrite]] = {}
        for write in note_rows:
            key = write.group_id or f"row:{write.note_id}:{write.field}"
            groups.setdefault(key, []).append(write)
        for rows in groups.values():
            if any(write.op not in ops for write in rows):
                excluded_notes.add(note_id)
                continue
            selected.extend(rows)

    for note_id, reason in plan.reasons.items():
        if note_id in review or reason not in REVIEW_REASONS:
            continue
        review[note_id] = ReviewNote(note_id, _reason_text(reason))

    written = {write.note_id for write in selected}
    untouched = len(scope_notes - written - set(review) - excluded_notes)
    return BatchSelection(
        rows=tuple(selected),
        review=tuple(sorted(review.values(), key=lambda item: item.note_id)),
        untouched=untouched,
        excluded_notes=len(excluded_notes),
    )
