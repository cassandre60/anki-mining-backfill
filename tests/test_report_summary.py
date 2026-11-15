"""The batch preview report must be readable by a human, not a data dump."""

from __future__ import annotations

from test_plan import rec

from mining_fixer.batch import BatchSelection, LeftAlone, default_ops, select
from mining_fixer.plan import (
    OP_ADD_TAGS,
    OP_BOLD_CLOZE_WORD,
    OP_EXPAND_SENTENCE,
    OP_FILL,
    OP_REPAIR_SENTENCE,
    Plan,
    PlannedWrite,
)
from mining_fixer.report import render_batch_summary


def note(note_id, expression="診察", reading="しんさつ"):
    return rec(
        note_id,
        {
            "Expression": expression,
            "reading": reading,
            "Sentence": "fragment",
            "Sentence Audio": "[sound:a.webm]",
            "Picture": "<img>",
            "Source": "Show 1.mp4 (1m00s)",
            "Sentence (furigana)": "ruby",
        },
        tags=(),
    )


def writes(note_id):
    return (
        PlannedWrite(
            note_id=note_id,
            field="Sentence",
            op=OP_EXPAND_SENTENCE,
            old_value="fragment",
            new_value="full scene",
            source_note_id=9,
            default_checked=True,
        ),
        PlannedWrite(
            note_id=note_id,
            field="Picture",
            op=OP_FILL,
            old_value="",
            new_value="<img>",
            source_note_id=9,
            default_checked=True,
        ),
        PlannedWrite(
            note_id=note_id,
            field="tags",
            op=OP_ADD_TAGS,
            old_value="yomitan",
            new_value="asbplayer yomitan",
            default_checked=True,
        ),
    )


def test_the_preview_reads_like_a_sentence_not_a_dump():
    plan = Plan(
        writes=writes(1),
        reasons={2: "nothing-to-fill"},
    )
    records = {1: note(1), 2: note(2, "尾ける", "つける")}
    selection = select(plan, default_ops())
    text = render_batch_summary(plan, records, selection, {"scope": 2})

    assert "# Mining Fixer — preview (nothing was changed)" in text
    assert "will be fixed: 1 note(s)" in text
    assert "unchanged: 1 note(s)" in text
    # Human labels, not field names or op ids.
    assert "full scene sentence" in text
    assert "picture" in text
    assert "expand_sentence" not in text
    assert "OP_FILL" not in text


def test_left_alone_is_listed_with_its_reason_and_no_question():
    selection = BatchSelection(
        rows=(),
        left_alone=(LeftAlone(5, "sentence left alone — fragment not recoverable"),),
        untouched=1,
    )
    text = render_batch_summary(
        Plan(writes=()), {5: note(5, "尾ける", "つける")}, selection, {"scope": 2}
    )
    assert "| 尾ける | 5 | sentence left alone — fragment not recoverable |" in text
    assert "Nothing here needs a decision" in text


def test_bold_repairs_are_labelled_for_a_human():
    plan = Plan(
        writes=(
            PlannedWrite(
                note_id=7,
                field="Sentence",
                op=OP_BOLD_CLOZE_WORD,
                old_value="母は うつ病に。",
                new_value="母は <b>うつ病</b>に。",
                default_checked=True,
            ),
        )
    )
    text = render_batch_summary(
        plan, {7: note(7, "鬱病", "うつびょう")}, select(plan, default_ops()), {"scope": 1}
    )
    assert "bold on the tested word" in text
    assert "bold_cloze_word" not in text


def test_repair_rows_are_labelled_for_a_human():
    plan = Plan(
        writes=(
            PlannedWrite(
                note_id=7,
                field="Sentence",
                op=OP_REPAIR_SENTENCE,
                old_value="あしたの朝刊の見出しは<br>こうニャ！➡",
                new_value="あしたの朝刊の見出しはこうニャ！",
                default_checked=True,
                badges=("strip-arrows", "collapse-br"),
            ),
        )
    )
    text = render_batch_summary(
        plan,
        {7: note(7, "見出し", "みだし")},
        select(plan, default_ops({"batch_repair_sentence": True})),
        {"scope": 1},
    )
    assert "sentence noise repair" in text
    assert "repair_sentence" not in text
