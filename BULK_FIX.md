# Mining Fixer — Bulk Fix (product vision)

What this add-on becomes: a **bulk fix extension**, not a reviewer of single
cards. The user selects a huge number of cards — up to a million — picks the
*dimensions* they want fixed, presses apply, and they are simply fixed. No
per-card review, no decision queue, no debug-tool feel: few words on screen,
one action, done. This file is the owner's product vision, not committed
scope; every item is marked *shipped*, *in progress* or *future*, and work
enters through `IMPLEMENTATION_PLAN.md`.

## Vocabulary

- **Source card** — a fully mined card: full scene `Sentence`,
  `Sentence (furigana)`, scene audio, picture, timestamped `Source`, word
  fields. The card the add-on copies *from*.
- **Child card** — a card related to a source card: same show, usually
  minutes later, sharing the same sentence block (its mined fragment is
  contained in the source's scene sentence). This is exactly the relation
  the scene matcher establishes.

## The target experience

Select cards across the Browser, tick the dimensions, press apply. The tool
resolves every guard itself: what is provably safe is written, what is not
is *left alone with a reason* in the preview report. The dialog shows
counts, not rows — the contract `batch.py` already ships, kept as the
selection grows and as more dimensions are added.

## Dimensions

Each dimension is an independent, individually toggleable policy with its
own evidence rules and guards. The shipped propagation dimension is on by
default (its replaces are information-preserving); **every new dimension
stays off by default until it is proven on a real collection**.

| # | Dimension | Status | What it fixes | Evidence / guards |
|---|---|---|---|---|
| 1 | Source–child fixes (scene propagation) | **shipped** | `Sentence`, `Sentence (furigana)`, scene audio, picture, `Translation`, timestamped `Source` onto children | source-confidence (`divergent-parents`, `far-from-source`), text-safety (`fragment-not-recoverable`, `cloze-anchor-not-unique`, `stale-fragment-furigana-risk`) |
| 2 | Sentence repair | **shipped, off by default** | remove line-tail continuation arrows (`➡` / `→`); `<br>` line breaks and spacing stay exactly as mined (owner decision 2026-11-15) | config-driven rule list (`strip-arrows`); `cloze-*` fragment anchor must still be found; old → new diff in the report |
| 3 | Furigana generation | **shipped, off by default** | rebuild `Sentence (furigana)` from the note's own post-write sentence | runs *after* repair in one plan; `reading.mecab.reading` of Japanese Support (installed, id 3918629684) — never a home-grown generator; base-text guard + engine-failure reasons |
| 4 | Expression repair | **future** | fix inflections; repair an expression written partly in kana when the kanji form exists | needs a per-expression oracle; ambiguity reported, never guessed |
| 5 | Indentation / formatting | **future** | normalise leading/trailing whitespace, line indentation in formatted fields | markup-only or explicitly opt-in; rendered-text equality checked per write |

Dimension 1 is what `batch.py` + `collection_io.apply_batch` ship today.
Dimensions 2 and 3 have code (`normalize.repair_sentence` /
`normalize.furigana_base_matches`, the `repair_sentence` and
`regenerate_furigana` ops) and ship **off by default**
(`sentence_repair_rules: []` / `batch_repair_sentence: false`,
`batch_regenerate_furigana: false`) until their Ring 3 battery on a copy; the
remaining dimensions are on the backlog (B6 the source-first pipeline, B7
this vision); none has code yet, and none will ship enabled by default.

## Ordering (the DAG)

Order matters. Repairing a child before its source copies the source's
defect N times; repairing the source first fixes N cards in one pass. The
dimensions therefore form a small directed acyclic graph and later
dimensions read the output of earlier ones:

```text
discover source cards          (audio + picture + full sentence + timestamped Source)
   │
repair source Sentence         (dimension 2 — deterministic text rules)
   │
regenerate source furigana     (dimension 3 — Japanese Support, on repaired text)
   │
propagate source → children    (dimension 1 — the shipped scene matcher)
   │
later dimensions               (4 expression repair, 5 indentation/formatting)
```

Two rules are non-negotiable: **sentence repair precedes furigana
generation** (ruby for text the card will not keep is wasted work), and
**both precede propagation** (children inherit one clean, ruby-complete
sentence instead of the noise).

## Audio-aligned line breaks (owner vision, recorded 2026-11-15)

The heuristic line-break and padding rules shipped on 2026-11-15 and were
rolled back the same day: the owner keeps `<br>` and spacing exactly as
mined. The direction that replaces the heuristics is **derive the line
breaks from the audio**, not from text rules:

- **Vision.** A program listens to the card's `Sentence Audio` and makes
  the sentence's line breaks (and padding) mimic the speaker's actual
  pauses. Example: a card holding あしたの朝刊の見出しはこうニャ！ becomes
  あしたの朝刊の見出しは<br>こうニャ！ when the speaker pauses a moment
  before こうニャ！ in the audio. This pairs with the shipped
  `strip-arrows` rule: the subtitle's tail arrow marks "the line
  continues", and the audio decides where the line actually breaks.
- **How it would work.** Forced alignment of the known sentence text
  against the audio (word-level timestamps, e.g. Whisper- or
  wav2vec2-based), inserting a `<br>` where the pause exceeds a threshold.
- **Why it is not built now.**
  - Alignment models are large (hundreds of MB) and are normally
    downloaded from the network — the add-on is fully offline
    (AGENTS.md §2 rule 8).
  - Alignment is compute-heavy per card — no heavy jobs on the author's
    machine (AGENTS.md §2 rule 3); it would have to run as a separate
    offline pre-pass the owner starts deliberately (or on CI / a second
    machine), writing results back through a log the add-on consumes.
  - Every card needs its audio file present and readable before it can be
    aligned at all.
- **Cheaper intermediate, if wanted.** Japanese subtitles encode in-line
  pauses as a full-width space (the broadcast-subtitlers' 内分 space —
  verify against a style guide before depending on this); the deck's
  padding census found such spaces in only 0.3% of notes, so the win is
  small either way.
- **Entry point.** A new bulk-fix dimension behind its own opt-in op, off
  by default, designed through this file and shipped via
  `IMPLEMENTATION_PLAN.md`.

## Scope and profiles

- **Targets** may come from any deck, as long as they use the configured
  note type; a selected note of another note type is reported and skipped.
- **Sources** currently come from the **configured deck only**
  (`collection_io.deck_records`). This is a real limitation: a child outside
  the configured deck can still be a target but cannot be sourced from its
  own deck's siblings. Widening the source set is future work.
- **Multi-note-type and multi-language** support (e.g. Chinese) are future
  work. They require a **profile** abstraction: which fields hold the
  sentence, the reading and the definition; how bold is spelled; how ruby
  generation is hooked. Today those are hard-coded Japanese conventions and
  the matching heuristics are **Japanese-specific** — kanji/kana folding,
  the `(Expression, reading, furigana)` word key, reading-derived surface
  forms. Until a profile exists, applying a dimension to a non-Japanese
  deck is out of scope and must fail loudly, not guess.

## Safety model

The sentence "select a million cards, press apply" is only acceptable
because every dimension obeys the same model, at any scale. Every line below
is **shipped** today in `collection_io.apply_batch`; new dimensions reuse it:

- **Forced Anki backup first**, aborting without writing if the backup fails.
- **Undo log written before the first write**, so a crash is still reversible.
- **Chunked writes**, leaving a partially applied but fully logged run.
- **Post-write verification** re-reads every written value and reports misses.
- **No write when confidence is insufficient** — the note is reported, never
  guessed; every new dimension must add its own guards.
- **Dry-run report** available with zero writes.
- **Fully offline** — no network, no telemetry.

## Build plan

Ordered slices. Each ships **independently** and stays **off by default**
until proven on a real collection. "Tests" means the hermetic suite;
"real-collection check" means the Ring 3 run on an existing snapshot, never
the live profile (AGENTS.md §2 rules 2–3) — and it is a **curated battery,
not a bulk 1000-note run** (owner guidance, 2026-11-16): twelve cards, one
per defect class, so a failure names the class it broke (table in
`TEST_STRATEGY.md`). The 1000-note run of T8 stands as the one-off scale
proof.

### Slice 1 — Sentence repair rules (dimension 2)

- **Goal.** Strip the configured continuation arrows from a source
  `Sentence`'s line tails; keep the `cloze-*` anchor findable. Line breaks
  (`<br>`) and spacing stay as mined (owner decision 2026-11-15 — the
  heuristic joining was rolled back the day it shipped; see
  "Audio-aligned line breaks" below for what replaces it).
- **Modules.** `normalize.py` (pure text rules), a new opt-in op in
  `plan.py` / `batch.py`, config keys in `config.json`, diff rendering in
  `report.py`.
- **Acceptance.** A pinned fixture (real arrow sentence → expected
  normalised form) passes; the fragment-recoverability guard still fires;
  Ring 3 run on a copy shows the old → new diff and an exact undo.
- **Risks.** Arrows are not always noise (`➡` as a separator, `→` as a
  dialogue dash): the rule list must be config-driven and diffed before apply.

### Slice 2 — Furigana regeneration (dimension 3)

- **Goal.** Rebuild the note's `Sentence (furigana)` from its own
  post-write Sentence through Japanese Support. Shipped as T12
  (`PLAN_VERSION` 4), off by default (`batch_regenerate_furigana: false`).
- **Modules.** `collection_io.py` (the only Anki-facing caller:
  `japanese_support_furigana_generator`), the `regenerate_furigana` op in
  `plan.py` / `batch.py`, the base-text guard in `normalize.py`
  (`furigana_base_matches`), config toggle.
- **Acceptance.** Generation runs only after repair (one plan, the
  post-write sentence is the input); a failed generation leaves the field
  untouched (never half-written — empty result or raised engine = reason,
  not write); ruby stored exactly as the add-on's reading produces it
  (entry point re-verified 2026-11-15); curated Ring 3 battery confirms
  children inherit the regenerated ruby.
- **Risks.** Depends on an external add-on whose entry points may change —
  re-verify against the installed source before depending on them
  (`reading.mecab.reading` is the engine; the public
  `regenerateReading` refuses non-empty destinations, so it cannot repair
  a wrong value).

### Slice 3 — Source-changed-since-filled reconciliation

- **Goal.** Detect children already filled from a source whose sentence has
  since changed, and re-plan or flag them.
- **Modules.** `plan.py` / `batch.py`, run-log reading in `applier.py`.
- **Acceptance.** A child filled from an old source is re-planned in the
  same run (source first), or marked for review when the source changed
  after its fill; Ring 3 confirms no child is left holding stale text.
- **Risks.** Needs a record of *what was copied* — the run log has it, but
  only for runs this tool performed.

### Slice 4 — Expression repair (dimension 4)

- **Goal.** Fix inflections and kana-only expressions where the kanji form
  exists.
- **Modules.** `normalize.py`, `plan.py`, word-group logic in `matching.py`.
- **Acceptance.** Only unambiguous rewrites ship; every ambiguity is a
  reason in the report; Ring 3 review.
- **Risks.** Highest guess risk of every dimension — must stay opt-in.

### Slice 5 — Indentation / formatting (dimension 5)

- **Goal.** Normalise whitespace and indentation in formatted fields.
- **Modules.** `normalize.py`, a new markup-only op alongside the bold
  repair.
- **Acceptance.** `strip_renderable(new) == strip_renderable(old)` verified
  per write; Ring 3 confirms rendered output unchanged.
- **Risks.** Whitespace can be load-bearing in a template; prove it is not.

### Slice 6 — Note-type / language profiles

- **Goal.** A profile abstraction (fields, bold convention, ruby hook) so a
  second mining setup or language can be served.
- **Modules.** `fieldconfig.py`, `config.json`, guard code throughout.
- **Acceptance.** A non-Japanese profile cannot silently run Japanese
  heuristics; Ring 3 on a second note type.
- **Risks.** Largest refactor; do it only once a second setup actually
  exists.

## Open questions (answer before each slice)

- How many source cards actually contain arrows / `<br>` / padding — a 50%
  problem or a 5% one? **Answered (2026-11-15, one read-only SQL census over
  the configured deck's `Sentence` field, 17,589 notes):** `<br>` **72.1%**,
  arrows `➡`/`→` **0.4%** (75 notes), padding (run-together spaces,
  indented or empty leading/trailing lines) **0.3%** (57 notes), any of
  them **72.2%**. The problem is `<br>` collapse, not arrows — but the
  **owner decision of 2026-11-15 keeps `<br>` and padding exactly as
  mined**: the line breaks are the sentence's pause structure, and the
  heuristic collapse was rolled back the day it shipped. Only `strip-arrows`
  ships. The rule list stays config-driven so arrows remain available
  without dominating the design.
- Does Japanese Support's reading beat what Yomitan already stored? Run it
  on a sample and compare.
- How do we detect "this child was already filled from that source and the
  source has since changed" when the run was not performed by this tool?
- Where does the source set stop being the configured deck, and what breaks
  when a child's deck has no source?
- What does the report show for a run that left a large fraction alone — a
  count, a reason histogram, or both?

---

This file is a plan and a vision, not committed scope; the source-first
pipeline enters through `IMPLEMENTATION_PLAN.md` (Backlog B6, B7).
