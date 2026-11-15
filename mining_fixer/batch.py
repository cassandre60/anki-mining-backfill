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

Two kinds of guard are treated differently, because only one of them is about
trusting the source:

- **Source confidence** (`divergent-parents`, `far-from-source`) — if the
  source is not trustworthy, nothing from it is written. The note is listed
  as *left alone* with the reason. This is the wrong-source protection.
- **Text safety** (`fragment-not-recoverable`, `cloze-anchor-not-unique`,
  `stale-fragment-furigana-risk`, `paired-with-expansion`) — the sentence
  rewrite is unsafe, so exactly that text unit is dropped. The scene's audio,
  picture and translation are independent of the text and are still written.

The result is a bulk run that never needs a decision queue: it writes what is
provably safe, leaves the rest untouched, and reports the leftovers with a
reason in the dry-run report.
"""

from __future__ import annotations

from dataclasses import dataclass

from .plan import (
    OP_ADD_TAGS,
    OP_BOLD_CLOZE_WORD,
    OP_EXPAND_SENTENCE,
    OP_FILL,
    OP_REPAIR_SENTENCE,
    OP_REPLACE_SOURCE,
    Plan,
    PlannedWrite,
)

__all__ = [
    "OPTIONAL_OPS",
    "SAFE_OPS",
    "BatchSelection",
    "LeftAlone",
    "allowed_ops",
    "default_ops",
    "select",
]

#: Writes that cannot lose information: empty-field fills, markup-only bold,
#: and tag additions.
SAFE_OPS = frozenset({OP_FILL, OP_BOLD_CLOZE_WORD, OP_ADD_TAGS})

#: Information-preserving replaces, each opt-in for a batch run.
OPTIONAL_OPS = frozenset({OP_REPLACE_SOURCE, OP_EXPAND_SENTENCE, OP_REPAIR_SENTENCE})

#: The text unit: a sentence and its ruby are atomic (QUALITY Q-D4). Audio,
#: picture, translation and source do not depend on the sentence text, so
#: they are independent fills and stay eligible when the sentence rewrite is
#: not enabled.
TEXT_FIELDS = frozenset({"Sentence", "Sentence (furigana)"})

#: Guards about the *source*: they make every row of the note untrustworthy.
SOURCE_GUARDS = frozenset({"divergent-parents", "far-from-source"})

#: Guards about the *sentence text*: only the text unit is dropped.
TEXT_GUARDS = (
    ("fragment-not-recoverable", "sentence left alone — fragment not recoverable"),
    ("cloze-anchor-not-unique", "sentence left alone — tested word not unique"),
    ("stale-fragment-furigana-risk", "sentence left alone — would strand fragment ruby"),
    ("paired-with-expansion", "sentence left alone — paired with a guarded expansion"),
)

#: Reasons that are worth reporting but are not a decision for the user.
REPORT_REASONS = frozenset({"cloze-word-ambiguous", "cloze-word-not-in-sentence"})

_REASON_TEXT = {
    "no-parent-that-fills": "no enriched sibling found",
    "nothing-to-fill": "already complete",
    "opted-out": "opted out with the opt-out tag",
    "cloze-word-ambiguous": "bold ambiguous — left alone",
    "cloze-word-not-in-sentence": "bold not found — left alone",
}


@dataclass(frozen=True)
class LeftAlone:
    """A note the batch run will not write, with the reason (reporting only)."""

    note_id: int
    reason: str
    rows: tuple[str, ...] = ()


@dataclass(frozen=True)
class BatchSelection:
    """What one batch run will do, as counts plus a reporting shortlist."""

    rows: tuple[PlannedWrite, ...] = ()
    left_alone: tuple[LeftAlone, ...] = ()
    untouched: int = 0
    excluded_notes: int = 0
    sentences_left_alone: int = 0

    @property
    def notes(self) -> int:
        """Notes with at least one write (tag updates included)."""
        return len({w.note_id for w in self.rows})

    @property
    def field_notes(self) -> int:
        """Notes that actually get a field filled or rewritten."""
        return len({w.note_id for w in self.rows if w.op != OP_ADD_TAGS})

    @property
    def tag_only_notes(self) -> int:
        """Notes that would only gain tags — metadata, not a fix."""
        return self.notes - self.field_notes

    def count_by_op(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for write in self.rows:
            counts[write.op] = counts.get(write.op, 0) + 1
        return counts

    def reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.left_alone:
            counts[item.reason] = counts.get(item.reason, 0) + 1
        return counts


def allowed_ops(
    expand_sentence: bool = False,
    replace_source: bool = False,
    repair_sentence: bool = False,
) -> frozenset[str]:
    """The op set for the chosen batch options (the default is lossless)."""
    ops = set(SAFE_OPS)
    if expand_sentence:
        ops.add(OP_EXPAND_SENTENCE)
    if replace_source:
        ops.add(OP_REPLACE_SOURCE)
    if repair_sentence:
        ops.add(OP_REPAIR_SENTENCE)
    return frozenset(ops)


def default_ops(cfg: dict | None = None) -> frozenset[str]:
    """What a bulk run does out of the box.

    ``expand_sentence`` and ``replace_source`` are *information-preserving*
    replaces: the mined fragment survives in ``cloze-*`` and the blob URL is
    kept in the run log, so the undo restores them. A bulk fixer that
    refused to complete sentences would be useless, so they are on by
    default and configurable without a UI (``batch_expand_sentence`` /
    ``batch_replace_source``). The subtitle-noise repair rewrites non-empty
    text with no oracle beyond its own rule list, so it stays OFF by
    default (``batch_repair_sentence``) until proven on a real collection.
    """
    cfg = cfg or {}
    return allowed_ops(
        expand_sentence=bool(cfg.get("batch_expand_sentence", True)),
        replace_source=bool(cfg.get("batch_replace_source", True)),
        repair_sentence=bool(cfg.get("batch_repair_sentence", False)),
    )


def _reason_text(reason: str) -> str:
    return _REASON_TEXT.get(reason, reason)


def _text_guard_reason(guarded: list[PlannedWrite]) -> str:
    badges = {badge for write in guarded for badge in write.badges}
    for badge, reason in TEXT_GUARDS:
        if badge in badges:
            return reason
    return "sentence left alone — guard did not pass"


def select(plan: Plan, ops: frozenset[str]) -> BatchSelection:
    """The rows a batch run may write under ``ops``, plus what it leaves alone.

    Rules, in order:

    1. **Source confidence blocks the note.** Any guarded row carrying a
       `divergent-parents` / `far-from-source` badge means the source itself
       is suspect: no row of that note is written.
    2. **Text safety drops the text unit only.** A guarded sentence (or its
       ruby) is skipped; the note's independent scene fields are still
       written.
    3. **Policy tiers.** Rows whose op is not enabled are skipped, with the
       note counted as "excluded by policy" (so enabling the tier is
       discoverable in the dialog).
    4. Everything else is written. A note with nothing left to write is
       reported as *left alone*, never as a question for the user.
    """
    rows_by_note: dict[int, list[PlannedWrite]] = {}
    for write in plan.writes:
        rows_by_note.setdefault(write.note_id, []).append(write)
    scope_notes = set(plan.reasons) | set(rows_by_note)

    selected: list[PlannedWrite] = []
    left_alone: dict[int, LeftAlone] = {}
    excluded_notes: set[int] = set()
    sentences_left_alone: set[int] = set()

    for note_id, note_rows in rows_by_note.items():
        guarded = [write for write in note_rows if not write.default_checked]
        source_blocked = [write for write in guarded if SOURCE_GUARDS & set(write.badges)]
        if source_blocked:
            badges = {badge for write in source_blocked for badge in write.badges}
            why = (
                "scene sources disagree — left alone"
                if "divergent-parents" in badges
                else "scene source far away in time — left alone"
            )
            left_alone[note_id] = LeftAlone(
                note_id,
                why,
                tuple(f"{write.field}:{write.op}" for write in source_blocked),
            )
            continue

        usable = [write for write in note_rows if write.default_checked]
        text_rows = [write for write in usable if write.field in TEXT_FIELDS]
        other_rows = [write for write in usable if write.field not in TEXT_FIELDS]

        if text_rows and not all(write.op in ops for write in text_rows):
            excluded_notes.add(note_id)
            text_rows = []
        if guarded and any(write.field in TEXT_FIELDS for write in guarded):
            sentences_left_alone.add(note_id)

        note_writes: list[PlannedWrite] = []
        for write in other_rows:
            if write.op in ops:
                note_writes.append(write)
            else:
                excluded_notes.add(note_id)
        note_writes.extend(text_rows)
        selected.extend(note_writes)

        if not note_writes and guarded:
            left_alone[note_id] = LeftAlone(
                note_id,
                _text_guard_reason(guarded),
                tuple(f"{write.field}:{write.op}" for write in guarded),
            )

    for note_id, reason in plan.reasons.items():
        if note_id in left_alone or reason not in REPORT_REASONS:
            continue
        left_alone[note_id] = LeftAlone(note_id, _reason_text(reason))

    written = {write.note_id for write in selected}
    untouched = len(scope_notes - written - set(left_alone) - excluded_notes)
    return BatchSelection(
        rows=tuple(selected),
        left_alone=tuple(sorted(left_alone.values(), key=lambda item: item.note_id)),
        untouched=untouched,
        excluded_notes=len(excluded_notes),
        sentences_left_alone=len(sentences_left_alone),
    )
