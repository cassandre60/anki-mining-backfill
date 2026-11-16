# Future Features — ideas, not commitments

Text dump of the author's ideas. Nothing here is in scope; work enters through
`IMPLEMENTATION_PLAN.md` (Backlog B6) only when it is designed, tested and
documented like everything else.

## Vocabulary (the author's lingo)

- **Source card** — a fully mined card: every field filled correctly (full
  scene `Sentence`, `Sentence (furigana)`, scene audio, picture, timestamped
  `Source`, word fields). It is the card the add-on copies *from*.
- **Child card** — a card related to a source card: mined from the same show,
  typically a few minutes apart, and sharing the same sentence block (the
  child's mined fragment is contained in the source's scene sentence). This is
  exactly the relation the scene matcher tries to establish.

## F1 — Fix the source card *before* fixing the children

Today the add-on treats a source card as ground truth: whatever its `Sentence`
holds is copied to the children. That is backwards when the source itself is
imperfect — and asbplayer/Yomitan sources usually are:

- **Arrows.** asbplayer inserts the continuation marker `➡` (and sometimes
  `→`) where a subtitle line was cut. The marker is punctuation noise that the
  reader has to ignore, and it leaks into every child.
- **Spacing and line breaks.** Subtitles are broken with `<br>` and padded
  with spaces for on-screen line fitting, so the text does not correspond
  one-to-one to what the audio says. A card whose `Sentence` reads as a stack
  of screen lines is harder to read and to compare with the audio than one
  flowing sentence.
- **Furigana.** The source may have no `Sentence (furigana)` at all (the
  Yomitan card was mined before furigana was generated), so every child
  inherits a ruby-less sentence.

### Proposed pipeline (source first, children second)

```text
1. Pick the source cards in a selection (they are the cards with audio,
   picture, a full scene sentence and a timestamped Source).
2. Normalise the source's Sentence:
     - remove continuation arrow markers (➡ / →), configurable
     - keep the `<br>`s and spacing exactly as mined (owner decision
       2026-11-15: line breaks are the sentence's pause structure; the
       audio-aligned direction in BULK_FIX.md replaces heuristic joining)
     - (optional) drop speaker/stage tags such as [TEL] (受付)
3. Rebuild the source's Sentence (furigana) from the normalised text.
     Japanese Support (the installed `Japanese Support` add-on, id
     3918629684) exposes `bulkreading.regenerateReadings(nids)` and
     `reading.regenerateReading(note, src_field)`; its public entry refuses
     non-empty destination fields, so the shipped dimension (T12) calls the
     same engine directly — `reading.mecab.reading(text)` — instead of
     writing our own generator. Verify the entry point against the
     installed source before depending on it (re-verified 2026-11-15).
4. Write those two fields on the source card — previewed, checked, logged,
   undoable, exactly like every other write.
5. Only then plan the children, so they inherit the clean sentence and
   furigana in one pass instead of copying the noise first and being fixed
   twice.
```

### Why it matters

- A source card is used by **many** children. Fixing one source fixes N cards;
  fixing children first multiplies the same defect N times.
- Children's `cloze-*` fields still contain the original fragment, so the
  normalisation must not destroy the anchor: the same recoverability rule as
  today (`cloze-prefix + body + suffix` must still appear in the new sentence)
  has to gate the write.
- `Sentence` and `Sentence (furigana)` must always be rewritten together; a
  normalised sentence under old ruby is a broken card (the existing
  `stale-fragment-furigana-risk` guard exists for the same reason).

### Risks / hard parts

1. **This is a non-empty write on a source card** — the largest trust step so
   far. It must be opt-in, previewed with an exact old → new diff, and
   reversible from the same run log as everything else. A new "source
   normalisation" policy tier belongs in `batch.py`, default off.
2. **Arrows and spaces are not always noise.** `➡` can be the author's own
   separator inside a long quote; `→` can be a dialogue dash. The removal list
   must be config-driven and the diff must be shown before applying.
3. **Children already filled from the old source** become stale. Either
   re-plan them in the same run (source first), or mark them for review when
   the source sentence changed after their fill (a "source changed since this
   card was filled" check needs a record of what was copied — the run log has
   it).
4. **Audio coherence cannot be verified offline.** We can normalise the text
   but not prove it matches the audio; the user is the judge. So the preview
   has to make the change obvious (side-by-side old/new, arrow/spacing counts).
5. **Furigana quality** depends on the external add-on and on the text being
   Japanese-clean; generated ruby must be stored exactly as that add-on
   produces it (no re-formatting), and a failed generation must leave the
   field untouched rather than half-written.

### Prerequisites / related backlog

- B4 (multi-note-type configuration) — source card detection depends on field
  names.
- Per-run "diff view" for a whole field (old vs new side by side) — useful
  beyond this feature.
- A `source_auto_gap_hours`-style confidence rule for *which* cards count as
  sources (already partially there: audio + full sentence + timestamped
  source).
- A test fixture with a real arrow/`<br>`-laden source sentence and its
  expected normalised form, plus its regenerated furigana, so the pipeline is
  pinned byte-exactly like the golden scene test.

### Experiments to run before designing it

1. Collect 20 source cards from the real collection; count arrows and
   missing furigana per card — is normalisation a 50% or a 5% problem?
   (Answered for the whole deck by the 2026-11-15 census, BULK_FIX.md:
   arrows 0.4%; `<br>` 72.1% but kept as mined by owner decision.)
2. Run Japanese Support's `regenerateReadings` on those 20 cards manually and
   eyeball the ruby; does it beat what Yomitan already stored?
3. Check whether any existing child cards were already filled from those
   sources (the run logs say so) — that tells us how much migration the
   change implies.

## Where each idea lives (traceability)

Every ask from the author, and where it is written down so it can be built
later. Status is one of *shipped*, *documented* (no code yet).

| Owner ask | Documented in | Status |
|---|---|---|
| Bulk fixer: select many cards, pick dimensions, apply, no per-card review | `BULK_FIX.md` (whole file), `QUALITY.md` Q-C9 | propagation + window shipped |
| Fix the source card before the children | `BULK_FIX.md` §Ordering, this file §F1 | documented (slices 1–2) |
| Sentence repair: remove continuation arrows, fix spacing and line breaks so the text coheres with the audio | `BULK_FIX.md` dimension 2, this file §F1 | documented (slice 1) |
| Generate furigana **after** the sentence is fixed, through the installed Japanese Support add-on | `BULK_FIX.md` dimension 3, this file §F1 | documented (slice 2) |
| Fix the expression itself: inflections, expressions written partly in kana where the kanji form exists | `BULK_FIX.md` dimension 4 | documented (slice 4) |
| Cards with no bold term in `Sentence` (non-listening): bold the expression's inflected occurrence — 前人未到 is a valid target, 漢字は読めるようになりたいかな is not | `BULK_FIX.md` dimension 6 + slice 8 (census 2026-11-16) | documented |
| Indentation / formatting | `BULK_FIX.md` dimension 5 | documented (slice 5) |
| Apply to other decks when they are selected | `BULK_FIX.md` §Scope and profiles | targets shipped; sources still limited to the configured deck |
| Apply to other languages (Chinese, …) and other note types | `BULK_FIX.md` §Scope and profiles, slice 6 | documented (profile abstraction) |
| "Ideally there should be no notes that need humans" | `QUALITY.md` Q-C9, `BULK_FIX.md` §The target experience | shipped (left alone with a reason; no decision queue) |
| A report a human can read, not a data dump | `report.render_batch_summary`, `README.md` | shipped |
| Never crash the author's machine again | `AGENTS.md` §2 rules 2–3, Lessons Learned | shipped (rules in force) |

## Other candidates (already listed elsewhere)

- Browser integration for source cards (select sources, fix them, then their
  children in the same run).
- Rendered front/back preview per row (`MVP.md` B2).
- AnkiWeb release and packaging (`MVP.md` B3).
- Anki's own note history / backup browser as the recovery path, instead of
  only our run log.