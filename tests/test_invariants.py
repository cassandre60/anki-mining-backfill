"""Property-based invariants for the apply/undo engine.

Hypothesis generates plans and live states; the engine must never write a
field whose precondition does not hold, re-running must be a no-op, and undo
must restore exactly what was changed.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from mining_fixer.applier import (
    NoteState,
    build_run_log,
    decide,
    decide_undo,
    run_log_records,
)
from mining_fixer.plan import (
    OP_ADD_TAGS,
    OP_BOLD_CLOZE_WORD,
    OP_EXPAND_SENTENCE,
    OP_FILL,
    OP_REPLACE_SOURCE,
    Plan,
    PlannedWrite,
)

FIELDS = ["Sentence", "Source", "Definition"]
VALUE_OPS = [OP_REPLACE_SOURCE, OP_EXPAND_SENTENCE, OP_BOLD_CLOZE_WORD]


@st.composite
def plans(draw):
    """A plan whose rows are self-consistent (fill ⇒ empty old, etc.)."""
    notes = draw(st.lists(st.integers(1, 4), min_size=1, max_size=4, unique=True))
    writes = []
    for note_id in notes:
        for field in draw(st.lists(st.sampled_from(FIELDS), unique=True, max_size=3)):
            if draw(st.booleans()):
                old = ""
                op = OP_FILL
            else:
                old = draw(st.text(min_size=1, max_size=16))
                op = draw(st.sampled_from(VALUE_OPS))
            new = draw(st.text(min_size=1, max_size=16))
            if new == old:
                new = new + "!"
            writes.append(
                PlannedWrite(
                    note_id=note_id,
                    field=field,
                    op=op,
                    old_value=old,
                    new_value=new,
                    default_checked=True,
                )
            )
        if draw(st.booleans()):
            old_tags = draw(st.lists(st.sampled_from(["a", "b", "c"]), unique=True))
            new_tags = sorted(set(old_tags) | set(draw(st.lists(st.sampled_from(["d", "e"])))))
            writes.append(
                PlannedWrite(
                    note_id=note_id,
                    field="tags",
                    op=OP_ADD_TAGS,
                    old_value=" ".join(old_tags),
                    new_value=" ".join(new_tags),
                    default_checked=True,
                )
            )
    return Plan(writes=tuple(writes))


def states_for(plan: Plan) -> dict[int, NoteState]:
    """The collection as the preview saw it: every old value is current."""
    states: dict[int, NoteState] = {}
    for note_id in {w.note_id for w in plan.writes}:
        fields: dict[str, str] = {}
        tags: set[str] = set()
        for write in plan.writes:
            if write.note_id != note_id:
                continue
            if write.op == OP_ADD_TAGS:
                tags = set(write.old_value.split())
            else:
                fields[write.field] = write.old_value
        states[note_id] = NoteState(fields=fields, tags=frozenset(tags))
    return states


def apply(decision, states: dict[int, NoteState]) -> None:
    """Mirror of collection_io.apply_decision, over the fake states."""
    for write in decision.field_writes:
        state = states[write.note_id]
        fields = dict(state.fields)
        fields[write.field] = write.new_value
        states[write.note_id] = NoteState(fields=fields, tags=state.tags)
    for write in decision.tags_writes:
        state = states[write.note_id]
        states[write.note_id] = NoteState(fields=state.fields, tags=frozenset(write.new_tags))


@settings(max_examples=60, deadline=None)
@given(plan=plans())
def test_every_write_has_its_precondition(plan):
    states = states_for(plan)
    checked = [(w.note_id, w.field) for w in plan.writes]
    decision = decide(plan, checked, states.__getitem__, applied_tag="auto-filled")
    for write in decision.field_writes:
        current = states[write.note_id].fields.get(write.field, "")
        assert current == write.old_value, (write, current)
        assert write.new_value != current


@settings(max_examples=60, deadline=None)
@given(plan=plans())
def test_applying_then_undoing_restores_the_exact_state(plan):
    states = states_for(plan)
    before = {nid: (dict(s.fields), set(s.tags)) for nid, s in states.items()}
    checked = [(w.note_id, w.field) for w in plan.writes]
    decision = decide(plan, checked, states.__getitem__, applied_tag="auto-filled")
    apply(decision, states)

    log = build_run_log(decision, {"test": True})
    undo = decide_undo(run_log_records(log), states.__getitem__)
    apply(undo, states)

    for note_id, (fields, tags) in before.items():
        assert states[note_id].fields == fields, note_id
        assert set(states[note_id].tags) == tags, note_id


@settings(max_examples=60, deadline=None)
@given(plan=plans())
def test_re_running_after_apply_writes_nothing(plan):
    states = states_for(plan)
    checked = [(w.note_id, w.field) for w in plan.writes]
    decision = decide(plan, checked, states.__getitem__, applied_tag="auto-filled")
    apply(decision, states)

    again = decide(plan, checked, states.__getitem__, applied_tag="auto-filled")
    assert again.row_count() == 0
    assert {s.reason for s in again.skipped} <= {"already applied"}


@settings(max_examples=60, deadline=None)
@given(plan=plans(), extra=st.text(min_size=1, max_size=8))
def test_an_edited_field_aborts_its_whole_note(plan, extra):
    states = states_for(plan)
    if not plan.writes:
        return
    target = plan.writes[0]
    if target.op == OP_ADD_TAGS:
        return  # tags rows are tested through their own superset rule
    state = states[target.note_id]
    fields = dict(state.fields)
    edited = state.fields.get(target.field, "") + extra
    while edited in (target.old_value, target.new_value):
        edited += "·"  # never accidentally match the applied target value
    fields[target.field] = edited
    states[target.note_id] = NoteState(fields=fields, tags=state.tags)

    checked = [(w.note_id, w.field) for w in plan.writes if w.note_id == target.note_id]
    decision = decide(plan, checked, states.__getitem__)
    assert decision.field_writes == []
    assert decision.tags_writes == []
    assert decision.skipped[0].reason == "changed since preview"
