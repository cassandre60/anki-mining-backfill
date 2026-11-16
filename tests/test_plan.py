"""Tests for plan.py — safety invariants."""

from __future__ import annotations

from test_golden_scene import CFG, CHILD, CHILD_ID, PARENT, PARENT_ID

from mining_fixer.matching import NoteRecord
from mining_fixer.normalize import strip_renderable
from mining_fixer.plan import (
    FURIGANA_FIELD,
    OP_ADD_TAGS,
    OP_BOLD_CLOZE_WORD,
    OP_EXPAND_SENTENCE,
    OP_FILL,
    OP_REGENERATE_FURIGANA,
    OP_REPAIR_EXPRESSION,
    OP_REPAIR_SENTENCE,
    OP_REPLACE_SOURCE,
    OP_STRIP_EMPTY_GLOSSARY,
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
                OP_REPAIR_SENTENCE,
                OP_REGENERATE_FURIGANA,
                OP_REPAIR_EXPRESSION,
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


# --- bold from expression (BULK_FIX.md dimension 6, slice shipped part) ------


def test_bold_repair_uses_the_expression_when_the_cloze_body_is_missing():
    # The mined fragment is junk or missing; the Expression itself occurs
    # once in the sentence — bold it (前人未到-shaped card).
    f = dict(CHILD.fields)
    f["Expression"] = "前人未到"
    f["reading"] = "ぜんじんみとう"
    f["furigana"] = ""
    f["cloze-prefix"] = ""
    f["cloze-body"] = ""
    f["cloze-suffix"] = ""
    f["Sentence"] = "ついに 前人未到の世界一周を<br>達成した。"
    c = rec(CHILD.note_id, f, tags=("yomitan",))
    plan = build_plan([c], CFG, scope_note_ids=[CHILD.note_id])
    bold = [w for w in plan.writes if w.op == OP_BOLD_CLOZE_WORD]
    assert len(bold) == 1
    assert "<b>前人未到</b>" in bold[0].new_value
    assert "bold-added-to-expression" in bold[0].badges
    assert strip_renderable(bold[0].new_value) == strip_renderable(bold[0].old_value)


def test_bold_repair_refuses_a_clause_like_expression():
    # The invalid card: the Expression field holds a whole clause that also
    # occurs verbatim in the sentence — bolding it would mask the sentence.
    f = dict(CHILD.fields)
    f["Expression"] = "漢字は読めるようになりたいかな"
    f["reading"] = ""
    f["furigana"] = ""
    f["cloze-prefix"] = ""
    f["cloze-body"] = ""
    f["cloze-suffix"] = ""
    f["Sentence"] = "漢字は読めるようになりたいかな<br>漢字読めないの?"
    c = rec(CHILD.note_id, f, tags=("yomitan",))
    plan = build_plan([c], CFG, scope_note_ids=[CHILD.note_id])
    assert not [w for w in plan.writes if w.op == OP_BOLD_CLOZE_WORD]
    assert any("not word-like enough" in w for w in plan.warnings)


def test_bold_repair_skips_an_over_long_word_expression():
    # The gate is conservative: a long legitimate word is skipped too, not
    # guessed (reported only when it occurs verbatim).
    f = dict(CHILD.fields)
    f["Expression"] = "ベーコンチーズバーガー"
    f["reading"] = ""
    f["furigana"] = ""
    f["cloze-prefix"] = ""
    f["cloze-body"] = ""
    f["cloze-suffix"] = ""
    f["Sentence"] = "ベーコンチーズバーガーをください"
    c = rec(CHILD.note_id, f, tags=("yomitan",))
    plan = build_plan([c], CFG, scope_note_ids=[CHILD.note_id])
    assert not [w for w in plan.writes if w.op == OP_BOLD_CLOZE_WORD]
    assert any("not word-like enough" in w for w in plan.warnings)


def test_bold_repair_skips_a_listening_tag_card():
    # The template's tag path: listening + usable audio hides the sentence.
    f = dict(CHILD.fields)
    f["Sentence"] = "先生は今 診察中ですので"
    f["Sentence Audio"] = " [sound:scene.webm] "
    c = rec(CHILD.note_id, f, tags=("yomitan", "listening"))
    plan = build_plan([c], CFG, scope_note_ids=[CHILD.note_id])
    assert not [w for w in plan.writes if w.op == OP_BOLD_CLOZE_WORD]


def test_bold_repair_skips_the_no_gloss_listening_shape():
    # The template's shape path: no Definition/Extended definition/Frequency
    # and Sentence Audio present -> audio-only front, nothing to bold.
    f = dict(CHILD.fields)
    f["Sentence"] = "先生は今 診察中ですので"
    f["Definition"] = ""
    f["Extended definition"] = ""
    f["Frequency"] = ""
    f["Sentence Audio"] = " [sound:scene.webm] "
    c = rec(CHILD.note_id, f, tags=("yomitan",))
    plan = build_plan([c], CFG, scope_note_ids=[CHILD.note_id])
    assert not [w for w in plan.writes if w.op == OP_BOLD_CLOZE_WORD]


def test_frequency_without_glosses_is_not_listening():
    # The template deliberately shows the normal sentence for those cards.
    f = dict(CHILD.fields)
    f["Sentence"] = "先生は今 診察中ですので"
    f["Definition"] = ""
    f["Extended definition"] = ""
    f["Sentence Audio"] = " [sound:scene.webm] "
    c = rec(CHILD.note_id, f, tags=("yomitan",))
    plan = build_plan([c], CFG, scope_note_ids=[CHILD.note_id])
    bold = [w for w in plan.writes if w.op == OP_BOLD_CLOZE_WORD]
    assert len(bold) == 1


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
    scene_rows = [w for w in rows if w.field != "Sentence"]
    assert not any(w.default_checked for w in scene_rows), [w.badges for w in scene_rows]
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
    scene_rows = [w for w in rows if w.field != "Sentence"]
    assert not any(w.default_checked for w in scene_rows)
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


# --- subtitle-noise repair (bulk-fix dimension 2, QUALITY Q-D10) ------------

REPAIR_CFG = {**CFG, "sentence_repair_rules": ["strip-arrows"]}


def test_a_configured_repair_emits_a_checked_write_with_rule_badges():
    target = rec(
        1,
        {
            "Expression": "見出し",
            "reading": "みだし",
            "furigana": "",
            "cloze-body": "",
            "Sentence": "あしたの朝刊の<b>見出し</b>は<br>こうニャ！➡",
        },
    )
    plan = build_plan([target], REPAIR_CFG, scope_note_ids=[1])
    repair_writes = [w for w in plan.writes if w.op == OP_REPAIR_SENTENCE]
    assert len(repair_writes) == 1
    write = repair_writes[0]
    assert write.op == OP_REPAIR_SENTENCE
    assert write.field == "Sentence"
    assert write.new_value == "あしたの朝刊の<b>見出し</b>は<br>こうニャ！"
    assert write.old_value == "あしたの朝刊の<b>見出し</b>は<br>こうニャ！➡"
    assert write.default_checked is True
    assert write.badges == ("strip-arrows",)


def test_repair_is_off_without_rules():
    target = rec(
        1,
        {"Expression": "", "reading": "", "furigana": "", "cloze-body": "", "Sentence": "前<br>後"},
    )
    plan = build_plan([target], CFG, scope_note_ids=[1])
    assert not any(w.op == OP_REPAIR_SENTENCE for w in plan.writes)


def test_repair_skips_a_note_whose_expansion_is_queued():
    # The fragment "見<br>出しはこうニャ！➡" would be repaired — but the scene
    # expansion already owns the field, so the noise repair stays out.
    parent = scene(9, "あしたの朝刊の見出しはこうニャ！")
    child = rec(
        1,
        {
            **scene(
                1,
                "見<br>出しはこうニャ！➡",
                expr="見出し",
                reading="みだし",
                body="見出し",
                audio="",
                picture="",
                source="asbplayer://blob",
            ).fields,
            "cloze-prefix": "",
            "cloze-body": "見出し",
            "cloze-suffix": "はこうニャ！",
        },
    )
    plan = build_plan([parent, child], REPAIR_CFG, scope_note_ids=[child.note_id])
    assert any(w.op == OP_EXPAND_SENTENCE and w.field == "Sentence" for w in plan.writes), [
        (w.op, w.field) for w in plan.writes
    ]
    assert not any(w.op == OP_REPAIR_SENTENCE for w in plan.writes)


def test_repair_skips_a_note_whose_bold_repair_is_queued():
    # Bold repair owns the field first; the noise repair must not fight it.
    # (The tail arrow would be repairable — that is the point of the test.)
    target = scene(
        1,
        "今のままじゃ<br>あいつらに顔向けできねえよ➡",
        expr="顔向け",
        reading="かおむけ",
        body="顔向け",
        audio="",
        picture="",
    )
    plan = build_plan([target], REPAIR_CFG, scope_note_ids=[target.note_id])
    sentence_writes = [w for w in plan.writes if w.field == "Sentence"]
    assert [w.op for w in sentence_writes] == [OP_BOLD_CLOZE_WORD]


def test_repair_is_dropped_when_the_tested_word_occurrence_would_change():
    # Under arrows-only rules the repair can change the tested word's
    # occurrence count only when that word is itself an arrow glyph
    # (synthetic by necessity — real arrows are never the mined word). The
    # guard stays as defense-in-depth for future rules (Q-D10).
    target = rec(
        1,
        {
            "Expression": "",
            "reading": "",
            "furigana": "",
            "Sentence": "見出し<b>➡</b>➡",
            "cloze-body": "➡",
        },
    )
    plan = build_plan([target], REPAIR_CFG, scope_note_ids=[1])
    assert not any(w.op == OP_REPAIR_SENTENCE for w in plan.writes)
    assert any("sentence repair skipped" in warning for warning in plan.warnings)


def test_unknown_repair_rules_warn_and_the_rest_still_runs():
    target = rec(
        1,
        {
            "Expression": "",
            "reading": "",
            "furigana": "",
            "cloze-body": "",
            "Sentence": "前➡<br>後",
        },
    )
    cfg = {**CFG, "sentence_repair_rules": ["strip-arrows", "nonsense"]}
    plan = build_plan([target], cfg, scope_note_ids=[1])
    assert any("unknown sentence_repair_rules ignored: nonsense" in w for w in plan.warnings)
    assert [w.op for w in plan.writes if w.op == OP_REPAIR_SENTENCE] == [OP_REPAIR_SENTENCE]
    write = next(w for w in plan.writes if w.op == OP_REPAIR_SENTENCE)
    assert write.new_value == "前<br>後"


# --- furigana regeneration (bulk-fix dimension 3, QUALITY Q-D11) -------------

REGEN_CFG = {**CFG, "batch_regenerate_furigana": True}


def _regen_card(nid, sentence, furigana=""):
    return rec(
        nid,
        {
            "Expression": "",
            "reading": "",
            "furigana": "",
            "Sentence": sentence,
            "Sentence (furigana)": furigana,
        },
    )


def _generator(value, calls=None):
    def generate(sentence):
        if calls is not None:
            calls.append(sentence)
        return value

    return generate


def test_regeneration_emits_a_checked_write_with_badges():
    target = _regen_card(1, "見出しはこうニャ！", furigana="見出しはこうニャ！")
    plan = build_plan(
        [target],
        REGEN_CFG,
        scope_note_ids=[1],
        furigana_generator=_generator("見出[みだ]しはこうニャ！"),
    )
    writes = [w for w in plan.writes if w.op == OP_REGENERATE_FURIGANA]
    assert len(writes) == 1
    write = writes[0]
    assert write.field == FURIGANA_FIELD
    assert write.old_value == "見出しはこうニャ！"
    assert write.new_value == "見出[みだ]しはこうニャ！"
    assert write.default_checked is True
    assert write.badges == ("furigana-regenerated",)


def test_regeneration_is_off_by_default():
    target = _regen_card(1, "見出しはこうニャ！", furigana="見出しはこうニャ！")
    plan = build_plan(
        [target],
        CFG,
        scope_note_ids=[1],
        furigana_generator=_generator("見出[みだ]しはこうニャ！"),
    )
    assert not any(w.op == OP_REGENERATE_FURIGANA for w in plan.writes)
    assert not any("furigana" in warning for warning in plan.warnings)


def test_regeneration_is_a_noop_when_the_ruby_already_matches():
    target = _regen_card(1, "見出しはこうニャ！", furigana="見出[みだ]しはこうニャ！")
    plan = build_plan(
        [target],
        REGEN_CFG,
        scope_note_ids=[1],
        furigana_generator=_generator("見出[みだ]しはこうニャ！"),
    )
    assert not any(w.op == OP_REGENERATE_FURIGANA for w in plan.writes)
    assert not any("furigana" in warning for warning in plan.warnings)


def test_regeneration_warns_once_when_no_generator_is_available():
    plan = build_plan(
        [_regen_card(1, "見出しはこうニャ！"), _regen_card(2, "見出しはこうニャ！")],
        REGEN_CFG,
        scope_note_ids=[1, 2],
    )
    assert not any(w.op == OP_REGENERATE_FURIGANA for w in plan.writes)
    assert sum("no furigana generator" in w for w in plan.warnings) == 1


def test_regeneration_runs_on_the_sentence_the_plan_leaves_behind():
    # The repair removes the tail arrow; the ruby must describe THAT text
    # (BULK_FIX.md: sentence repair precedes furigana generation).
    calls: list[str] = []
    target = _regen_card(1, "見出しはこうニャ！➡", furigana="見出しはこうニャ！")
    cfg = {**REGEN_CFG, "sentence_repair_rules": ["strip-arrows"]}
    plan = build_plan(
        [target],
        cfg,
        scope_note_ids=[1],
        furigana_generator=_generator("見出[みだ]しはこうニャ！", calls=calls),
    )
    assert calls == ["見出しはこうニャ！"]
    assert any(w.op == OP_REPAIR_SENTENCE for w in plan.writes)
    write = next(w for w in plan.writes if w.op == OP_REGENERATE_FURIGANA)
    assert write.badges == ("furigana-regenerated", "after-sentence-write")


def test_regeneration_defers_to_a_queued_scene_fill_of_the_same_field():
    # The scene fill already owns Sentence (furigana) for this child.
    parent = scene(
        9,
        "あしたの朝刊の見出しはこうニャ！",
        furigana="あしたの朝刊の見出し[みだし]はこうニャ！",
    )
    child = rec(
        1,
        {
            **scene(
                1,
                "見<br>出しはこうニャ！➡",
                expr="見出し",
                reading="みだし",
                body="見出し",
                audio="",
                picture="",
                source="asbplayer://blob",
            ).fields,
            "cloze-prefix": "",
            "cloze-body": "見出し",
            "cloze-suffix": "はこうニャ！",
        },
    )
    plan = build_plan(
        [parent, child],
        REGEN_CFG,
        scope_note_ids=[child.note_id],
        furigana_generator=_generator("見出[みだ]しはこうニャ！"),
    )
    assert any(w.op == OP_FILL and w.field == FURIGANA_FIELD for w in plan.writes)
    assert not any(w.op == OP_REGENERATE_FURIGANA for w in plan.writes)


def test_regeneration_is_dropped_when_the_engine_mangles_the_text():
    target = _regen_card(1, "見出しはこうニャ！", furigana="old")
    plan = build_plan(
        [target],
        REGEN_CFG,
        scope_note_ids=[1],
        furigana_generator=_generator("全然違うテキスト"),
    )
    assert not any(w.op == OP_REGENERATE_FURIGANA for w in plan.writes)
    assert any("furigana regeneration skipped" in warning for warning in plan.warnings)


def test_regeneration_is_dropped_when_the_engine_raises():
    def boom(_sentence):
        raise RuntimeError("mecab is not running")

    target = _regen_card(1, "見出しはこうニャ！", furigana="old")
    plan = build_plan([target], REGEN_CFG, scope_note_ids=[1], furigana_generator=boom)
    assert not any(w.op == OP_REGENERATE_FURIGANA for w in plan.writes)
    assert any("reading engine raised" in warning for warning in plan.warnings)


# --- empty-definition cleanup (QUALITY Q-D12, owner ask 2026-11-16) ----------

JUNK_SHELL = '<div style="text-align: left;" class="yomitan-glossary"><ol></ol></div>'


def test_an_empty_definition_shell_is_cleared():
    f = dict(CHILD.fields)
    f["Definition"] = JUNK_SHELL
    f["Sentence"] = "先生は今 診察中ですので"
    c = rec(CHILD.note_id, f, tags=("yomitan",))
    plan = build_plan([c], CFG, scope_note_ids=[CHILD.note_id])
    clears = [w for w in plan.writes if w.op == OP_STRIP_EMPTY_GLOSSARY]
    assert len(clears) == 1
    write = clears[0]
    assert write.field == "Definition"
    assert write.old_value == JUNK_SHELL
    assert write.new_value == ""
    assert write.default_checked is True
    assert write.badges == ("cleared-empty-glossary",)


def test_a_real_definition_is_never_cleared():
    f = dict(CHILD.fields)
    f["Definition"] = '<div class="yomitan-glossary"><ol><li>しんさつ</li></ol></div>'
    f["Sentence"] = "先生は今 診察中ですので"
    c = rec(CHILD.note_id, f, tags=("yomitan",))
    plan = build_plan([c], CFG, scope_note_ids=[CHILD.note_id])
    assert not [w for w in plan.writes if w.op == OP_STRIP_EMPTY_GLOSSARY]


def test_both_definition_fields_are_cleaned_when_both_are_shells():
    f = dict(CHILD.fields)
    f["Definition"] = JUNK_SHELL
    f["Extended definition"] = '<div class="yomitan-glossary"><ol></ol></div>'
    f["Sentence"] = "先生は今 診察中ですので"
    c = rec(CHILD.note_id, f, tags=("yomitan",))
    plan = build_plan([c], CFG, scope_note_ids=[CHILD.note_id])
    fields = sorted(w.field for w in plan.writes if w.op == OP_STRIP_EMPTY_GLOSSARY)
    assert fields == ["Definition", "Extended definition"]


# --- dimension picker: scene propagation off (BULK_FIX.md B7) -----------------


def test_the_scene_dimension_off_leaves_scene_fills_out_of_the_plan():
    # The picker can turn propagation off without unlocking anything else:
    # no scene-origin row is planned, so no fill can slip through selection.
    cfg = {**CFG, "batch_scene_propagation": False}
    plan = build_plan([PARENT, CHILD], cfg, scope_note_ids=[CHILD_ID])
    assert not any(w.op == OP_FILL for w in plan.writes)
    assert not any(w.op in (OP_EXPAND_SENTENCE, OP_REPLACE_SOURCE) for w in plan.writes)
    # The lossless core still works (bold repair is not a dimension).
    assert any(w.op == OP_BOLD_CLOZE_WORD for w in plan.writes) or not plan.writes


# --- Expression spelling repair (bulk-fix dimension 4, Q-D12) -----------------

# The real ひと握り card (note 1736973220751): the mining kept the subtitle's
# surface form while the note's own furigana records the dictionary form the
# Yomitan lookup resolved to. Before T15 the planner emitted nothing for it
# ("already complete") — the observation that made the gap visible.
HITONIGIRI = rec(
    1736973220751,
    {
        **BASE,
        "Expression": "ひと握り",
        "reading": "ひとにぎり",
        "furigana": "一握[ひとにぎ]り",
        "Sentence": "選別者の中でも&nbsp;ほんの<b>ひと握り</b>の<br>常識を超えた怪物たち",
        "Sentence (furigana)": "選別[せんべつ]者[しゃ]の 中[なか]でもほんのひと 握[にぎ]りの",
        "Sentence Audio": "[sound:Judas_Kami_no_Tou_-_S0_828541_4f19jx02.mp3]",
        "Word Audio": "[sound:yomitan_audio.mp3]",
        "Picture": '<img src="Judas_Kami_no_Tou_-_S0_828640_CMfYsMCA.webp">',
        "Source": "[Judas] Kami no Tou - S01E02.mkv (13m48s)",
    },
)
EXPR_REPAIR_CFG = {**CFG, "batch_repair_expression": True}


def expression_rows(plan):
    return [w for w in plan.writes if w.field == "Expression"]


def test_expression_repair_rewrites_the_surface_form_to_the_furigana_base():
    plan = build_plan([HITONIGIRI], EXPR_REPAIR_CFG, scope_note_ids=[HITONIGIRI.note_id])
    rows = expression_rows(plan)
    assert len(rows) == 1
    write = rows[0]
    assert write.op == OP_REPAIR_EXPRESSION
    assert write.old_value == "ひと握り"
    assert write.new_value == "一握り"
    assert write.default_checked
    assert "expression-repaired-from-furigana" in write.badges


def test_expression_repair_can_be_switched_off():
    # The escape hatch: `batch_repair_expression: false` removes the tier
    # without reporting an anomaly — the card simply stays untouched.
    cfg = {**CFG, "batch_repair_expression": False}
    plan = build_plan([HITONIGIRI], cfg, scope_note_ids=[HITONIGIRI.note_id])
    assert expression_rows(plan) == []
    # Not reported as a new anomaly either — the card simply stays untouched.
    assert plan.reasons.get(HITONIGIRI.note_id) == "no-parent-that-fills"


def test_expression_repair_is_inert_when_the_furigana_matches_the_expression():
    # A correctly mined card: furigana `ひと握[にぎ]り` describes ひと握り.
    target = rec(
        2,
        {
            **BASE,
            "Expression": "ひと握り",
            "reading": "ひとにぎり",
            "furigana": "ひと握[にぎ]り",
            "Sentence": "ほんの<b>ひと握り</b>の怪物たち",
        },
    )
    plan = build_plan([target], EXPR_REPAIR_CFG, scope_note_ids=[2])
    assert expression_rows(plan) == []
    assert plan.warnings == []


def test_expression_repair_is_silent_without_a_furigana_field():
    # No oracle on the note → nothing to derive; kana-only expressions
    # without furigana stay future work (the offline dictionary seam).
    target = rec(
        3,
        {**BASE, "Expression": "いきなり", "reading": "いきなり", "furigana": ""},
    )
    plan = build_plan([target], EXPR_REPAIR_CFG, scope_note_ids=[3])
    assert expression_rows(plan) == []
    assert plan.warnings == []


def test_expression_repair_reports_a_furigana_that_reads_differently():
    # The furigana describes another word than the reading field claims:
    # a mis-mine signal, reported — never rewritten. The card is fully
    # enriched, so the expression reason is the plan's only reason (the
    # scene dimension stays quiet); on a scene-gapped card the same miss
    # surfaces as a run warning instead.
    target = rec(
        4,
        {
            **BASE,
            "Expression": "ひと握り",
            "reading": "にぎる",
            "furigana": "一握[ひとにぎ]り",
            "Sentence": "ほんの<b>ひと握り</b>の怪物たち",
            "Sentence (furigana)": "ほんのひと 握[にぎ]りの怪物たち",
            "Sentence Audio": "[sound:a.mp3]",
            "Picture": '<img src="p.webp">',
            "Translation": "a handful of monsters",
            "Source": "show (13m48s)",
        },
    )
    plan = build_plan([target], EXPR_REPAIR_CFG, scope_note_ids=[4])
    assert expression_rows(plan) == []
    assert plan.reasons == {4: "expression-repair-reading-mismatch"}
    assert any("expression repair skipped" in warning for warning in plan.warnings)


def test_expression_repair_refuses_a_kanji_less_base():
    # A pure-kana base would be a different word, never a spelling (Q-D12).
    # `ひとに[ぎり]` reads ひとにぎり like the reading field, but its base
    # ひとに carries no kanji to rewrite to.
    target = rec(
        5,
        {
            **BASE,
            "Expression": "ひと握り",
            "reading": "ひとにぎり",
            "furigana": "ひとに[ぎり]",
            "Sentence": "ほんの<b>ひと握り</b>の怪物たち",
            "Sentence (furigana)": "ほんのひと 握[にぎ]りの怪物たち",
            "Sentence Audio": "[sound:a.mp3]",
            "Picture": '<img src="p.webp">',
            "Translation": "a handful of monsters",
            "Source": "show (13m48s)",
        },
    )
    plan = build_plan([target], EXPR_REPAIR_CFG, scope_note_ids=[5])
    assert expression_rows(plan) == []
    assert plan.reasons == {5: "expression-repair-no-kanji-form"}


def test_expression_repair_refuses_a_clause_like_base():
    # The Q-D3 word-like gate applies to the base too. The base is all
    # kanji, so the reading cross-check passes and the gate is what refuses.
    target = rec(
        6,
        {
            **BASE,
            "Expression": "ひと握り",
            "reading": "ひとにぎり",
            "furigana": "漢字能力検定試験実施企画[ひとにぎり]",
            "Sentence": "ほんの<b>ひと握り</b>の怪物たち",
            "Sentence (furigana)": "ほんのひと 握[にぎ]りの怪物たち",
            "Sentence Audio": "[sound:a.mp3]",
            "Picture": '<img src="p.webp">',
            "Translation": "a handful of monsters",
            "Source": "show (13m48s)",
        },
    )
    plan = build_plan([target], EXPR_REPAIR_CFG, scope_note_ids=[6])
    assert expression_rows(plan) == []
    assert plan.reasons == {6: "expression-not-word-like"}


def test_expression_repair_is_deferred_while_word_writes_are_queued():
    # F2 risk 4: a Definition fill is sourced from the old spelling's word
    # group; the rewrite must not land in the same run. The next run, with
    # the Definition filled, picks the rewrite up.
    sibling = rec(
        7,
        {
            **BASE,
            "Expression": "ひと握り",
            "reading": "ひとにぎり",
            "furigana": "一握[ひとにぎ]り",
            "Definition": "one handful",
        },
    )
    target = rec(
        8,
        {
            **BASE,
            "Expression": "ひと握り",
            "reading": "ひとにぎり",
            "furigana": "一握[ひとにぎ]り",
            "Sentence": "ほんの<b>ひと握り</b>の怪物たち",
            "Definition": "",
        },
    )
    plan = build_plan([sibling, target], EXPR_REPAIR_CFG, scope_note_ids=[8])
    assert any(w.field == "Definition" for w in plan.writes)  # the word tier ran
    assert expression_rows(plan) == []


def test_expression_repair_runs_alongside_non_word_writes():
    # Bold markup and scene media do not depend on the word group: the
    # rewrite is not deferred for them.
    target = rec(
        9,
        {
            **HITONIGIRI.fields,
            "Sentence": "ほんのひと握りの怪物たち",  # no bold → bold repair too
        },
    )
    plan = build_plan([target], EXPR_REPAIR_CFG, scope_note_ids=[9])
    assert expression_rows(plan)
    assert any(w.op == OP_BOLD_CLOZE_WORD for w in plan.writes)
