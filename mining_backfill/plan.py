"""Plan construction: the single source of truth for preview and apply.

Pure module: no anki/aqt imports.

A :class:`Plan` is a deterministic, versioned list of :class:`PlannedWrite`
plus per-candidate reasons for every note the add-on could not help. The
preview dialog and the applier consume the same plan, so what is shown is
exactly what is written.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace

from .fieldconfig import (
    FIELD_NEVER_COPY,
    image_files,
    is_blob_source,
    is_empty,
    sound_files,
)
from .matching import (
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
from .normalize import kana_fold, norm_sentence_match, strip_renderable, word_key

__all__ = ["PlannedWrite", "Plan", "build_plan", "PLAN_VERSION", "scope_from_selection"]

PLAN_VERSION = 2

OP_FILL = "fill"
OP_REPLACE_SOURCE = "replace_source"
OP_EXPAND_SENTENCE = "expand_sentence"
# Markup-only repair: wrap the tested word in <b> (rendered text unchanged).
OP_BOLD_CLOZE_WORD = "bold_cloze_word"
# Tag-set union from contributing sources; never removes a tag.
OP_ADD_TAGS = "add_tags"
OPS_TOUCHING_NONEMPTY = frozenset(
    {OP_REPLACE_SOURCE, OP_EXPAND_SENTENCE, OP_BOLD_CLOZE_WORD, OP_ADD_TAGS}
)


@dataclass(frozen=True)
class PlannedWrite:
    """One field change. ``old_value`` empty <=> OP_FILL in almost all cases.

    Four ops may write a non-empty value, each guarded: the two approved
    replaces (blob Source — the blob URL is recorded in the audit log;
    fragment Sentence — the fragment survives in cloze-*), the markup-only
    bold repair (``strip_renderable`` of both values must be equal) and the
    tags union (``new_value`` is a superset of ``old_value``). All carry
    badges.
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


_KANJI_HINT_RE = re.compile(r"[㐀-\u4dbf\u4e00-\u9fff]")


def _mixed_form_candidates(expression: str, reading: str) -> list[str]:
    """Mixed-kana spellings of the headword: its leading kanji read as kana.

    Mined sentences often render the headword's leading kanji in kana
    (鬱病 with reading うつびょう appears as うつ病). Per-kanji readings are
    unknown offline, so every (reading-prefix, headword-suffix) pair is a
    candidate; the caller's sentence-occurrence oracle plus the uniqueness
    requirement filter the wrong ones out. Candidates must contain kanji:
    pure-kana strings would match unrelated common words.
    """
    hw = expression.strip()
    rd = kana_fold(reading.strip())
    if len(hw) < 2 or len(rd) < 2 or not _KANJI_HINT_RE.search(hw):
        return []
    out: list[str] = []
    for k in range(1, len(rd)):
        for m in range(1, len(hw)):
            cand = rd[:k] + hw[m:]
            if cand == hw or not _KANJI_HINT_RE.search(cand) or cand in out:
                continue
            out.append(cand)
    return out


def _wrap_first_occurrence(sentence: str, word: str) -> str | None:
    """``word`` wrapped in ``<b>`` at its first occurrence, or None if unsafe.

    Unsafe: the occurrence sits inside an HTML tag (e.g. an attribute
    value). The caller additionally verifies the wrapping is markup-only.
    """
    start = sentence.find(word)
    if start < 0:
        return None
    if sentence.rfind("<", 0, start) > sentence.rfind(">", 0, start):
        return None  # the occurrence lives inside a tag
    return f"{sentence[:start]}<b>{word}</b>{sentence[start + len(word) :]}"


_BOLD_TAG_RE = re.compile(r"<b[\s>]|<strong")


def _bold_repair_for(target: NoteRecord) -> tuple[PlannedWrite | None, str | None, str | None]:
    """Locate the tested word in a bold-less ``Sentence``; markup-only fix.

    The deck convention bolds the mined word inside ``Sentence``; the front
    template keys on it (accent highlight — and its cloze-fallback rebuilds
    the front from cloze-* exactly when no bold term exists). Cards whose
    cloze-* hold dictionary-entry text (mining bug) have no bold; the word
    may still occur as a different surface form.

    Tier 1: the cloze body occurs exactly once. Tier 2 (only when the body
    never occurs): a mixed-kana spelling derived from (Expression, reading)
    occurs exactly once. Ambiguity — more than one occurrence, or several
    candidates — is never resolved by guessing.

    Returns ``(write, reason, detail)``: the write is markup-only
    (``strip_renderable`` equality is verified before it is returned);
    ``reason``/``detail`` explain a miss for the report.
    """
    sentence = target.get("Sentence")
    # <br> must not read as a bold tag: match <b>/<b attrs>/<strong only.
    if is_empty(sentence) or _BOLD_TAG_RE.search(sentence):
        return None, None, None
    body = strip_renderable(target.get("cloze-body")).strip()
    if not body:
        return None, None, None  # nothing was mined: the convention cannot apply
    count = sentence.count(body)
    if count > 1:
        return None, "cloze-word-ambiguous", f"cloze word '{body}' occurs {count} times"
    if count == 1:
        new_value = _wrap_first_occurrence(sentence, body)
        if new_value is not None and strip_renderable(new_value) == strip_renderable(sentence):
            write = PlannedWrite(
                note_id=target.note_id,
                field="Sentence",
                op=OP_BOLD_CLOZE_WORD,
                old_value=sentence,
                new_value=new_value,
                default_checked=True,
                badges=("bold-added-to-cloze-word",),
            )
            return write, None, None
        return (
            None,
            "cloze-word-not-in-sentence",
            f"cloze word '{body}' has no anchor outside HTML markup",
        )
    # The cloze body never occurs (dictionary-entry junk): try the
    # reading-derived surface forms.
    hits = [
        (cand, sentence.count(cand))
        for cand in _mixed_form_candidates(target.get("Expression"), target.get("reading"))
        if cand in sentence
    ]
    single = [cand for cand, n in hits if n == 1]
    multi = [(cand, n) for cand, n in hits if n > 1]
    if len(single) == 1 and not multi:
        new_value = _wrap_first_occurrence(sentence, single[0])
        if new_value is not None and strip_renderable(new_value) == strip_renderable(sentence):
            write = PlannedWrite(
                note_id=target.note_id,
                field="Sentence",
                op=OP_BOLD_CLOZE_WORD,
                old_value=sentence,
                new_value=new_value,
                default_checked=True,
                badges=("bold-added-to-surface-form",),
            )
            return write, None, None
    if not hits:
        return (
            None,
            "cloze-word-not-in-sentence",
            f"cloze word '{body}' and its reading-derived forms never occur in it",
        )
    listed = ", ".join(f"'{cand}' ×{n}" for cand, n in sorted(hits))
    return None, "cloze-word-ambiguous", f"surface-form candidates: {listed}"


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


_ANKI_CONTROL_TAGS = frozenset({"marked", "leech"})


def _reserved_tags(cfg: dict) -> frozenset[str]:
    """Tags that must never propagate from a source card onto a target."""
    return frozenset(
        {
            *_ANKI_CONTROL_TAGS,
            cfg.get("optout_tag", "no-autofill"),
            cfg.get("applied_tag", "auto-filled"),
        }
    )


def _tags_write_for(
    target: NoteRecord,
    target_writes: list[PlannedWrite],
    records_by_id: dict[int, NoteRecord],
    cfg: dict,
) -> PlannedWrite | None:
    """Union the target's tags with every contributing source's tags.

    Only sources of default-checked writes contribute: a card the plan does
    not act on has not earned tag authority. Control tags (Anki's
    marked/leech and this tool's own optout/applied tags) never propagate.
    The op can only ADD: ``new_value`` is a superset of ``old_value`` —
    that is the badge's contract.
    """
    reserved = _reserved_tags(cfg)
    new_tags = set(target.tags)
    sources = sorted(
        {
            w.source_note_id
            for w in target_writes
            if w.default_checked and w.source_note_id is not None
        }
    )
    for source_id in sources:
        source = records_by_id.get(source_id)
        if source is not None:
            new_tags |= set(source.tags) - reserved
    if new_tags == set(target.tags):
        return None
    return PlannedWrite(
        note_id=target.note_id,
        field="tags",
        op=OP_ADD_TAGS,
        old_value=" ".join(sorted(target.tags)),
        new_value=" ".join(sorted(new_tags)),
        default_checked=True,
        badges=("tags-union-never-removes",),
    )


def scope_from_selection(
    selected: Sequence[int], available: Iterable[int]
) -> tuple[list[int], list[int]]:
    """Resolve a Browser selection to ``(scope, unknown)``, order preserved.

    Duplicates are dropped and the user's selection order is kept. Ids that
    are not in ``available`` are reported separately so the caller can explain
    them (deleted notes, another note type) instead of silently dropping them
    from the run.
    """
    known = set(available)
    seen: set[int] = set()
    scope: list[int] = []
    unknown: list[int] = []
    for note_id in selected:
        if note_id in seen:
            continue
        seen.add(note_id)
        if note_id in known:
            scope.append(note_id)
        else:
            unknown.append(note_id)
    return scope, unknown


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
        target_writes: list[PlannedWrite] = []
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
            target_writes.append(w)
        # Word-level fills apply to every scoped note with word gaps.
        key = word_key(target.get("Expression"), target.get("reading"), target.get("furigana"))
        if key is not None:
            group = groups.get(key, [])
            if len(group) > 1:
                target_writes.extend(_word_writes_for(target, group, groups, cfg))
        # Markup-only bold repair. Never issued when a Sentence expansion is
        # queued for the same note: the two ops would fight over the field.
        bold_write, bold_reason, bold_detail = _bold_repair_for(target)
        queued_expansion = any(
            w.field == "Sentence" and w.op == OP_EXPAND_SENTENCE for w in target_writes
        )
        if bold_write is not None and not queued_expansion:
            target_writes.append(bold_write)
        elif bold_reason is not None:
            suffix = " (Sentence is also queued for scene expansion)" if queued_expansion else ""
            expr = target.get("Expression") or "(sentence card)"
            warnings.append(
                f"note {target.note_id} ({expr}): no bold in Sentence — {bold_detail}{suffix}"
            )
            if not target_writes and target.note_id not in reasons:
                reasons[target.note_id] = bold_reason
        # Tags: union of the target's tags with every contributing source's.
        tags_write = _tags_write_for(target, target_writes, by_id, cfg)
        if tags_write is not None:
            target_writes.append(tags_write)
        if not target_writes and target.note_id not in reasons:
            reasons[target.note_id] = "nothing-to-fill"
        if target_writes:
            reasons.pop(target.note_id, None)
        writes.extend(target_writes)

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
