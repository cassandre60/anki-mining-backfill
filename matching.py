"""Scene and word matching over mining-note records.

Pure module: no anki/aqt imports. Callers pass :class:`NoteRecord` values
built from any backend (live Anki, the headless ``anki`` library, or test
fixtures).

Scene matching implements the verified user workflow:

- A *candidate* is an unenriched card (Source is still the asbplayer blob
  URL, no Sentence Audio).
- A *parent* is an enriched card (has Sentence Audio) whose normalized
  Sentence CONTAINS the candidate's normalized Sentence.
- Mining sessions cluster in time, so parents are only searched within a
  temporal window around the candidate's note id (a millisecond creation
  timestamp). Window is a hard cap: no silent widening, misses are
  reported for review.
- Word matching groups notes by (normalized Expression, normalized
  reading) and fills empty word-level fields from the best sibling.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

from fieldconfig import (
    eligible_source,
    is_blob_source,
    is_empty,
    looks_yomitan_gloss,
)
from normalize import (
    norm_sentence_match,
    word_key,
)

__all__ = [
    "NoteRecord",
    "SceneMatch",
    "WordSource",
    "find_scene_parents",
    "rank_scene_parents",
    "word_groups",
    "best_word_source",
]

DAY_MS = 86_400_000
# Never widen silently past this; user must change config explicitly.
MAX_WINDOW_MS = 14 * DAY_MS
# A span starting/ending at a punctuation boundary is trustworthy; interior
# spans are allowed (the user's own golden case has no leading boundary)
# but flagged.
_BOUNDARY_CHARS = "。、！？!?「」『』（）()【】….,:;"


@dataclass(frozen=True)
class NoteRecord:
    """Immutable snapshot of one note. The aqt/core seam: plain data only."""

    note_id: int
    notetype_id: int
    fields: dict[str, str]
    tags: frozenset[str] = frozenset()

    def get(self, name: str) -> str:
        return self.fields.get(name, "") or ""


@dataclass
class SceneMatch:
    """One containing parent for a candidate."""

    parent: NoteRecord
    tier_gap_ms: int  # |parent.note_id - candidate.note_id|
    exact_equal: bool  # parent sentence equals candidate sentence
    boundary_ok: bool  # span starts/ends at punctuation boundary
    fillable: int  # number of candidate gaps this parent can fill
    fill_payload: tuple  # values it would write (for agreement checks)


@dataclass
class WordSource:
    """A sibling able to supply one word-level field."""

    record: NoteRecord
    value: str
    provenance: bool  # Yomitan gloss provenance
    consensus: int  # siblings agreeing on the normalized value


# --- scene matching ---------------------------------------------------------


def _normalized(record: NoteRecord, cache: dict[int, str]) -> str:
    if record.note_id not in cache:
        cache[record.note_id] = norm_sentence_match(record.get("Sentence"))
    return cache[record.note_id]


def _boundary_ok(candidate_norm: str, parent_norm: str, start: int) -> bool:
    """Span must start at a boundary and end at parent end or boundary.

    Interior spans are tolerated by the caller (user's golden case) but
    flagged; a span not ending at a boundary is a stronger FP signal and
    returns False, unless the parent ends exactly there.
    """
    ok_start = (
        start == 0
        or candidate_norm[0] in _BOUNDARY_CHARS
        or parent_norm[start - 1] in _BOUNDARY_CHARS
    )
    end = start + len(candidate_norm)
    ok_end = end == len(parent_norm) or parent_norm[end] in _BOUNDARY_CHARS
    return ok_start and ok_end


def find_scene_parents(
    candidate: NoteRecord,
    parents_by_id: dict[int, NoteRecord],
    window_ms: int = 3 * DAY_MS,
    min_len: int = 6,
    cache: dict[int, str] | None = None,
) -> list[SceneMatch]:
    """Parents within the temporal window whose Sentence contains the candidate's.

    ``parents_by_id`` must contain only audio-bearing enriched notes.
    The window is symmetric around the candidate's note id (creation
    timestamp) and a hard cap; callers widen only by re-running with a
    larger config value.
    """
    cache = cache if cache is not None else {}
    ctext = _normalized(candidate, cache)
    if len(ctext) < min_len:
        return []
    ids = sorted(parents_by_id)
    lo = bisect.bisect_left(ids, candidate.note_id - window_ms)
    hi = bisect.bisect_right(ids, candidate.note_id + window_ms)
    matches: list[SceneMatch] = []
    for nid in ids[lo:hi]:
        parent = parents_by_id[nid]
        ptext = _normalized(parent, cache)
        start = ptext.find(ctext)
        if start < 0:
            continue
        exact = ptext == ctext
        matches.append(
            SceneMatch(
                parent=parent,
                tier_gap_ms=abs(parent.note_id - candidate.note_id),
                exact_equal=exact,
                boundary_ok=_boundary_ok(ctext, ptext, start),
                fillable=0,
                fill_payload=(),
            )
        )
    return matches


def _fillable_and_payload(
    candidate: NoteRecord, parent: NoteRecord, optin_fields: tuple[str, ...]
) -> tuple[int, tuple]:
    """Count gaps this parent can fill and the exact payload it would write."""
    payload: list[tuple[str, str]] = []
    count = 0
    for fname in ("Sentence Audio", "Picture", "Sentence (furigana)", "Translation", *optin_fields):
        if not is_empty(candidate.get(fname)):
            continue
        value = parent.get(fname)
        if not eligible_source(fname, value):
            continue
        payload.append((fname, value))
        count += 1
    if is_blob_source(candidate.get("Source")) and not is_blob_source(parent.get("Source")):
        payload.append(("Source", parent.get("Source")))
        count += 1
    return count, tuple(payload)


def rank_scene_parents(
    matches: list[SceneMatch],
    candidate: NoteRecord,
    optin_fields: tuple[str, ...] = ("Notes", "context", "Kanji Notes"),
) -> list[SceneMatch]:
    """Order matches by: exact-equality, fillability, tightness, recency.

    1. Parents that fill nothing are dropped.
    2. Exact sentence-equality first (Tier E).
    3. Among containment matches: shorter parent (tightest clip), then
       smaller |id gap| (same session), then more fillable, then lowest id.
    """
    scored: list[SceneMatch] = []
    for m in matches:
        fillable, payload = _fillable_and_payload(candidate, m.parent, optin_fields)
        if fillable == 0:
            continue
        m.fillable = fillable
        m.fill_payload = payload
        scored.append(m)
    scored.sort(
        key=lambda m: (
            0 if m.exact_equal else 1,
            len(norm_sentence_match(m.parent.get("Sentence"))),
            m.tier_gap_ms,
            -m.fillable,
            m.parent.note_id,
        )
    )
    # Dedup identical normalized keys (two parents with byte-identical
    # sentences and payloads collapse into one agreement group).
    return scored


def agreement_groups(ranked: list[SceneMatch]) -> dict[tuple, list[SceneMatch]]:
    """Group ranked parents by the payload they would write.

    Parents writing identical values are not "ambiguous": they agree. Only
    divergent payloads need user review.
    """
    groups: dict[tuple, list[SceneMatch]] = {}
    for m in ranked:
        groups.setdefault(m.fill_payload, []).append(m)
    return groups


def word_groups(records: list[NoteRecord]) -> dict[tuple[str, str], list[NoteRecord]]:
    """Group records by (normalized Expression, normalized reading).

    Reading-only grouping is intentionally absent: it mixes distinct words
    that share a reading (氏/詩/師 all read し). Kana-only expressions are
    returned in their own group; callers may treat them as low-trust.
    """
    groups: dict[tuple[str, str], list[NoteRecord]] = {}
    for r in records:
        key = word_key(r.get("Expression"), r.get("reading"), r.get("furigana"))
        if key is None:
            continue
        groups.setdefault(key, []).append(r)
    return groups


def best_word_source(
    field_name: str,
    candidate: NoteRecord,
    group: list[NoteRecord],
) -> WordSource | None:
    """Pick the best sibling value for one empty word-level field.

    Selection order: Yomitan gloss provenance, then consensus (number of
    siblings agreeing on the normalized value), then earliest note id.
    Junk values are ineligible sources. ``candidate`` itself is excluded.
    """
    candidates: list[WordSource] = []
    for r in group:
        if r.note_id == candidate.note_id:
            continue
        value = r.get(field_name)
        if not eligible_source(
            field_name, value, expression=r.get("Expression"), reading=r.get("reading")
        ):
            continue
        candidates.append(
            WordSource(
                record=r,
                value=value,
                provenance=looks_yomitan_gloss(value),
                consensus=0,
            )
        )
    if not candidates:
        return None
    # Consensus: how many sources share the candidate's normalized value.
    from normalize import strip_renderable  # local import keeps cycle-free

    norm_values = [strip_renderable(c.value).strip() for c in candidates]
    for c, norm_val in zip(candidates, norm_values, strict=True):
        c.consensus = sum(1 for v in norm_values if v == norm_val)
    candidates.sort(key=lambda c: (not c.provenance, -c.consensus, c.record.note_id))
    return candidates[0]


def singleton_kanji_guard(
    candidate: NoteRecord,
    groups: dict[tuple[str, str], list[NoteRecord]],
) -> bool:
    """True when the candidate's kanji Expression looks like a Yomitan
    kanji-attribution artifact (e.g. ``尾ける`` for おける).

    Heuristic: the exact (Expression, reading) group is a singleton while
    another group with the same reading and a kana-only (or kanji-less)
    expression has two or more members. Sense fields must then not be
    auto-filled; media/furigana/reading may still be.
    """
    key = word_key(candidate.get("Expression"), candidate.get("reading"), candidate.get("furigana"))
    if key is None:
        return False
    expr, read = key
    if len(groups.get(key, [])) > 1:
        return False
    if not re.search(r"[㐀-\u4dbf\u4e00-\u9fff]", expr):
        return False  # kana-only singleton is not an artifact
    for (other_expr, other_read), members in groups.items():
        if (
            other_read == read
            and other_expr != expr
            and len(members) >= 2
            and not re.search(r"[㐀-\u4dbf\u4e00-\u9fff]", other_expr)
        ):
            return True
    return False
