"""Plan construction: the single source of truth for preview and apply.

Pure module: no anki/aqt imports.

A :class:`Plan` is a deterministic, versioned list of :class:`PlannedWrite`
plus per-candidate reasons for every note the add-on could not help. The
preview dialog and the applier consume the same plan, so what is shown is
exactly what is written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from fieldconfig import (
    FIELD_NEVER_COPY,
    image_files,
    is_blob_source,
    is_empty,
    sound_files,
)
from matching import (
    DAY_MS,
    MAX_WINDOW_MS,
    NoteRecord,
    SceneMatch,
    agreement_groups,
    best_word_source,
    find_scene_parents,
    rank_scene_parents,
    singleton_kanji_guard,
    word_groups,
)
from normalize import norm_sentence_match, strip_renderable, word_key

__all__ = ["PlannedWrite", "Plan", "build_plan", "PLAN_VERSION"]

PLAN_VERSION = 1

OP_FILL = "fill"
OP_REPLACE_SOURCE = "replace_source"
OP_EXPAND_SENTENCE = "expand_sentence"
OPS_TOUCHING_NONEMPTY = frozenset({OP_REPLACE_SOURCE, OP_EXPAND_SENTENCE})


@dataclass(frozen=True)
class PlannedWrite:
    """One field change. ``old_value`` empty <=> OP_FILL in almost all cases.

    The two approved replaces (blob Source, fragment Sentence) are the only
    ops that may write a non-empty field; both carry explicit badges and
    both preserve their information (the blob URL is recorded in the audit
    log; the fragment survives in cloze-*).
    """

    note_id: int
    field: str
    op: str
    old_value: str
    new_value: str
    source_note_id: int | None = None
    default_checked: bool = False
    badges: tuple[str, ...] = ()
    window_ms: int | None = None
    group_id: str | None = None  # rows sharing a group are applied together


@dataclass
class Plan:
    version: int = PLAN_VERSION
    writes: tuple[PlannedWrite, ...] = ()
    reasons: dict[int, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def checked(self) -> tuple[PlannedWrite, ...]:
        return tuple(w for w in self.writes if w.default_checked)


def _fragment_recoverable(candidate: NoteRecord, cand_norm: str) -> bool:
    """The mined fragment must survive in cloze-* before Sentence is replaced."""
    parts = [
        strip_renderable(candidate.get("cloze-prefix")),
        strip_renderable(candidate.get("cloze-body")),
        strip_renderable(candidate.get("cloze-suffix")),
    ]
    if not any(parts):
        return False
    joined = norm_sentence_match("".join(parts))
    return bool(joined) and joined == cand_norm


def _unique_anchor(parent_value: str, cloze_body: str) -> bool:
    """The cloze body (the tested word) must occur exactly once in the new
    Sentence; otherwise the template's highlight would be ambiguous or lost."""
    if not cloze_body.strip():
        return False
    body = strip_renderable(cloze_body).strip()
    if not body:
        return False
    parent_plain = strip_renderable(parent_value)
    return parent_plain.count(body) == 1


_BOLD_RE = re.compile(r"<b>([^<]{1,80})</b>")


def _retarget_bold(parent_value: str, parent_body: str, child_body: str) -> tuple[str, str | None]:
    """Move the scene's bold markup from the parent's word to the child's.

    The deck convention bolds the mined word inside ``Sentence`` (e.g.
    ``先生は今 <b>診察</b>中ですので➡``). Copying a parent scene verbatim
    would leave the PARENT's word bolded on the child's card; the user's
    manual fix un-bolds the parent's word and bolds the child's cloze word
    instead. Both tags are formatting: no text is added or removed, and
    every change is logged with the old value.

    Returns ``(new_value, badge)``; badge is ``None`` when nothing changed,
    ``"stale-parent-bold"`` when the copy would keep the parent's word
    bolded, and the precise retarget badge otherwise.
    """
    parent_bold = _BOLD_RE.search(parent_value)
    value = parent_value
    unwrapped = False
    if parent_bold:
        pbody = parent_body.strip()
        if pbody and strip_renderable(parent_bold.group(1)) == strip_renderable(pbody).strip():
            value = parent_value.replace(parent_bold.group(0), parent_bold.group(1), 1)
            unwrapped = True
        elif (
            child_body.strip()
            and strip_renderable(parent_bold.group(1)) == strip_renderable(child_body).strip()
        ):
            # Bold already marks the child's word: keep the value as is.
            value = parent_value
        else:
            # Bold marks a different word: leave the parent value untouched
            # rather than guess which markup the card should carry.
            return parent_value, "stale-parent-bold"
    wrapped = False
    cbody = child_body.strip()
    if cbody and f"<b>{cbody}</b>" not in value and value.count(cbody) == 1:
        value = value.replace(cbody, f"<b>{cbody}</b>", 1)
        wrapped = True
    if value == parent_value:
        return parent_value, None
    if unwrapped and wrapped:
        return value, "bold-retargeted-to-cloze-word"
    return value, "parent-bold-removed" if unwrapped else "bold-added-to-cloze-word"


def _scene_writes_for(
    candidate: NoteRecord,
    matches: list[SceneMatch],
    cfg: dict,
) -> tuple[list[PlannedWrite], str | None]:
    """Emit scene-op writes for one candidate, or a reason string."""
    ranked = rank_scene_parents(
        matches,
        candidate,
        optin_fields=tuple(cfg.get("scene_optin_fields", ())),
    )
    if not ranked:
        return [], "no-parent-that-fills"
    groups = agreement_groups(ranked)
    # Largest agreement group wins; ties break on the first-ranked member.
    best_payload, best_members = max(
        groups.items(), key=lambda kv: (len(kv[1]), -ranked.index(kv[1][0]))
    )
    parent = best_members[0].parent
    agree = len(best_members)
    gap_ms = best_members[0].tier_gap_ms
    writes: list[PlannedWrite] = []
    group_id = f"scene-{candidate.note_id}-{parent.note_id}"
    gap_hours = gap_ms / 3_600_000
    context_badges = [f"source-note:{parent.note_id}", f"added-gap:{gap_hours:.1f}h"]
    if agree > 1:
        context_badges.append(f"{agree}-siblings-agree")
    if not best_members[0].boundary_ok:
        context_badges.append("interior-span")
    parent_len = len(norm_sentence_match(parent.get("Sentence")))
    cand_len = len(norm_sentence_match(candidate.get("Sentence")))
    if parent_len > 2 * cand_len:
        context_badges.append("scene-block-parent")

    # Fill ops: only truly empty fields, only values the parent actually has.
    for fname, value in best_payload:
        if fname == "Source":
            writes.append(
                PlannedWrite(
                    note_id=candidate.note_id,
                    field="Source",
                    op=OP_REPLACE_SOURCE,
                    old_value=candidate.get("Source"),
                    new_value=value,
                    source_note_id=parent.note_id,
                    default_checked=bool(cfg.get("replaces_autocheck", True)),
                    badges=tuple(["replaces-blob-url", *context_badges]),
                    window_ms=gap_ms,
                    group_id=group_id,
                )
            )
            continue
        default_checked = True
        if fname in ("Notes", "context", "Kanji Notes"):
            default_checked = False
        writes.append(
            PlannedWrite(
                note_id=candidate.note_id,
                field=fname,
                op=OP_FILL,
                old_value="",
                new_value=value,
                source_note_id=parent.note_id,
                default_checked=default_checked,
                badges=tuple(context_badges),
                window_ms=gap_ms,
                group_id=group_id,
            )
        )

    # Sentence expansion: the user's own transformation. Guarded:
    #  - fragment must be recoverable from cloze-* (never lose the only copy)
    #  - the cloze anchor must occur exactly once in the new Sentence
    #  - stale fragment furigana must not be left behind (atomic replacement)
    cand_norm = norm_sentence_match(candidate.get("Sentence"))
    parent_sentence = parent.get("Sentence")
    parent_furigana = parent.get("Sentence (furigana)")
    if cand_norm and cand_norm != norm_sentence_match(parent_sentence):
        if _fragment_recoverable(candidate, cand_norm) and _unique_anchor(
            parent_sentence, candidate.get("cloze-body")
        ):
            checked = bool(cfg.get("replaces_autocheck", True))
            badges = ["expands-sentence", "fragment-kept-in-cloze", *context_badges]
            new_sentence, bold_badge = _retarget_bold(
                parent_sentence, parent.get("cloze-body"), candidate.get("cloze-body")
            )
            if bold_badge:
                badges.append(bold_badge)
            child_furigana = candidate.get("Sentence (furigana)")
            if not is_empty(child_furigana):
                if not is_empty(parent_furigana):
                    badges += ("replaces-fragment-furigana",)
                else:
                    # Would leave fragment ruby under the full scene text.
                    checked = False
                    badges += ("stale-fragment-furigana-risk",)
            writes.append(
                PlannedWrite(
                    note_id=candidate.note_id,
                    field="Sentence",
                    op=OP_EXPAND_SENTENCE,
                    old_value=candidate.get("Sentence"),
                    new_value=new_sentence,
                    source_note_id=parent.note_id,
                    default_checked=checked,
                    badges=tuple(badges),
                    window_ms=gap_ms,
                    group_id=group_id,
                )
            )
            if not is_empty(parent_furigana) and is_empty(child_furigana):
                writes.append(
                    PlannedWrite(
                        note_id=candidate.note_id,
                        field="Sentence (furigana)",
                        op=OP_FILL,
                        old_value="",
                        new_value=parent_furigana,
                        source_note_id=parent.note_id,
                        default_checked=checked,
                        badges=tuple(["scene-furigana", *context_badges]),
                        window_ms=gap_ms,
                        group_id=group_id,
                    )
                )
            elif not is_empty(parent_furigana) and not is_empty(child_furigana):
                writes.append(
                    PlannedWrite(
                        note_id=candidate.note_id,
                        field="Sentence (furigana)",
                        op=OP_EXPAND_SENTENCE,
                        old_value=child_furigana,
                        new_value=parent_furigana,
                        source_note_id=parent.note_id,
                        default_checked=checked,
                        badges=tuple(["replaces-fragment-furigana", *context_badges]),
                        window_ms=gap_ms,
                        group_id=group_id,
                    )
                )
        else:
            writes.append(
                PlannedWrite(
                    note_id=candidate.note_id,
                    field="Sentence",
                    op=OP_EXPAND_SENTENCE,
                    old_value=candidate.get("Sentence"),
                    new_value=parent_sentence,
                    source_note_id=parent.note_id,
                    default_checked=False,
                    badges=(
                        "expansion-guard",
                        "fragment-not-recoverable"
                        if not _fragment_recoverable(candidate, cand_norm)
                        else "cloze-anchor-not-unique",
                        *context_badges,
                    ),
                    window_ms=gap_ms,
                    group_id=group_id,
                )
            )

    # Invariant: a Sentence (furigana) fill must never ship default-checked
    # while its paired Sentence expansion is guarded — full-scene ruby under
    # a fragment sentence is a broken card. The furigana fill may originate
    # from the generic fill loop, so pair it here.
    expansion = next(
        (w for w in writes if w.field == "Sentence" and w.op == OP_EXPAND_SENTENCE), None
    )
    if expansion is not None and not expansion.default_checked:
        writes = [
            w
            if not (w.field == "Sentence (furigana)" and w.op == OP_FILL and w.default_checked)
            else replace(w, default_checked=False, badges=(*w.badges, "paired-with-expansion"))
            for w in writes
        ]
    return writes, None


def _word_writes_for(
    candidate: NoteRecord,
    group: list[NoteRecord],
    groups: dict,
    cfg: dict,
) -> list[PlannedWrite]:
    """Fill empty word-level fields from best siblings."""
    writes: list[PlannedWrite] = []
    guard = singleton_kanji_guard(candidate, groups)
    sense_fields = {"Definition", "Extended definition"}
    for fname in cfg.get("word_fill_fields", ()):
        if fname in FIELD_NEVER_COPY or not is_empty(candidate.get(fname)):
            continue
        src = best_word_source(fname, candidate, group)
        if src is None:
            continue
        badges: list[str] = [f"source-note:{src.record.note_id}"]
        if guard and fname in sense_fields:
            badges.append("kanji-attribution-guard")
            continue
        if fname in ("Pitch Accent", "Frequency"):
            badges.append("dictionary-version-may-differ")
        if src.provenance:
            badges.append("yomitan-gloss")
        elif src.consensus >= 2:
            badges.append(f"{src.consensus}-siblings-agree")
        else:
            badges.append("single-source-user-authored")
            if fname in sense_fields:
                # Sense fields need provenance or consensus to be default.
                badges.append("review-sense-field")
        default_checked = bool(cfg.get("replaces_autocheck", True)) and (
            src.provenance or src.consensus >= 2 or fname not in sense_fields
        )
        writes.append(
            PlannedWrite(
                note_id=candidate.note_id,
                field=fname,
                op=OP_FILL,
                old_value="",
                new_value=src.value,
                source_note_id=src.record.note_id,
                default_checked=default_checked,
                badges=tuple(badges),
            )
        )
    return writes


def build_plan(
    records: list[NoteRecord],
    cfg: dict,
    scope_note_ids: list[int] | None = None,
    media_exists=None,
) -> Plan:
    """Build the full plan.

    ``records``: all records in scope (the deck). ``scope_note_ids``: the
    notes to *fix* (targets); all records remain eligible as parents and
    word sources. ``media_exists(filename)``: optional gate — fills
    referencing missing media are dropped with a warning.
    """
    window_ms = min(int(cfg.get("window_days", 3)) * DAY_MS, MAX_WINDOW_MS)
    min_len = int(cfg.get("min_sentence_len", 6))
    cache: dict[int, str] = {}
    by_id = {r.note_id: r for r in records}

    parents_by_id = {
        r.note_id: r
        for r in records
        if sound_files(r.get("Sentence Audio"))
        and r.get("Sentence Audio") is not None
        and (
            media_exists is None
            or all(media_exists(f) for f in sound_files(r.get("Sentence Audio")))
        )
    }

    if scope_note_ids is None:
        scope = [r for r in records if is_blob_source(r.get("Source"))]
    else:
        scope = [by_id[nid] for nid in scope_note_ids if nid in by_id]

    writes: list[PlannedWrite] = []
    reasons: dict[int, str] = {}
    warnings: list[str] = []
    optout = cfg.get("optout_tag", "no-autofill")

    groups = word_groups(records)
    parent_usage: dict[int, int] = {}

    for target in scope:
        if optout in target.tags:
            reasons[target.note_id] = "opted-out"
            continue
        scene_writes, reason = [], None
        has_scene_gap = any(
            is_empty(target.get(f))
            for f in ("Sentence Audio", "Picture", "Sentence (furigana)", "Translation")
        ) or is_blob_source(target.get("Source"))
        if has_scene_gap:
            matches = find_scene_parents(target, parents_by_id, window_ms, min_len, cache)
            scene_writes, reason = _scene_writes_for(target, matches, cfg)
            if reason:
                reasons[target.note_id] = reason
        for w in scene_writes:
            if w.source_note_id:
                parent_usage[w.source_note_id] = parent_usage.get(w.source_note_id, 0) + 1
            if media_exists is not None and w.op == OP_FILL:
                refs = sound_files(w.new_value) or image_files(w.new_value)
                if refs and not all(media_exists(f) for f in refs):
                    warnings.append(
                        f"drop fill note:{w.note_id} field:{w.field} missing media {refs}"
                    )
                    continue
            writes.append(w)
        # Word-level fills apply to every scoped note with word gaps.
        key = word_key(target.get("Expression"), target.get("reading"), target.get("furigana"))
        if key is not None:
            group = groups.get(key, [])
            if len(group) > 1:
                writes.extend(_word_writes_for(target, group, groups, cfg))
        if not any(w.note_id == target.note_id for w in writes) and target.note_id not in reasons:
            reasons[target.note_id] = "nothing-to-fill"

    for parent_id, uses in parent_usage.items():
        if uses > 20:
            warnings.append(f"parent {parent_id} fills {uses} rows — verify manually")

    writes.sort(key=lambda w: (w.note_id, w.field, w.op))
    # De-duplicate identical (note, field, new_value) rows (scene + word
    # matchers can agree on the same fill).
    deduped: list[PlannedWrite] = []
    seen: set[tuple] = set()
    for w in writes:
        k = (w.note_id, w.field, w.op, w.new_value)
        if k in seen:
            continue
        seen.add(k)
        deduped.append(w)
    return Plan(version=PLAN_VERSION, writes=tuple(deduped), reasons=reasons, warnings=warnings)
