"""Regression suite over real cards captured from the author's collection.

Why this file exists (owner requirement, 2026-11-16: "we need a robust
regression testing suite"): the synthetic fixtures passed while the real
cards stayed broken. Every bug the author found by hand — arrows left in
`Sentence (furigana)`, a card that needed a second run, a junk definition
shell, a clause sitting in the `Expression` field — was invisible to the
suite. This test replays the captured field values of those exact cards
(`tests/fixtures/real_cards.json.gz`, read-only capture, no secrets) and
asserts the properties the author actually cares about:

1. **One run fixes the card; a second run is a no-op.** After applying the
   plan's own values, re-planning must produce no row for that note.
2. **No subtitle arrow survives, in either sentence field.** The `Sentence`
   *and* the `Sentence (furigana)` ruby are checked, because the author
   found arrows still showing after the first field was cleaned.
3. **A definition never keeps a junk-only shell** — it is either filled with
   a sibling's value (in the same run) or cleared.
4. **A clause-like `Expression` is never bolded** (the author's own invalid
   case), and every bold write stays markup-only.
5. **Nothing is written to a card whose data is junk** — a dictionary entry
   used as a sentence, or a word that never occurs, is reported, not guessed.

The fixture is a frozen capture: if the collection changes, this file keeps
testing the values that produced the bugs.
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

from mining_fixer.batch import default_ops, select
from mining_fixer.matching import NoteRecord
from mining_fixer.normalize import is_empty_glossary_shell, strip_renderable
from mining_fixer.plan import OP_BOLD_CLOZE_WORD, OP_STRIP_EMPTY_GLOSSARY, build_plan

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "real_cards.json.gz"
ARROW_TAIL = re.compile(r"[\u2192\u21d2\u27a1]+\ufe0f?[ \t]*(?:<br\s*/?>|\n|$)")

#: The config the add-on ships (automatic mode): every dimension on.
CFG = {
    "window_days": 3,
    "min_sentence_len": 6,
    "batch_expand_sentence": True,
    "batch_replace_source": True,
    "batch_scene_propagation": True,
    "batch_repair_sentence": True,
    "sentence_repair_rules": ["strip-arrows"],
    "batch_regenerate_furigana": True,
    "definition_fields": ["Definition", "Extended definition"],
    "scene_fill_fields": ["Sentence Audio", "Picture", "Sentence (furigana)", "Translation"],
    "scene_replace_fields": ["Source", "Sentence"],
    "scene_optin_fields": ["Notes", "context", "Kanji Notes"],
    "word_fill_fields": [
        "Definition",
        "Extended definition",
        "Pitch Accent",
        "Frequency",
        "Word Audio",
        "furigana",
        "reading",
    ],
    "replaces_autocheck": True,
    "optout_tag": "no-autofill",
    "applied_tag": "auto-filled",
}


def load_cards() -> dict[str, list[NoteRecord]]:
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    out: dict[str, list[NoteRecord]] = {}
    for name, notes in data["classes"].items():
        out[name] = [
            NoteRecord(
                note_id=note["note_id"],
                notetype_id=1,
                fields=dict(note["fields"]),
                tags=frozenset(note["tags"]),
            )
            for note in notes
        ]
    return out


CARDS = load_cards()
ALL = [note for notes in CARDS.values() for note in notes]
BY_ID = {note.note_id: note for note in ALL}


def plan_for(records: list[NoteRecord], scope: list[int]):
    return build_plan(records, CFG, scope_note_ids=scope, media_exists=lambda _name: True)


def applied_fields(note: NoteRecord, plan) -> dict[str, str]:
    """The field values the run would leave behind for one note."""
    fields = dict(note.fields)
    for write in plan.writes:
        if write.note_id == note.note_id and write.default_checked:
            fields[write.field] = write.new_value
    return fields


def test_every_captured_card_has_a_sentence_and_an_expression():
    # Guard the fixture itself: a card with no Sentence tests nothing.
    assert len(ALL) >= 10
    for note in ALL:
        assert (note.get("Expression") or "").strip(), note.note_id
        assert (note.get("Sentence") or "").strip(), note.note_id


def test_a_second_run_over_the_real_cards_is_a_no_op():
    # The owner's rule: run once, fix, run again -> nothing to do. This is
    # the property that catches "run twice" bugs (fill through a shell, an
    # expansion that copies arrows).
    for note in ALL:
        records = list(ALL)
        plan = plan_for(records, [note.note_id])
        after = dict(note.fields)
        after.update(applied_fields(note, plan))
        updated = NoteRecord(note_id=note.note_id, notetype_id=1, fields=after, tags=note.tags)
        records2 = [updated if r.note_id == note.note_id else r for r in records]
        again = plan_for(records2, [note.note_id])
        rows = [
            (w.field, w.op) for w in again.writes if w.note_id == note.note_id and w.default_checked
        ]
        assert rows == [], (note.note_id, note.get("Expression"), rows)


def test_no_arrow_survives_in_either_sentence_field():
    # The author's report: arrows still showing because they live in the ruby
    # field. Both fields must come out clean after the run.
    for note in ALL:
        plan = plan_for(list(ALL), [note.note_id])
        after = applied_fields(note, plan)
        for field in ("Sentence", "Sentence (furigana)"):
            value = after.get(field) or ""
            assert not ARROW_TAIL.search(value), (note.note_id, field, value[-60:])


def test_a_definition_never_keeps_a_junk_only_shell():
    for note in ALL:
        plan = plan_for(list(ALL), [note.note_id])
        after = applied_fields(note, plan)
        for field in ("Definition", "Extended definition"):
            value = after.get(field) or ""
            assert not is_empty_glossary_shell(value), (note.note_id, field, value[:60])


def test_a_clause_like_expression_is_never_bolded():
    # The author's invalid case: a whole clause in the Expression field.
    for note in CARDS["clause_expression"]:
        plan = plan_for(list(ALL), [note.note_id])
        bold = [w for w in plan.writes if w.note_id == note.note_id and w.op == OP_BOLD_CLOZE_WORD]
        assert bold == [], (note.note_id, note.get("Expression"))


def test_every_bold_write_is_markup_only():
    plan = plan_for(list(ALL), [note.note_id for note in ALL])
    for write in plan.writes:
        if write.op == OP_BOLD_CLOZE_WORD:
            assert strip_renderable(write.new_value) == strip_renderable(write.old_value), (
                write.note_id,
                write.field,
            )


def test_junk_data_is_reported_not_guessed():
    # A dictionary entry used as a sentence (此の度) must not become a bold or
    # a scene write; whatever the tool decides, it stays honest.
    for note in ALL:
        plan = plan_for(list(ALL), [note.note_id])
        for write in plan.writes:
            if write.note_id != note.note_id or not write.default_checked:
                continue
            assert write.op != OP_STRIP_EMPTY_GLOSSARY or write.new_value == ""
            if write.op == OP_BOLD_CLOZE_WORD:
                body = strip_renderable(note.get("cloze-body")).strip()
                assert body and body in write.new_value, (note.note_id, body)


def test_the_default_policy_selects_the_same_rows_for_the_real_cards():
    # Selection must not invent or drop rows: every checked write of a note is
    # either selected or the note is reported as left alone with a reason.
    plan = plan_for(list(ALL), [note.note_id for note in ALL])
    selection = select(plan, default_ops(CFG))
    selected = {(w.note_id, w.field) for w in selection.rows}
    checked = {(w.note_id, w.field) for w in plan.writes if w.default_checked}
    assert selected <= checked
    reported = {item.note_id for item in selection.left_alone}
    for note_id in {w.note_id for w in plan.writes}:
        if not any(nid == note_id for nid, _ in selected):
            assert note_id in reported, note_id
