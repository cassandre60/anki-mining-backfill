# Mining Backfill

An Anki add-on that completes incompletely-mined Japanese cards by copying
from their enriched siblings — the already-finished card of the same scene,
or a sibling card of the same word. Built for asbplayer + Yomitan mining
workflows where enrichment is interrupted: the card stays without scene
audio, picture, timestamped source, or the full scene sentence, and fixing
each one by hand costs minutes per card.

**Status: working add-on, preview-first.** The matching core, the in-Anki
preview/apply dialog (with undo), and the headless audit-package builder are
complete and tested. Vocabulary-specific heuristics are tuned for the
author's deck; matching is conservative by design — it reports what it
cannot fix rather than guessing. See [Roadmap](#roadmap).

## Safety guarantees

These are the rules the core is built around — each one is enforced in code
and covered by tests, not just intended:

1. **Fills only touch empty fields.** A field with any non-whitespace
   content is never written. Markup-only values like `<hr>` count as
   occupied and are never overwritten.
2. **Only four approved non-empty writes, each information-preserving.**
   - `Source`: the asbplayer blob URL is replaced with the timestamped
     source — the blob URL is recorded in the run log, so nothing is lost.
   - `Sentence`: the mined fragment is replaced with the full scene text —
     only offered when the fragment is provably recoverable from
     `cloze-prefix + cloze-body + cloze-suffix`, and the cloze anchor (the
     tested word) occurs exactly once in the new text. The scene's bold
     markup is moved to your card's word, never left on the sibling's.
   - Bold markup repair (`bold_cloze_word`): when a card's `Sentence` has
     no bold term at all (its cloze-* hold dictionary-entry text instead
     of the subtitle span), the tested word is wrapped in `<b>` — but only
     when it occurs exactly once, either verbatim or as a reading-derived
     surface form (鬱病 + うつびょう → うつ病). Markup-only: the rendered
     text is identical, verified per write. Two occurrences = never
     guessed, reported as a warning instead.
   - Tags (`add_tags`): the target keeps its tags and gains every
     contributing source card's tags — a pure union that never removes;
     Anki control tags (`marked`, `leech`) and this tool's own tags
     (`no-autofill`, `auto-filled`) never propagate.
3. **`Sentence` and `Sentence (furigana)` are atomic.** Both always come
   from the same parent — never mixed ruby from a second note, never stale
   fragment ruby left under a full scene. If the parent has no furigana and
   the child does, the expansion ships unchecked (`stale-fragment-furigana-risk`).
4. **Risky rows ship unchecked, not hidden.** Guards like
   `fragment-not-recoverable`, `cloze-anchor-not-unique`, or a furigana fill
   paired with a guarded expansion set `default_checked=False` and carry a
   visible badge. Silence never hides a risky write.
5. **Media is checked on disk first.** A fill referencing a media file that
   no longer exists is dropped with a warning instead of producing a dead
   reference.
6. **`no-autofill` opts a note out as a target.** Hand-edited notes remain
   eligible as sources (they are good sources) and are badged when used.
7. **Every run is reversible.** Every write carries its old value in a JSON
   run log; the future apply step restores field-by-field only where the
   card is untouched since.
8. **Junk is never a source.** Doubled-reading pitch-accent artifacts,
   attribution-only definitions, `<hr>`-only fields, and placeholder values
   are excluded from fills.
9. **Fully offline.** Nothing syncs, nothing contacts the network.

## How matching works

**Scene completion** — an unenriched card's normalized `Sentence` is
matched by containment into enriched cards' `Sentence`, searched only
within a temporal window around the note id (note ids are millisecond
creation timestamps; default ±3 days, hard cap, never widened silently).
Candidates are ranked: exact-equal sentence first, then tightest containing
parent, then smallest id gap. When several parents would write identical
values they collapse into one agreement group (`N-siblings-agree`); genuine
divergence needs manual review.

**Word backfill** — notes are grouped by `(Expression, reading)`. There is
deliberately no reading-only matching: 氏/詩/師/死 all read し. Sense fields
(`Definition`, `Extended definition`) are default-checked only with Yomitan
gloss provenance or 2+ sibling agreement; a singleton kanji expression
whose reading has a 2+ kana twin (`尾ける`-style Yomitan attribution
artifacts) is refused sense fills entirely.

## Installing it in Anki

The add-on is the `mining_backfill/` package. Anki discovers any folder in
`addons21/` that contains `__init__.py`, so a symlink gives a live dev
install (edits take effect on the next Anki restart):

```
ln -s "$PWD/mining_backfill" "$HOME/.local/share/Anki2/addons21/mining_backfill"
```

That folder also needs a `meta.json` (Anki writes one when a package is
installed; for a manual install, copy any installed add-on's and set
`name`, `human_version`, `package`). Then, after restarting Anki:

- **Tools → "Mining Backfill: preview and apply…"** — plans the newest
  `preview_last_n` notes of the configured deck (default 30).
- **In the Browser: select notes → right-click → "Mining Backfill: preview
  and apply on selection"** — plans exactly the selected notes. Every note of
  the configured deck still serves as a *source*, so a selection of ten cards
  finds its scene parents and word siblings even when those are not selected.
  Selected notes of another note type are reported and skipped; selections are
  deduplicated and keep their order.

Either entry opens the same dialog: every proposed write is one row (note,
field, the exact old → new value, its source note, its badges). Rows the plan
guarded arrive **unchecked**; the rest are checked. Nothing is written until
you press Apply.

- **Tools → "Mining Backfill: undo last run"** — restores exactly what the
  last apply replaced and removes exactly the tags it added.

- **In the Browser: select notes → right-click → "Mining Backfill: batch-fix
  selection…"** — the bulk mode, for hundreds or thousands of notes. It shows
  **counts, not rows**: how many notes will be fixed and with what, how many
  are already complete and will not be touched, and which few need a human.
  Default is lossless: empty-field fills, bold markup, tag additions. Two
  opt-in tiers add the information-preserving replaces ("also expand
  Sentence", "also replace blob Source") with a live count of how many extra
  notes each would fix. Every batch run takes an **Anki backup** first,
  writes its **undo log before the first write**, applies in chunks, and then
  **re-reads every written value to verify it landed**. "Write dry-run report"
  produces the full Markdown report without touching the collection.

Apply is safe by construction:

- **Per-note atomicity.** Every checked row of a note is re-asserted against
  the collection first; if the card changed since the preview, *no* row of
  that note is written. A half-applied card is worse than an untouched one.
- **Re-running is a no-op.** Rows that already hold their target value are
  recognised as done, not re-written.
- **Undo log.** Each apply writes `run-<timestamp>.json` under
  `<profile>/mining_backfill/undo/` — old values, applied values, and the
  tags involved. Undo restores only notes whose values are still exactly
  what the run wrote; anything edited since is reported and left alone.
- **The tag op only adds**, so tags gained since the preview survive.
- **A scene source is only trusted when it is unambiguous and close.** If two
  cards would give the same child different values, neither is chosen: the
  rows arrive unchecked with `divergent-parents`. A match further than
  `scene_auto_gap_hours` (default 6 h) from the child arrives unchecked with
  `far-from-source`, unless the sentences are byte-identical (self-verifying).
  In a 1,000-note selection this moved 18 notes from "will fix" to "review" —
  exactly the wrong-source cases the batch dialog exists to keep out of an
  automatic run.
- **Nothing is written inside the dialog's event loop.** Apply closes the
  dialog, then writes once the Browser's editor has saved any pending edits —
  so an in-flight editor save cannot overwrite the run, and the write does not
  interleave with Anki's window teardown.

## The audit package

For reviewing a whole run before it touches your collection, the headless
builder still exports a standalone `.apkg`:

```
python3 scripts/build_audit_package.py --profile-dir ~/.local/share/Anki2/User\ 1 --last 20
```

- Imports into deck `zzz-Mining-Backfill-Audit`. Notes carry their target
  card's tags plus the tags of the cards they take values from — a union,
  nothing removed, no audit-bookkeeping tags; the deck is the container.
- Uses a cloned note type (`... (MB Audit)`) with fresh ids, so the import
  can never merge into your live note type or modify an existing note.
- Deterministic GUIDs (`uuid5` of the original note id) keep re-imports of
  rebuilt packages idempotent — the same notes update in place.
- `--note-id <id>` (repeatable) pins extra cards into the scope, for fixes
  explicitly requested by name — the moving "last N" window would
  otherwise drop them as new cards get mined.
- `dist/mining-backfill-report-<run>.md` — per-card preview: every write,
  its source note, badges, and default check state.
- `dist/mining-backfill-plan-<run>.json` — the audit log: every old and new
  value, per field.

After auditing: delete the audit deck and the cloned note type.

## Documentation

| Document | Answers |
|---|---|
| [`PRODUCT.md`](PRODUCT.md) | what this add-on is for, users, principles, non-goals |
| [`MVP.md`](MVP.md) | what is actually built today, limitations, acceptance criteria |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | module map, pipeline, ops table, apply contract |
| [`CODEBASE_GUIDE.md`](CODEBASE_GUIDE.md) | guided tour: reading order, safety ideas, where to add things |
| [`QUALITY.md`](QUALITY.md) | the invariants that must stay true (Q-*) |
| [`TEST_STRATEGY.md`](TEST_STRATEGY.md) | the test rings and what each one proves |
| [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) | shipped slices and the backlog |
| [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) | the author's ideas, incl. the source-first pipeline (not committed scope) |
| [`AGENTS.md`](AGENTS.md) | operating rules for agents working in this repo |

## Development

```
python3 -m pytest         # 111 tests with Anki; 109 + 2 self-skipping without
ruff check . && ruff format --check .
```

The golden test (`tests/test_golden_scene.py`) reproduces a real manual fix
from the author's collection **byte-for-byte on all five fields** — media,
source, furigana, and the sentence with the bold retargeted to the card's
own word. The core (`mining_backfill/` minus the three Qt-facing modules)
imports no `anki`/`aqt` — enforced by an AST test — so the same code runs
headless, in tests, and inside Anki. `tests/test_addon_load.py` imports the
package the way Anki does, with a stubbed `aqt`, which is what catches a
broken entry point before users see "add-on failed to load".

## Roadmap

- [x] aqt add-on shell: preview dialog, apply with re-assertion, undo log.
- [x] browser integration: run the plan on the selected notes (right-click in
      the Browse window).
- [ ] rendered front/back HTML per row in the preview, instead of field values.
- [ ] source-first pipeline: normalise a source card (arrows, spacing, `<br>`),
      regenerate its furigana, then fix the children — see
      [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md).
- [ ] AnkiWeb release (yields a numeric package id and self-updates).
- [x] CI workflow: `ruff` + the full test suite on every push and pull
  request (`.github/workflows/tests.yml`).

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE).
