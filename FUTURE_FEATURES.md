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
     - collapse the `<br>`s and padding spaces into one readable line
     - (optional) drop speaker/stage tags such as [TEL] (受付)
3. Rebuild the source's Sentence (furigana) from the normalised text.
     Japanese Support (the installed `Japanese Support` add-on, id
     3918629684) already exposes `bulkreading.regenerateReadings(nids)` and
     `reading.regenerateReading(note, src_field)`; use its MeCab/Kakasi
     reading instead of writing our own generator. Verify the entry point
     against the installed source before depending on it.
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

1. Collect 20 source cards from the real collection; count arrows, `<br>`s,
   padding spaces and missing furigana per card — is normalisation a 50% or a
   5% problem?
2. Run Japanese Support's `regenerateReadings` on those 20 cards manually and
   eyeball the ruby; does it beat what Yomitan already stored?
3. Check whether any existing child cards were already filled from those
   sources (the run logs say so) — that tells us how much migration the
   change implies.

## Other candidates (already listed elsewhere)

- Browser integration for source cards (select sources, fix them, then their
  children in the same run).
- Rendered front/back preview per row (`MVP.md` B2).
- AnkiWeb release and packaging (`MVP.md` B3).
- Anki's own note history / backup browser as the recovery path, instead of
  only our run log.