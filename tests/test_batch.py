"""Batch policy: tiers, group atomicity, and what the user is shown."""

from __future__ import annotations

from mining_fixer.batch import allowed_ops, default_ops, select
from mining_fixer.plan import (
    OP_ADD_TAGS,
    OP_BOLD_CLOZE_WORD,
    OP_EXPAND_SENTENCE,
    OP_FILL,
    OP_REGENERATE_FURIGANA,
    OP_REPAIR_SENTENCE,
    OP_REPLACE_SOURCE,
    Plan,
    PlannedWrite,
)


def w(note_id, field, op, old="", new="value", checked=True, group=None, badges=()):
    return PlannedWrite(
        note_id=note_id,
        field=field,
        op=op,
        old_value=old,
        new_value=new,
        default_checked=checked,
        badges=badges,
        group_id=group,
    )


def test_the_default_policy_is_lossless():
    # Fills, bold markup and tag additions only — never a replace.
    assert allowed_ops() == {
        OP_FILL,
        OP_BOLD_CLOZE_WORD,
        OP_ADD_TAGS,
    }
    assert OP_EXPAND_SENTENCE not in allowed_ops()
    assert OP_EXPAND_SENTENCE in allowed_ops(expand_sentence=True)
    assert OP_REPLACE_SOURCE in allowed_ops(replace_source=True)


def test_the_text_unit_is_atomic_but_scene_media_is_independent():
    # A sentence and its ruby go together; the scene's audio/picture do not
    # depend on the text, so the lossless tier still fills them.
    plan = Plan(
        writes=(
            w(1, "Sentence", OP_EXPAND_SENTENCE, "fragment", "full scene", group="scene-1-9"),
            w(1, "Sentence (furigana)", OP_FILL, "", "ruby", group="scene-1-9"),
            w(1, "Picture", OP_FILL, "", "<img>", group="scene-1-9"),
            w(1, "Sentence Audio", OP_FILL, "", "[sound:a.webm]", group="scene-1-9"),
            w(2, "Sentence", OP_FILL, "", "plain fill"),
        )
    )
    lossless = select(plan, allowed_ops())
    assert [row.field for row in lossless.rows] == ["Picture", "Sentence Audio", "Sentence"]
    assert lossless.field_notes == 2
    assert lossless.excluded_notes == 1  # the text unit of note 1

    expanded = select(plan, allowed_ops(expand_sentence=True))
    assert expanded.notes == 2
    assert expanded.excluded_notes == 0
    assert {row.field for row in expanded.rows if row.note_id == 1} == {
        "Sentence",
        "Sentence (furigana)",
        "Picture",
        "Sentence Audio",
    }


def test_a_note_whose_only_rows_are_guarded_is_left_alone():
    plan = Plan(
        writes=(
            w(
                1,
                "Sentence",
                OP_EXPAND_SENTENCE,
                "fragment",
                "scene",
                checked=False,
                badges=("expansion-guard", "fragment-not-recoverable"),
            ),
            w(
                1,
                "Sentence (furigana)",
                OP_FILL,
                "",
                "ruby",
                checked=False,
                badges=("paired-with-expansion",),
            ),
        )
    )
    selection = select(plan, allowed_ops(expand_sentence=True))
    assert selection.rows == ()
    assert [(item.note_id, item.reason) for item in selection.left_alone] == [
        (1, "sentence left alone — fragment not recoverable")
    ]
    assert selection.left_alone[0].rows == (
        "Sentence:expand_sentence",
        "Sentence (furigana):fill",
    )


def test_a_text_guard_drops_only_the_sentence_and_still_fills_media():
    # The exact case that made the window useless: the sentence cannot be
    # rewritten, but its scene's audio and picture are independent and safe.
    plan = Plan(
        writes=(
            w(
                1,
                "Sentence",
                OP_EXPAND_SENTENCE,
                "fragment",
                "scene",
                checked=False,
                badges=("expansion-guard", "fragment-not-recoverable"),
            ),
            w(1, "Picture", OP_FILL, "", "<img>"),
            w(1, "Sentence Audio", OP_FILL, "", "[sound:a.webm]"),
        )
    )
    selection = select(plan, allowed_ops(expand_sentence=True))
    assert sorted(row.field for row in selection.rows) == ["Picture", "Sentence Audio"]
    assert selection.field_notes == 1
    assert selection.left_alone == ()
    assert selection.sentences_left_alone == 1


def test_idempotent_and_optional_replaces_are_counted_separately():
    plan = Plan(
        writes=(
            w(1, "Sentence", OP_FILL, "", "text"),
            w(2, "Sentence", OP_EXPAND_SENTENCE, "fragment", "scene"),
            w(3, "Source", OP_REPLACE_SOURCE, "blob:https://x", "Episode 1.mp4"),
        )
    )
    lossless = select(plan, allowed_ops())
    assert lossless.notes == 1
    assert lossless.excluded_notes == 2
    assert lossless.untouched == 0

    everything = select(plan, allowed_ops(expand_sentence=True, replace_source=True))
    assert everything.notes == 3


def test_complete_notes_count_as_untouched_and_ambiguous_bold_is_left_alone():
    plan = Plan(
        writes=(w(1, "Sentence", OP_FILL, "", "text"),),
        reasons={
            2: "nothing-to-fill",
            3: "cloze-word-ambiguous",
            4: "opted-out",
            5: "no-parent-that-fills",
        },
    )
    selection = select(plan, allowed_ops())
    assert selection.notes == 1
    assert selection.untouched == 3  # complete, opted out, nothing found
    assert [(item.note_id, item.reason) for item in selection.left_alone] == [
        (3, "bold ambiguous — left alone")
    ]


def test_default_batch_writes_the_information_preserving_replaces():
    # The bulk fixer completes cards out of the box: the fragment stays in
    # cloze-*, the blob URL stays in the run log, so both replaces are safe.
    assert default_ops() == {
        OP_FILL,
        OP_BOLD_CLOZE_WORD,
        OP_ADD_TAGS,
        OP_EXPAND_SENTENCE,
        OP_REPLACE_SOURCE,
    }
    assert OP_EXPAND_SENTENCE not in default_ops({"batch_expand_sentence": False})
    assert OP_REPLACE_SOURCE not in default_ops({"batch_replace_source": False})


def test_the_repair_tier_is_off_by_default_and_opt_in():
    assert OP_REPAIR_SENTENCE not in allowed_ops()
    assert OP_REPAIR_SENTENCE in allowed_ops(repair_sentence=True)
    assert OP_REPAIR_SENTENCE not in default_ops()
    assert OP_REPAIR_SENTENCE in default_ops({"batch_repair_sentence": True})


def test_the_furigana_tier_is_off_by_default_and_opt_in():
    assert OP_REGENERATE_FURIGANA not in allowed_ops()
    assert OP_REGENERATE_FURIGANA in allowed_ops(regenerate_furigana=True)
    assert OP_REGENERATE_FURIGANA not in default_ops()
    assert OP_REGENERATE_FURIGANA in default_ops({"batch_regenerate_furigana": True})


def test_furigana_rows_are_selected_only_when_the_tier_is_on():
    plan = Plan(
        writes=(
            w(1, "Sentence (furigana)", OP_REGENERATE_FURIGANA, "old", "見出[みだ]し"),
            w(1, "Sentence Audio", OP_FILL, "", "[sound:a.webm]"),
        )
    )
    off = select(plan, allowed_ops())
    assert [row.field for row in off.rows] == ["Sentence Audio"]
    assert off.excluded_notes == 1

    on = select(plan, allowed_ops(regenerate_furigana=True))
    assert sorted(row.field for row in on.rows) == ["Sentence (furigana)", "Sentence Audio"]
    assert on.excluded_notes == 0


def test_repair_rows_are_selected_only_when_the_tier_is_on():
    plan = Plan(
        writes=(
            w(1, "Sentence", OP_REPAIR_SENTENCE, "前<br>後", "前後"),
            w(1, "Sentence Audio", OP_FILL, "", "[sound:a.webm]"),
        )
    )
    off = select(plan, allowed_ops())
    assert [row.field for row in off.rows] == ["Sentence Audio"]
    assert off.excluded_notes == 1

    on = select(plan, allowed_ops(repair_sentence=True))
    assert sorted(row.field for row in on.rows) == ["Sentence", "Sentence Audio"]
    assert on.excluded_notes == 0


def test_left_alone_names_the_divergence_so_the_user_knows_why():
    plan = Plan(
        writes=(
            w(
                1,
                "Picture",
                OP_FILL,
                checked=False,
                group="scene-1-9",
                badges=("divergent-parents",),
            ),
        )
    )
    selection = select(plan, allowed_ops())
    assert selection.rows == ()
    assert [(item.note_id, item.reason) for item in selection.left_alone] == [
        (1, "scene sources disagree — left alone")
    ]


def test_tag_only_notes_are_reported_separately():
    # A note whose only eligible row is a tag update is not "fixed": the
    # dialog must not count it among the filled notes.
    plan = Plan(
        writes=(
            w(1, "Sentence", OP_EXPAND_SENTENCE, "fragment", "scene", group="scene-1-9"),
            w(1, "tags", OP_ADD_TAGS, "yomitan", "asbplayer yomitan"),
            w(2, "Sentence", OP_FILL, "", "text"),
        )
    )
    selection = select(plan, allowed_ops())
    assert selection.field_notes == 1
    assert selection.tag_only_notes == 1
    assert selection.notes == 2
    assert {row.field for row in selection.rows if row.note_id == 1} == {"tags"}
    plan = Plan(
        writes=(
            w(1, "Sentence", OP_FILL, "", "a"),
            w(1, "Picture", OP_FILL, "", "b"),
            w(2, "tags", OP_ADD_TAGS, "yomitan", "asbplayer yomitan"),
        )
    )
    selection = select(plan, allowed_ops())
    assert selection.count_by_op() == {OP_FILL: 2, OP_ADD_TAGS: 1}
    assert selection.notes == 2
