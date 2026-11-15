"""Tests for plan.py — safety invariants."""

from __future__ import annotations

from test_golden_scene import CFG, CHILD, CHILD_ID, PARENT, PARENT_ID

from mining_fixer.matching import NoteRecord
from mining_fixer.normalize import strip_renderable
from mining_fixer.plan import (
    OP_ADD_TAGS,
    OP_BOLD_CLOZE_WORD,
    OP_EXPAND_SENTENCE,
    OP_FILL,
    OP_REPLACE_SOURCE,
    PLAN_VERSION,
    _retarget_bold,
    build_plan,
    scope_from_selection,
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
            assert w.op in (
                OP_REPLACE_SOURCE,
                OP_EXPAND_SENTENCE,
                OP_BOLD_CLOZE_WORD,
                OP_ADD_TAGS,
            ), w.field


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
    # A card that is already complete (bold present, nothing empty) is an
    # honest miss with a reason and no writes.
    f = dict(CHILD.fields)
    f["Sentence"] = "先生は今 <b>診察</b>中ですので➡"
    c = rec(CHILD.note_id, f, tags=("yomitan",))
    plan = build_plan([c], CFG, scope_note_ids=[CHILD.note_id])
    assert plan.reasons.get(CHILD.note_id) in ("no-parent-that-fills", "nothing-to-fill")
    assert not plan.writes


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


def test_add_tags_union_from_default_checked_sources():
    # The user's own example: 診察 (yomitan) fed by 至急 (asbplayer+yomitan)
    # must end up with both tags — and nothing removed.
    plan = build_plan([PARENT, CHILD], CFG, scope_note_ids=[CHILD_ID])
    rows = [w for w in plan.writes if w.note_id == CHILD_ID and w.op == OP_ADD_TAGS]
    assert len(rows) == 1
    row = rows[0]
    assert row.old_value == "yomitan"
    assert row.new_value == "asbplayer yomitan"
    assert row.default_checked
    assert "tags-union-never-removes" in row.badges
    added = set(row.new_value.split()) - set(row.old_value.split())
    assert added == {"asbplayer"}
    assert set(row.new_value.split()) >= set(row.old_value.split())


def test_add_tags_filters_control_tags():
    # Anki control tags and this tool's own tags never propagate.
    p = rec(
        PARENT.note_id,
        dict(PARENT.fields),
        tags=("asbplayer", "yomitan", "marked", "leech", "no-autofill", "auto-filled"),
    )
    plan = build_plan([p, CHILD], CFG, scope_note_ids=[CHILD.note_id])
    rows = [w for w in plan.writes if w.note_id == CHILD.note_id and w.op == OP_ADD_TAGS]
    assert rows and rows[0].new_value == "asbplayer yomitan"


def test_add_tags_skipped_when_target_already_has_all_tags():
    child = rec(CHILD.note_id, dict(CHILD.fields), tags=("asbplayer", "yomitan"))
    plan = build_plan([PARENT, child], CFG, scope_note_ids=[CHILD.note_id])
    assert not [w for w in plan.writes if w.op == OP_ADD_TAGS]


def test_add_tags_needs_default_checked_writes():
    # Sources of UNCHECKED writes contribute nothing: a card the plan does
    # not act on has not earned tag authority.
    p = rec(PARENT.note_id, dict(PARENT.fields), tags=("asbplayer", "yomitan"))
    child = dict(CHILD.fields)
    child["Sentence Audio"] = " [sound:have.webm] "
    child["Picture"] = '<img src="have.jpeg">'
    child["Source"] = "Dr. Rintaro Episode 6.mp4 (20m19s)"  # not a blob
    child["Sentence (furigana)"] = ""
    child["cloze-prefix"] = ""  # fragment unrecoverable -> guarded expansion
    child["cloze-body"] = ""
    child["cloze-suffix"] = ""
    c = rec(CHILD.note_id, child, tags=("yomitan",))
    plan = build_plan([p, c], CFG, scope_note_ids=[CHILD.note_id])
    rows = [w for w in plan.writes if w.note_id == CHILD.note_id]
    assert rows and all(not w.default_checked for w in rows)
    assert not [w for w in plan.writes if w.op == OP_ADD_TAGS]


def test_bold_repair_exact_tier():
    # The cloze body occurs exactly once, unbolded: wrap it.
    f = dict(CHILD.fields)
    f["Sentence"] = "先生は今 診察中ですので➡"
    c = rec(CHILD.note_id, f, tags=("yomitan",))
    plan = build_plan([c], CFG, scope_note_ids=[CHILD.note_id])
    bold = [w for w in plan.writes if w.op == OP_BOLD_CLOZE_WORD]
    assert len(bold) == 1
    assert bold[0].new_value == "先生は今 <b>診察</b>中ですので➡"
    assert "bold-added-to-cloze-word" in bold[0].badges
    assert bold[0].default_checked
    assert strip_renderable(bold[0].new_value) == strip_renderable(bold[0].old_value)


def test_bold_repair_surface_form():
    # 鬱病-shaped: cloze-* hold dictionary-entry text, the sentence spells
    # the leading kanji as kana (うつ病, exactly once) -> inferred tier.
    f = dict(CHILD.fields)
    f["Expression"] = "鬱病"
    f["reading"] = "うつびょう"
    f["cloze-prefix"] = "うつ‐びょう【"
    f["cloze-body"] = "鬱病"
    f["cloze-suffix"] = "】〔―ビヤウ〕"
    f["Sentence"] = "母は うつ病にかかってたんです｡"
    c = rec(CHILD.note_id, f, tags=("yomitan",))
    plan = build_plan([c], CFG, scope_note_ids=[CHILD.note_id])
    bold = [w for w in plan.writes if w.op == OP_BOLD_CLOZE_WORD]
    assert len(bold) == 1
    assert bold[0].new_value == "母は <b>うつ病</b>にかかってたんです｡"
    assert "bold-added-to-surface-form" in bold[0].badges
    assert strip_renderable(bold[0].new_value) == strip_renderable(bold[0].old_value)


def test_bold_repair_ambiguous_not_guessed():
    # Two occurrences of the tested word: never guess which to bold.
    f = dict(CHILD.fields)
    f["Sentence"] = "診察の先生は今 診察中ですので➡"
    c = rec(CHILD.note_id, f, tags=("yomitan",))
    plan = build_plan([c], CFG, scope_note_ids=[CHILD.note_id])
    assert not [w for w in plan.writes if w.op == OP_BOLD_CLOZE_WORD]
    assert any("occurs 2 times" in w for w in plan.warnings)


def test_bold_repair_with_br_markup():
    # Regression: "<b" in sentence matches <br> — the build data is full of
    # <br>, which silently disabled every repair. Bold-tag detection must
    # ignore line-break markup.
    f = dict(CHILD.fields)
    f["Sentence"] = "母は うつ病に<br>かかってたんです｡"
    f["Expression"] = "鬱病"
    f["reading"] = "うつびょう"
    f["cloze-body"] = "鬱病"
    c = rec(CHILD.note_id, f, tags=("yomitan",))
    plan = build_plan([c], CFG, scope_note_ids=[CHILD.note_id])
    bold = [w for w in plan.writes if w.op == OP_BOLD_CLOZE_WORD]
    assert len(bold) == 1
    assert bold[0].new_value == "母は <b>うつ病</b>に<br>かかってたんです｡"


def test_bold_repair_skipped_when_expansion_queued():
    # The golden child's Sentence is queued for a checked scene expansion
    # that already carries the retargeted bold: no markup repair, no noise.
    plan = build_plan([PARENT, CHILD], CFG, scope_note_ids=[CHILD_ID])
    assert not [w for w in plan.writes if w.op == OP_BOLD_CLOZE_WORD]
    assert not any("no bold in Sentence" in w for w in plan.warnings)


def test_scope_from_selection_preserves_order_and_dedupes():
    # The Browser selection is a list of note ids; its order is the user's.
    scope, unknown = scope_from_selection([3, 1, 3, 9], {1, 2, 3})
    assert scope == [3, 1]
    assert unknown == [9]


def test_scope_from_selection_reports_every_unknown_id():
    scope, unknown = scope_from_selection([9, 8], set())
    assert scope == []
    assert unknown == [9, 8]


def test_explicit_scope_limits_targets_but_not_sources():
    # What the Browser selection relies on: only the selected notes are
    # targets, while every record stays eligible as a parent/word source.
    plan = build_plan([PARENT, CHILD], CFG, scope_note_ids=[CHILD_ID])
    assert {w.note_id for w in plan.writes} == {CHILD_ID}
    assert PARENT_ID not in plan.reasons


# --- source confidence (wrong-source protection) ---------------------


def scene(
    nid,
    sentence,
    *,
    expr="至急",
    reading="しきゅう",
    body="至急",
    audio=" [sound:asbp.webm] ",
    picture='<img src="asbp.jpeg">',
    translation="",
    source="Show Episode 1.mp4 (1m00s)",
    furigana="",
):
    return rec(
        nid,
        {
            "Expression": expr,
            "reading": reading,
            "Sentence": sentence,
            "Sentence Audio": audio,
            "Picture": picture,
            "Translation": translation,
            "Source": source,
            "Sentence (furigana)": furigana,
            "cloze-prefix": "先生は今 ",
            "cloze-body": body,
            "cloze-suffix": "中ですので",
        },
        tags=("asbplayer",),
    )


CHILD_SCENE = dict(
    expr="診察",
    reading="しんさつ",
    body="診察",
    audio="",
    picture="",
    source="blob:https://asbplayer/xyz",
)


def test_divergent_scene_sources_are_never_auto_checked():
    # Two unrelated parents both contain the fragment but would write
    # different payloads: picking either silently risks an unrelated card.
    child = scene(10_000_000, "先生は今 診察中ですので", **CHILD_SCENE)
    first = scene(
        10_000_000 + 60_000,
        "先生は今 診察中ですので 次の患者さんが",
        picture='<img src="a.jpeg">',
        audio=" [sound:a.webm] ",
    )
    second = scene(
        10_000_000 + 120_000,
        "先生は今 診察中ですので お待ちください",
        picture='<img src="b.jpeg">',
        audio=" [sound:b.webm] ",
    )
    plan = build_plan([child, first, second], CFG, scope_note_ids=[child.note_id])
    rows = [w for w in plan.writes if w.note_id == child.note_id]
    assert rows
    assert not any(w.default_checked for w in rows), [w.badges for w in rows]
    assert any("divergent-parents" in w.badges for w in rows)
    assert any("scene sources disagree" in warning for warning in plan.warnings)


def test_a_far_scene_source_is_left_unchecked():
    # Within the ±3-day search window, but far outside a mining session: the
    # match is suggested, never trusted automatically.
    child = scene(0, "先生は今 診察中ですので", **CHILD_SCENE)
    far = scene(30 * 3_600_000, "先生は今 診察中ですので 次の患者さん")
    plan = build_plan([child, far], CFG, scope_note_ids=[child.note_id])
    rows = [w for w in plan.writes if w.note_id == child.note_id]
    assert rows
    assert not any(w.default_checked for w in rows)
    assert any("far-from-source" in w.badges for w in rows)


def test_an_identical_sentence_is_trusted_even_when_far():
    # A byte-identical sentence verifies the source by itself.
    sentence = "先生は今 診察中ですので"
    child = scene(0, sentence, **CHILD_SCENE)
    twin = scene(30 * 3_600_000, sentence)
    plan = build_plan([child, twin], CFG, scope_note_ids=[child.note_id])
    rows = [w for w in plan.writes if w.note_id == child.note_id]
    assert rows
    assert all(w.default_checked for w in rows), [(w.field, w.badges) for w in rows]
