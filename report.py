"""Markdown report rendering for a plan run.

Pure module: no anki/aqt imports.
"""

from __future__ import annotations

from fieldconfig import sound_files
from matching import NoteRecord
from plan import (
    OP_ADD_TAGS,
    OP_BOLD_CLOZE_WORD,
    OP_EXPAND_SENTENCE,
    OP_FILL,
    OP_REPLACE_SOURCE,
    Plan,
)

__all__ = ["render_markdown"]

_OP_LABEL = {
    OP_FILL: "fill",
    OP_REPLACE_SOURCE: "replace blob Source",
    OP_EXPAND_SENTENCE: "expand to scene sentence",
    OP_BOLD_CLOZE_WORD: "bold markup (text unchanged)",
    OP_ADD_TAGS: "add tags (never removes)",
}


def _plain(value: str, limit: int = 160) -> str:
    text = value or ""
    text = text.replace("\n", " ⏎ ")
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text.replace("|", "\\|")


def render_markdown(plan: Plan, records: dict[int, NoteRecord], run_meta: dict) -> str:
    by_note: dict[int, list] = {}
    for w in plan.writes:
        by_note.setdefault(w.note_id, []).append(w)

    checked = [w for w in plan.writes if w.default_checked]
    lines: list[str] = []
    lines.append("# Mining Backfill — run report")
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
            if w.op == OP_EXPAND_SENTENCE:
                val = f"{_plain(w.old_value, 60)} → {_plain(w.new_value, 90)}"
            elif w.op == OP_ADD_TAGS:
                added = " ".join(sorted(set(w.new_value.split()) - set(w.old_value.split())))
                val = f"{_plain(w.old_value, 40) or '(no tags)'} + {_plain(added, 40)}"
            if w.field == "Sentence Audio" or w.field == "Word Audio":
                val = ", ".join(sound_files(w.new_value)) or _plain(w.new_value, 60)
            state = "✓" if w.default_checked else "—"
            badges = ", ".join(w.badges) or "-"
            lines.append(
                f"| {w.field} | {_OP_LABEL.get(w.op, w.op)}{src} | {val} | {state} | {badges} |"
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
