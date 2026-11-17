"""Apply-engine rules: per-note atomicity, idempotence, tags-only-add, undo.

These are the guarantees that make "apply" safe on a real collection, so
they are pinned here with a dict-backed fake collection — no Anki needed.
"""

from __future__ import annotations

import json
import types

from mining_fixer.applier import (
    NoteState,
    build_run_log,
    decide,
    decide_undo,
    latest_run_log_in,
    run_after_editor_saved,
    run_log_records,
)
from mining_fixer.plan import (
    OP_ADD_TAGS,
    OP_BOLD_CLOZE_WORD,
    OP_EXPAND_SENTENCE,
    OP_FILL,
    Plan,
    PlannedWrite,
)

SENTENCE = "Sentence"
BODY = "cloze-body"


def write(note_id, field, op, old, new, checked=True, source=None, badges=()):
    return PlannedWrite(
        note_id=note_id,
        field=field,
        op=op,
        old_value=old,
        new_value=new,
        source_note_id=source,
        default_checked=checked,
        badges=badges,
    )


def plan_of(*writes) -> Plan:
    return Plan(writes=tuple(writes))


def reader(states: dict[int, NoteState]):
    return lambda note_id: states[note_id]


def state(fields, tags=()) -> NoteState:
    return NoteState(fields=dict(fields), tags=frozenset(tags))


def test_fill_is_written_when_the_field_is_still_empty():
    plan = plan_of(write(1, SENTENCE, OP_FILL, "", "full scene line"))
    states = {1: state({SENTENCE: ""})}
    decision = decide(plan, [(1, SENTENCE)], reader(states))
    assert [(w.note_id, w.field, w.new_value) for w in decision.field_writes] == [
        (1, SENTENCE, "full scene line")
    ]
    assert not decision.skipped


def test_one_stale_row_skips_the_whole_note():
    # The sentence changed under the preview, so the tags row — which would
    # still be valid on its own — must not be applied either.
    plan = plan_of(
        write(1, SENTENCE, OP_EXPAND_SENTENCE, "fragment", "full scene", source=9),
        write(1, "tags", OP_ADD_TAGS, "yomitan", "asbplayer yomitan"),
    )
    states = {1: state({SENTENCE: "edited by hand"}, tags={"yomitan"})}
    decision = decide(plan, [(1, SENTENCE), (1, "tags")], reader(states))
    assert decision.field_writes == []
    assert decision.tags_writes == []
    assert [(s.note_id, s.reason) for s in decision.skipped] == [(1, "changed since preview")]
    assert decision.skipped[0].rows == ("Sentence:expand_sentence",)


def test_untouched_notes_are_still_written_when_another_note_is_skipped():
    plan = plan_of(
        write(1, SENTENCE, OP_FILL, "", "stale target"),
        write(2, SENTENCE, OP_FILL, "", "fresh target"),
    )
    states = {1: state({SENTENCE: "already had text"}), 2: state({SENTENCE: ""})}
    decision = decide(plan, [(1, SENTENCE), (2, SENTENCE)], reader(states))
    assert [w.note_id for w in decision.field_writes] == [2]


def test_rerunning_the_same_plan_is_a_noop():
    plan = plan_of(write(1, SENTENCE, OP_FILL, "", "full scene line"))
    states = {1: state({SENTENCE: "full scene line"})}
    decision = decide(plan, [(1, SENTENCE)], reader(states))
    assert decision.row_count() == 0
    assert [(s.note_id, s.reason) for s in decision.skipped] == [(1, "already applied")]


def test_bold_markup_row_quotes_the_previous_value():
    plan = plan_of(
        write(1, SENTENCE, OP_BOLD_CLOZE_WORD, "母は うつ病に。", "母は <b>うつ病</b>に。")
    )
    states = {1: state({SENTENCE: "母は うつ病に。"})}
    decision = decide(plan, [(1, SENTENCE)], reader(states))
    assert decision.field_writes[0].old_value == "母は うつ病に。"
    assert decision.field_writes[0].new_value == "母は <b>うつ病</b>に。"


def test_tags_are_only_ever_added():
    # The card gained a tag since the preview: it must survive.
    plan = plan_of(write(1, "tags", OP_ADD_TAGS, "yomitan", "asbplayer yomitan"))
    states = {1: state({}, tags={"yomitan", "marked-later"})}
    decision = decide(plan, [(1, "tags")], reader(states))
    assert list(decision.tags_writes[0].new_tags) == ["asbplayer", "marked-later", "yomitan"]
    assert list(decision.tags_writes[0].old_tags) == ["marked-later", "yomitan"]


def test_applied_tag_marks_every_note_that_was_written():
    plan = plan_of(write(1, SENTENCE, OP_FILL, "", "text"))
    states = {1: state({SENTENCE: ""})}
    decision = decide(plan, [(1, SENTENCE)], reader(states), applied_tag="auto-filled")
    assert list(decision.tags_writes[0].new_tags) == ["auto-filled"]


def test_applied_tag_is_added_even_when_the_tags_row_is_unchecked():
    plan = plan_of(
        write(1, SENTENCE, OP_FILL, "", "text"),
        write(1, "tags", OP_ADD_TAGS, "yomitan", "asbplayer yomitan"),
    )
    states = {1: state({SENTENCE: ""}, tags={"yomitan"})}
    decision = decide(plan, [(1, SENTENCE)], reader(states), applied_tag="auto-filled")
    assert list(decision.tags_writes[0].new_tags) == ["auto-filled", "yomitan"]


def test_unchecked_rows_write_nothing():
    plan = plan_of(write(1, SENTENCE, OP_FILL, "", "text", checked=False))
    decision = decide(plan, [], reader({1: state({SENTENCE: ""})}))
    assert decision.row_count() == 0
    assert decision.skipped == []


def test_undo_restores_values_and_removes_only_the_tags_it_added():
    plan = plan_of(
        write(1, SENTENCE, OP_FILL, "", "full scene"),
        write(1, BODY, OP_FILL, "", "cloze"),
    )
    before = {1: state({SENTENCE: "", BODY: ""}, tags={"yomitan"})}
    decision = decide(plan, [(1, SENTENCE), (1, BODY)], reader(before), applied_tag="auto-filled")
    assert decision.row_count() == 3  # two fields plus the applied-tag marker

    log = build_run_log(decision, {"deck": "test"})
    after = {
        1: state(
            {SENTENCE: "full scene", BODY: "cloze"},
            tags={"yomitan", "auto-filled"},
        )
    }
    undo = decide_undo(run_log_records(log), reader(after))
    restored = {w.field: w.new_value for w in undo.field_writes}
    assert restored == {SENTENCE: "", BODY: ""}
    assert [w.op for w in undo.field_writes] == ["restore", "restore"]
    assert list(undo.tags_writes[0].new_tags) == ["yomitan"]


def test_undo_leaves_notes_edited_since_the_run_alone():
    plan = plan_of(write(1, SENTENCE, OP_FILL, "", "full scene"))
    decision = decide(plan, [(1, SENTENCE)], reader({1: state({SENTENCE: ""})}))
    log = build_run_log(decision, {})
    after = {1: state({SENTENCE: "the user rewrote this"})}
    undo = decide_undo(run_log_records(log), reader(after))
    assert undo.row_count() == 0
    assert [(s.note_id, s.reason) for s in undo.skipped] == [(1, "changed since the run")]


def test_undo_is_idempotent():
    plan = plan_of(write(1, SENTENCE, OP_FILL, "", "full scene"))
    decision = decide(plan, [(1, SENTENCE)], reader({1: state({SENTENCE: ""})}))
    log = build_run_log(decision, {})
    already_back = {1: state({SENTENCE: ""})}
    undo = decide_undo(run_log_records(log), reader(already_back))
    assert undo.row_count() == 0
    assert undo.skipped == []


def test_run_log_round_trips_through_json():
    import json

    plan = plan_of(write(1, "tags", OP_ADD_TAGS, "yomitan", "asbplayer yomitan"))
    decision = decide(plan, [(1, "tags")], reader({1: state({}, tags={"yomitan"})}))
    log = build_run_log(decision, {"deck": "test", "rows": 1})
    assert json.loads(json.dumps(log)) == log
    records = run_log_records(log)
    assert records[0]["tags_applied"] == ["asbplayer", "yomitan"]
    assert records[0]["tags_prior"] == ["yomitan"]
    assert run_log_records({}) == []


# --- write timing (the host's editor must save before we write) ---------


class _FakeEditor:
    """Stand-in for a Browser editor; records the callback instead of saving."""

    def __init__(self, raise_on_call: bool = False) -> None:
        self.callback = None
        self.calls = 0
        self.raise_on_call = raise_on_call

    def call_after_note_saved(self, callback) -> None:
        self.calls += 1
        if self.raise_on_call:
            raise RuntimeError("editor is gone")
        self.callback = callback


def test_writes_wait_for_the_editor_to_save():
    events: list[str] = []
    editor = _FakeEditor()
    run_after_editor_saved(types.SimpleNamespace(editor=editor), lambda: events.append("write"))
    assert events == []  # nothing is written while a save is still pending
    editor.callback()
    assert events == ["write"]


def test_a_doubled_editor_callback_still_writes_once():
    events: list[str] = []
    editor = _FakeEditor()
    run_after_editor_saved(types.SimpleNamespace(editor=editor), lambda: events.append("write"))
    editor.callback()
    editor.callback()  # some editors invoke their callback more than once
    assert events == ["write"]


def test_writes_run_immediately_without_an_editor():
    events: list[str] = []
    for browser in (
        None,
        types.SimpleNamespace(),
        types.SimpleNamespace(editor=object()),
    ):
        run_after_editor_saved(browser, lambda: events.append("write"))
    assert events == ["write", "write", "write"]


def test_writes_still_run_when_the_editor_flush_raises():
    events: list[str] = []
    editor = _FakeEditor(raise_on_call=True)
    run_after_editor_saved(types.SimpleNamespace(editor=editor), lambda: events.append("write"))
    # The user pressed Apply: a broken editor must not swallow the run.
    assert events == ["write"]


def test_a_lost_editor_callback_cannot_swallow_the_run():
    events: list[str] = []
    scheduled: list = []
    editor = _FakeEditor()
    run_after_editor_saved(
        types.SimpleNamespace(editor=editor),
        lambda: events.append("write"),
        schedule=scheduled.append,
    )
    assert events == []  # still waiting for the editor to save
    scheduled[0]()  # safety net fires: Anki lost the save callback
    assert events == ["write"]
    editor.callback()  # a late save callback must not write a second time
    assert events == ["write"]


# --- undo log lookup (current + pre-rename folders) ---------------------


def test_the_newest_run_log_wins_across_folders(tmp_path):
    legacy = tmp_path / "mining_backfill" / "undo"
    current = tmp_path / "mining_fixer" / "undo"
    legacy.mkdir(parents=True)
    current.mkdir(parents=True)
    (legacy / "run-20261114-222600.json").write_text(json.dumps({"records": []}), encoding="utf-8")
    (current / "run-20261115-090000-000000.json").write_text(
        json.dumps({"records": []}), encoding="utf-8"
    )
    path, log = latest_run_log_in([current, legacy])
    assert path.name == "run-20261115-090000-000000.json"
    assert log == {"records": []}


def test_a_run_logged_before_the_rename_stays_undoable(tmp_path):
    legacy = tmp_path / "mining_backfill" / "undo"
    legacy.mkdir(parents=True)
    (legacy / "run-20261114-222600.json").write_text(json.dumps({"records": []}), encoding="utf-8")
    current = tmp_path / "mining_fixer" / "undo"  # never created
    path, _ = latest_run_log_in([current, legacy])
    assert path.parent == legacy


def test_no_run_log_anywhere_means_no_undo(tmp_path):
    assert latest_run_log_in([tmp_path / "missing", tmp_path / "also-missing"]) is None


def test_an_unreadable_newest_log_means_no_undo(tmp_path):
    folder = tmp_path / "mining_fixer" / "undo"
    folder.mkdir(parents=True)
    (folder / "run-20261115-090000-000000.json").write_text("{broken", encoding="utf-8")
    assert latest_run_log_in([folder]) is None


# --- semantic verification (the author's hand-found defects) -----------------


def _state(note_id, fields, tags=()):
    return NoteState(fields=dict(fields), tags=frozenset(tags))


def test_verification_reports_two_bold_items():
    from mining_fixer.applier import ApplyDecision, FieldWrite, verify_writes

    decision = ApplyDecision(
        field_writes=[FieldWrite(1, "Sentence", "bold_cloze_word", "old", "<b>校</b>と<b>ぜひ</b>")]
    )
    problems = verify_writes(
        decision, lambda nid: _state(nid, {"Sentence": "<b>校</b>と<b>ぜひ</b>"})
    )
    assert any("2 bold items" in problem for problem in problems)


def test_verification_reports_a_ruby_that_does_not_match_its_sentence():
    from mining_fixer.applier import ApplyDecision, FieldWrite, verify_writes

    decision = ApplyDecision(
        field_writes=[FieldWrite(1, "Sentence (furigana)", "fill", "", "この‐たび【 ×此の度】")]
    )
    problems = verify_writes(
        decision,
        lambda nid: _state(
            nid,
            {
                "Sentence": "今回 対象としたい患者は この方。",
                "Sentence (furigana)": "この‐たび【 ×此の度】",
            },
        ),
    )
    assert any("ruby does not match" in problem for problem in problems)


def test_verification_reports_missing_media():
    from mining_fixer.applier import ApplyDecision, FieldWrite, verify_writes

    decision = ApplyDecision(
        field_writes=[FieldWrite(1, "Sentence Audio", "fill", "", "[sound:a.webm]")]
    )
    problems = verify_writes(
        decision,
        lambda nid: _state(nid, {"Sentence Audio": "[sound:a.webm]"}),
        media_exists=lambda name: False,
    )
    assert any("media file(s) missing" in problem for problem in problems)


def test_verification_is_silent_for_a_coherent_card():
    from mining_fixer.applier import ApplyDecision, FieldWrite, verify_writes

    decision = ApplyDecision(
        field_writes=[FieldWrite(1, "Sentence", "bold_cloze_word", "あ校", "あ<b>校</b>")]
    )
    problems = verify_writes(
        decision,
        lambda nid: _state(nid, {"Sentence": "あ<b>校</b>", "Sentence (furigana)": "あ 校[こう]"}),
        media_exists=lambda name: True,
    )
    assert problems == []


def test_merged_run_logs_keep_the_first_prior_and_the_last_applied(tmp_path):
    # One Apply may take several passes (Q-A2). Each pass logs prior -> applied;
    # the merged log must restore the whole Apply: earliest prior, latest
    # applied, union of tags, and only one log file left behind.
    from mining_fixer.applier import merge_run_logs

    def log(name, records):
        path = tmp_path / name
        path.write_text(json.dumps({"kind": "batch", "records": records}), encoding="utf-8")
        return path

    first = log(
        "run-1.json",
        [
            {
                "note_id": 1,
                "fields": [{"field": "Sentence", "prior": "a", "applied": "b"}],
                "tags_applied": ["t"],
                "tags_prior": [],
            }
        ],
    )
    second = log(
        "run-2.json",
        [
            {
                "note_id": 1,
                "fields": [
                    {"field": "Sentence", "prior": "b", "applied": "c"},
                    {"field": "Picture", "prior": "", "applied": "p"},
                ],
                "tags_applied": ["t", "u"],
                "tags_prior": ["t"],
            }
        ],
    )
    merge_run_logs([first, second])
    assert not first.exists()
    merged = json.loads(second.read_text(encoding="utf-8"))
    record = merged["records"][0]
    fields = {change["field"]: change for change in record["fields"]}
    assert fields["Sentence"]["prior"] == "a"  # the earliest old value
    assert fields["Sentence"]["applied"] == "c"  # the last applied value
    assert fields["Picture"]["applied"] == "p"
    assert record["tags_applied"] == ["t", "u"]  # the last pass's tags
    assert record["tags_prior"] == []  # the true "before", from the first pass


def test_merged_multi_pass_log_undoes_the_whole_apply(tmp_path):
    # Undo on the merged log must return every field to its pre-Apply value
    # (not the value after the first pass) and the tags to the pre-Apply set.
    from mining_fixer.applier import decide_undo, merge_run_logs

    def log(name, records):
        path = tmp_path / name
        path.write_text(json.dumps({"records": records}), encoding="utf-8")
        return path

    first = log(
        "run-1.json",
        [
            {
                "note_id": 1,
                "fields": [{"field": "Sentence", "prior": "a", "applied": "b"}],
                "tags_applied": ["t"],
                "tags_prior": [],
            }
        ],
    )
    second = log(
        "run-2.json",
        [
            {
                "note_id": 1,
                "fields": [
                    {"field": "Sentence", "prior": "b", "applied": "c"},
                    {"field": "Picture", "prior": "", "applied": "p"},
                ],
                "tags_applied": ["t", "u"],
                "tags_prior": ["t"],
            }
        ],
    )
    merge_run_logs([first, second])
    merged = json.loads(second.read_text(encoding="utf-8"))
    after_apply = {1: state({"Sentence": "c", "Picture": "p"}, tags=("t", "u"))}
    undo = decide_undo(run_log_records(merged), reader(after_apply))
    restored = {write.field: write.new_value for write in undo.field_writes}
    assert restored == {"Sentence": "a", "Picture": ""}
    assert list(undo.tags_writes[0].new_tags) == []  # back to the pre-Apply tags
