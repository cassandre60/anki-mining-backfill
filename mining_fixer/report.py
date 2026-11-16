"""Markdown report rendering for a plan run.

Pure module: no anki/aqt imports.
"""

from __future__ import annotations

from .fieldconfig import sound_files
from .matching import NoteRecord
from .plan import (
    OP_ADD_TAGS,
    OP_BOLD_CLOZE_WORD,
    OP_EXPAND_SENTENCE,
    OP_FILL,
    OP_REGENERATE_FURIGANA,
    OP_REPAIR_SENTENCE,
    OP_REPLACE_SOURCE,
    Plan,
)

__all__ = [
    "GLANCE_LIMIT",
    "OP_LABELS",
    "change_lines",
    "field_label",
    "render_batch_summary",
    "render_markdown",
]

OP_LABELS = {
    OP_FILL: "fill",
    OP_REPLACE_SOURCE: "replace blob Source",
    OP_EXPAND_SENTENCE: "expand to scene sentence",
    OP_BOLD_CLOZE_WORD: "bold markup (text unchanged)",
    OP_REPAIR_SENTENCE: "repair subtitle noise",
    OP_REGENERATE_FURIGANA: "regenerate furigana",
    OP_ADD_TAGS: "add tags (never removes)",
}


#: Rows a capped list shows before pointing at the full report — one knob for
#: the batch window's glance lists so neither grows with the selection.
GLANCE_LIMIT = 40


def change_lines(
    selection,
    records: dict[int, NoteRecord],
    limit: int = GLANCE_LIMIT,
) -> list[str]:
    """One glimpse line per changed note: the word, what changes, and for the
    sentence rewrites a short before → after sample.

    Built for the batch window's "planned changes" list — labels and a
    sample, never full field values; the report has the complete page. The
    risky dimensions (sentence expansion, subtitle repair) get the sample so
    soundness is checkable at a glance; ruby markup and markup-only bold
    stay label-only because their values are noise.
    """
    by_note: dict[int, list] = {}
    for write in selection.rows:
        by_note.setdefault(write.note_id, []).append(write)

    lines: list[str] = []
    for note_id, writes in list(by_note.items())[:limit]:
        record = records.get(note_id)
        word = record.get("Expression") if record is not None else ""
        labels = []
        for write in writes:
            label = field_label(write)
            if write.op in (OP_EXPAND_SENTENCE, OP_REPAIR_SENTENCE):
                label += f" ({_plain(write.old_value, 40)} → {_plain(write.new_value, 60)})"
            labels.append(label)
        prefix = word if word else f"note {note_id}"
        lines.append(f"{prefix} — {' · '.join(labels)}")
    if len(by_note) > limit:
        lines.append(f"… and {len(by_note) - limit} more note(s) — the report has the full list")
    return lines


def _plain(value: str, limit: int = 160) -> str:
    text = value or ""
    text = text.replace("\n", " ⏎ ")
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text.replace("|", "\\|")


def render_batch_summary(
    plan: Plan,
    records: dict[int, NoteRecord],
    selection,
    meta: dict,
    limit: int = 200,
) -> str:
    """One readable page: what changes, per card, and what was left alone.

    Written for a human skimming a bulk run, not for a machine: one row per
    note, human field labels, and the reasons listed in plain words. The
    per-field old → new detail stays in the plan JSON.
    """
    lines: list[str] = []
    lines.append("# Mining Fixer — preview (nothing was changed)")
    lines.append("")
    by_op = selection.count_by_op()
    filled = ", ".join(
        f"{count} {OP_LABELS.get(op, op)}" for op, count in by_op.items() if op != OP_ADD_TAGS
    )
    lines.append(f"- selected: {meta.get('scope', '?')} note(s)")
    lines.append(
        f"- will be fixed: {selection.field_notes} note(s)" + (f" — {filled}" if filled else "")
    )
    if selection.tag_only_notes:
        lines.append(f"- only tag updates: {selection.tag_only_notes} note(s)")
    lines.append(f"- unchanged: {selection.untouched} note(s)")
    lines.append(f"- left alone: {len(selection.left_alone)} note(s)")
    lines.append("")

    by_note: dict[int, list[str]] = {}
    for write in selection.rows:
        label = field_label(write)
        labels = by_note.setdefault(write.note_id, [])
        if label not in labels:
            labels.append(label)
    lines.append("## What will be fixed")
    lines.append("")
    if not by_note:
        lines.append("Nothing.")
    else:
        lines.append("| word | note | what changes |")
        lines.append("|---|---|---|")
        for note_id in list(by_note)[:limit]:
            record = records.get(note_id)
            word = record.get("Expression") if record is not None else ""
            lines.append(f"| {word or '—'} | {note_id} | {' · '.join(by_note[note_id])} |")
        if len(by_note) > limit:
            lines.append("")
            lines.append(f"(showing the first {limit} of {len(by_note)} notes)")
    lines.append("")

    if selection.left_alone:
        lines.append("## Left alone")
        lines.append("")
        lines.append("| word | note | why |")
        lines.append("|---|---|---|")
        for item in selection.left_alone[:limit]:
            record = records.get(item.note_id)
            word = record.get("Expression") if record is not None else ""
            lines.append(f"| {word or '—'} | {item.note_id} | {item.reason} |")
        lines.append("")
        lines.append("Nothing here needs a decision — these are simply untouched.")
    return "\n".join(lines) + "\n"


_LABELS_BY_FIELD = {
    "Sentence Audio": "scene audio",
    "Picture": "picture",
    "Translation": "translation",
    "Source": "timestamped source",
    "Sentence (furigana)": "furigana",
    "Expression": "expression",
}


def field_label(write) -> str:
    """A human phrase for one planned write."""
    if write.op == OP_ADD_TAGS:
        added = " ".join(sorted(set(write.new_value.split()) - set(write.old_value.split())))
        return f"tags: {added}" if added else "tags"
    if write.op == OP_EXPAND_SENTENCE and write.field == "Sentence":
        return "full scene sentence"
    if write.op == OP_BOLD_CLOZE_WORD:
        return "bold on the tested word"
    if write.op == OP_REPAIR_SENTENCE:
        return "sentence noise repair"
    if write.op == OP_REGENERATE_FURIGANA:
        return "furigana regenerated"
    return _LABELS_BY_FIELD.get(write.field, write.field)


def render_markdown(plan: Plan, records: dict[int, NoteRecord], run_meta: dict) -> str:
    by_note: dict[int, list] = {}
    for w in plan.writes:
        by_note.setdefault(w.note_id, []).append(w)

    checked = [w for w in plan.writes if w.default_checked]
    lines: list[str] = []
    lines.append("# Mining Fixer — run report")
    lines.append("")
    for k, v in run_meta.items():
        lines.append(f"- **{k}**: {v}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- notes in scope: {len(plan.reasons) + len(by_note)}")
    lines.append(f"- notes with proposed changes: {len(by_note)}")
    lines.append(f"- field writes: {len(plan.writes)} (default-checked: {len(checked)})")
    fills = sum(1 for w in plan.writes if w.op == OP_FILL)
    markup = sum(1 for w in plan.writes if w.op == OP_BOLD_CLOZE_WORD)
    tag_adds = sum(1 for w in plan.writes if w.op == OP_ADD_TAGS)
    replaces = sum(1 for w in plan.writes if w.op not in (OP_FILL, OP_BOLD_CLOZE_WORD, OP_ADD_TAGS))
    lines.append(f"- fills: {fills}, replaces: {replaces}")
    if markup:
        lines.append(f"- markup-only bold repairs: {markup}")
    if tag_adds:
        lines.append(f"- tag additions: {tag_adds}")
    unfixable = [r for r in plan.reasons.values()]
    reason_counts: dict[str, int] = {}
    for r in unfixable:
        reason_counts[r] = reason_counts.get(r, 0) + 1
    for reason, count in sorted(reason_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"- unfixable ({reason}): {count}")
    if plan.warnings:
        lines.append("")
        lines.append("## Warnings")
        lines.append("")
        for warning in plan.warnings:
            lines.append(f"- {warning}")

    lines.append("")
    lines.append("## Proposed changes")
    lines.append("")
    for note_id in sorted(by_note):
        record = records.get(note_id)
        expr = record.get("Expression") if record else "?"
        lines.append(f"### {expr or '(sentence card)'} — note {note_id}")
        lines.append("")
        lines.append("| field | op | new value (from note) | default | badges |")
        lines.append("|---|---|---|---|---|")
        for w in by_note[note_id]:
            src = f" note {w.source_note_id}" if w.source_note_id else ""
            val = _plain(w.new_value)
            if w.op in (OP_EXPAND_SENTENCE, OP_REPAIR_SENTENCE, OP_REGENERATE_FURIGANA):
                val = f"{_plain(w.old_value, 60)} → {_plain(w.new_value, 90)}"
            elif w.op == OP_ADD_TAGS:
                added = " ".join(sorted(set(w.new_value.split()) - set(w.old_value.split())))
                val = f"{_plain(w.old_value, 40) or '(no tags)'} + {_plain(added, 40)}"
            if w.field == "Sentence Audio" or w.field == "Word Audio":
                val = ", ".join(sound_files(w.new_value)) or _plain(w.new_value, 60)
            state = "✓" if w.default_checked else "—"
            badges = ", ".join(w.badges) or "-"
            lines.append(
                f"| {w.field} | {OP_LABELS.get(w.op, w.op)}{src} | {val} | {state} | {badges} |"
            )
        lines.append("")

    lines.append("## Notes without proposed changes")
    lines.append("")
    lines.append("| note | expression | reason |")
    lines.append("|---|---|---|")
    for note_id in sorted(plan.reasons):
        record = records.get(note_id)
        expr = record.get("Expression") if record else "?"
        lines.append(
            f"| {note_id} | {_plain(expr or '(sentence card)', 40)} | {plan.reasons[note_id]} |"
        )
    lines.append("")
    return "\n".join(lines)
