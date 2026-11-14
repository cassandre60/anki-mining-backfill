"""Batch policy: tiers, group atomicity, and what the user is shown."""

from __future__ import annotations

from mining_backfill.batch import allowed_ops, select
from mining_backfill.plan import (
    OP_ADD_TAGS,
    OP_BOLD_CLOZE_WORD,
    OP_EXPAND_SENTENCE,
    OP_FILL,
    OP_REPLACE_SOURCE,
    Plan,
    PlannedWrite,
)


def w(note_id, field, op, old="", new="value", checked=True, group=None):
    return PlannedWrite(
        note_id=note_id,
        field=field,
        op=op,
        old_value=old,
        new_value=new,
        default_checked=checked,
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


def test_a_scene_group_is_written_all_or_nothing():
    # An expansion plus its furigana fill share a group: under the lossless
    # policy the whole group is excluded, so the fragment never gets
    # full-scene furigana.
    plan = Plan(
        writes=(
            w(1, "Sentence", OP_EXPAND_SENTENCE, "fragment", "full scene", group="scene-1-9"),
            w(1, "Sentence (furigana)", OP_FILL, "", "ruby", group="scene-1-9"),
            w(2, "Sentence", OP_FILL, "", "plain fill"),
        )
    )
    lossless = select(plan, allowed_ops())
    assert [row.note_id for row in lossless.rows] == [2]
    assert lossless.excluded_notes == 1

    expanded = select(plan, allowed_ops(expand_sentence=True))
    assert [row.field for row in expanded.rows] == [
        "Sentence",
        "Sentence (furigana)",
        "Sentence",
    ]
    assert expanded.notes == 2
    assert expanded.excluded_notes == 0


def test_one_guarded_row_sends_the_note_to_review_not_to_the_writer():
    plan = Plan(
        writes=(
            w(1, "Sentence", OP_EXPAND_SENTENCE, "fragment", "scene", checked=False),
            w(1, "Sentence (furigana)", OP_FILL, "", "ruby", checked=False),
        )
    )
    selection = select(plan, allowed_ops(expand_sentence=True))
    assert selection.rows == ()
    assert [(item.note_id, item.reason) for item in selection.review] == [
        (1, "guarded row needs a human")
    ]
    assert selection.review[0].rows == (
        "Sentence:expand_sentence",
        "Sentence (furigana):fill",
    )


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


def test_complete_notes_count_as_untouched_and_ambiguous_bold_as_review():
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
    assert [(item.note_id, item.reason) for item in selection.review] == [
        (3, "bold ambiguous — left alone")
    ]


def test_counts_are_per_op_for_the_summary():
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
