"""Tests for plan.py — safety invariants."""

from __future__ import annotations

from test_golden_scene import CFG, CHILD, CHILD_ID, PARENT, PARENT_ID

from matching import NoteRecord
from plan import (
    OP_EXPAND_SENTENCE,
    OP_FILL,
    OP_REPLACE_SOURCE,
    PLAN_VERSION,
    _retarget_bold,
    build_plan,
)


def rec(nid, fields, tags=()):
    return NoteRecord(note_id=nid, notetype_id=1, fields=fields, tags=frozenset(tags))


BASE = dict(CHILD.fields)


def test_plan_version_and_determinism():
    p1 = build_plan([PARENT, CHILD], CFG, scope_note_ids=[CHILD_ID])
    p2 = build_plan([PARENT, CHILD], CFG, scope_note_ids=[CHILD_ID])
    assert p1.version == PLAN_VERSION
    assert p1.writes == p2.writes
    ids = [(w.note_id, w.field, w.op) for w in p1.writes]
    assert ids == sorted(ids)


def test_never_overwrite_invariant():
    plan = build_plan([PARENT, CHILD], CFG, scope_note_ids=[CHILD_ID])
    for w in plan.writes:
        if w.op == OP_FILL:
            assert w.old_value == "", (w.field, w.new_value)


def test_replaces_only_approved_ops():
    plan = build_plan([PARENT, CHILD], CFG, scope_note_ids=[CHILD_ID])
    for w in plan.writes:
        if w.old_value:
            assert w.op in (OP_REPLACE_SOURCE, OP_EXPAND_SENTENCE), w.field


def test_expansion_guard_when_fragment_not_recoverable():
    child = dict(CHILD.fields)
    child["cloze-prefix"] = ""  # fragment no longer reconstructible
    child["cloze-body"] = ""
    child["cloze-suffix"] = ""
    c = rec(CHILD.note_id, child, tags=("yomitan",))
    plan = build_plan([PARENT, c], CFG, scope_note_ids=[CHILD.note_id])
    rows = [w for w in plan.writes if w.note_id == CHILD.note_id and w.field == "Sentence"]
    assert rows and rows[0].default_checked is False
    assert "fragment-not-recoverable" in rows[0].badges


def test_expansion_guard_when_anchor_not_unique():
    parent_f = dict(PARENT.fields)
    # scene text contains 診察 twice -> highlight ambiguous
    parent_f["Sentence"] = "[TEL] 診察の先生は今 診察中ですので➡代わりに診察します。"
    p = rec(PARENT.note_id, parent_f, tags=("asbplayer", "yomitan"))
    plan = build_plan([p, CHILD], CFG, scope_note_ids=[CHILD.note_id])
    rows = [w for w in plan.writes if w.note_id == CHILD.note_id and w.field == "Sentence"]
    assert rows and rows[0].default_checked is False


def test_furigana_fill_paired_with_guarded_expansion():
    # The expansion is guarded, so the furigana fill must ship unchecked too:
    # full-scene ruby under a fragment sentence is a broken card.
    child = dict(CHILD.fields)
    child["cloze-prefix"] = ""
    child["cloze-body"] = ""
    child["cloze-suffix"] = ""
    c = rec(CHILD.note_id, child, tags=("yomitan",))
    plan = build_plan([PARENT, c], CFG, scope_note_ids=[CHILD.note_id])
    fills = [
        w for w in plan.writes if w.note_id == CHILD.note_id and w.field == "Sentence (furigana)"
    ]
    assert fills and fills[0].op == OP_FILL
    assert fills[0].default_checked is False
    assert "paired-with-expansion" in fills[0].badges


def test_atomic_furigana_replace_when_both_have_it():
    # Child carries fragment ruby; the parent has scene ruby. The replace is
    # atomic with the Sentence expansion and carries its own badge.
    child = dict(CHILD.fields)
    child_furigana = "先生[せんせい]は今 診察[しんさつ]中ですので➡"
    child["Sentence (furigana)"] = child_furigana
    c = rec(CHILD.note_id, child, tags=("yomitan",))
    plan = build_plan([PARENT, c], CFG, scope_note_ids=[CHILD.note_id])
    rows = {
        w.field: w for w in plan.writes if w.note_id == CHILD.note_id and w.op == OP_EXPAND_SENTENCE
    }
    assert set(rows) == {"Sentence", "Sentence (furigana)"}
    furi = rows["Sentence (furigana)"]
    assert furi.old_value == child_furigana
    assert furi.new_value == PARENT.get("Sentence (furigana)")
    assert furi.default_checked
    assert "replaces-fragment-furigana" in furi.badges


def test_stale_furigana_blocks_default_checked():
    # Parent lacks furigana: expanding would leave the child's fragment ruby
    # stale under the scene text -> expansion ships unchecked.
    parent_f = dict(PARENT.fields)
    parent_f["Sentence (furigana)"] = ""
    p = rec(PARENT.note_id, parent_f, tags=("asbplayer", "yomitan"))
    child = dict(CHILD.fields)
    child["Sentence (furigana)"] = "先生[せんせい]は今 診察[しんさつ]中ですので➡"  # fragment ruby
    c = rec(CHILD.note_id, child, tags=("yomitan",))
    plan = build_plan([p, c], CFG, scope_note_ids=[CHILD.note_id])
    rows = [w for w in plan.writes if w.note_id == CHILD.note_id and w.field == "Sentence"]
    assert rows and rows[0].default_checked is False
    assert "stale-fragment-furigana-risk" in rows[0].badges


def test_scene_furigana_filled_when_parent_has_it():
    parent_f = dict(PARENT.fields)
    parent_f["Sentence (furigana)"] = (
        "先生[せんせい]は今 診察[しんさつ]中ですので➡代わりに伺[うかが]います"
    )
    p = rec(PARENT.note_id, parent_f, tags=("asbplayer", "yomitan"))
    plan = build_plan([p, CHILD], CFG, scope_note_ids=[CHILD.note_id])
    fills = [
        w for w in plan.writes if w.note_id == CHILD.note_id and w.field == "Sentence (furigana)"
    ]
    assert fills and fills[0].op == OP_FILL and fills[0].default_checked


def test_optout_tag_blocks_target():
    child = dict(CHILD.fields)
    c = rec(CHILD.note_id, child, tags=("yomitan", "no-autofill"))
    plan = build_plan([PARENT, c], CFG, scope_note_ids=[CHILD.note_id])
    assert plan.reasons.get(CHILD.note_id) == "opted-out"
    assert not plan.writes


def test_unfixable_reason_reported():
    # no audio-bearing parent anywhere near -> honest miss
    plan = build_plan([CHILD], CFG, scope_note_ids=[CHILD.note_id])
    assert plan.reasons.get(CHILD.note_id) in ("no-parent-that-fills", "nothing-to-fill")


def test_translation_fill_and_notes_optin():
    parent_f = dict(PARENT.fields)
    parent_f["Translation"] = "The doctor is examining a patient now."
    parent_f["Notes"] = "grammar: ~て form context"
    p = rec(PARENT.note_id, parent_f, tags=("asbplayer", "yomitan"))
    plan = build_plan([p, CHILD], CFG, scope_note_ids=[CHILD.note_id])
    by_field = {w.field: w for w in plan.writes if w.note_id == CHILD.note_id}
    assert by_field["Translation"].default_checked
    assert by_field["Notes"].default_checked is False  # opt-in only


def test_retarget_bold_moves_bold_to_child_word():
    scene = "[TEL](ベル)<br><b>至急</b> 日野先生と話したいと｡<br>先生は今 診察中ですので➡"
    value, badge = _retarget_bold(scene, "至急", "診察")
    assert value == "[TEL](ベル)<br>至急 日野先生と話したいと｡<br>先生は今 <b>診察</b>中ですので➡"
    assert badge == "bold-retargeted-to-cloze-word"


def test_retarget_bold_keeps_value_when_bold_on_other_word():
    scene = "彼は<b>天才</b>だ。<br>先生は今 診察中ですので➡"
    value, badge = _retarget_bold(scene, "至急", "診察")
    assert value == scene  # untouched: guessing would be worse than keeping
    assert badge == "stale-parent-bold"


def test_retarget_bold_noop_when_child_already_bold():
    scene = "先生は今 <b>診察</b>中ですので➡"
    value, badge = _retarget_bold(scene, "", "診察")
    assert value == scene
    assert badge is None


def test_expansion_pairing_never_mixes_parents():
    # The whole scene write group carries one source note id; values must
    # all come from the same parent (never mix ruby from a second parent).
    plan = build_plan([PARENT, CHILD], CFG, scope_note_ids=[CHILD_ID])
    scene_rows = [
        w
        for w in plan.writes
        if w.note_id == CHILD_ID and w.group_id and w.group_id.startswith("scene-")
    ]
    assert scene_rows
    assert {w.source_note_id for w in scene_rows} == {PARENT_ID}
