# Mining Fixer — Implementation Plan

Status: **shipped as v0.2.0** — the add-on installs, previews, applies and
undoes; the audit builder works headless. New work enters through the Backlog
below, never as silent scope creep inside a coding session.

## Shipped slices

- **T1 — Pure matching core + golden fixture.** `normalize`, `fieldconfig`,
  `matching`, `plan`, `report` with no Anki import; scene containment matching
  inside a hard time window with parent ranking and agreement collapsing; word
  groups by `(Expression, reading, furigana)` with provenance and junk
  filters; fills-only invariant; the two original approved replaces; the
  byte-exact golden acceptance test reproducing the author's manual 診察 fix.
- **T2 — Headless audit package builder.** `scripts/build_audit_package.py`
  clones the note type with fresh ids into a separate deck, assigns
  deterministic `uuid5` GUIDs, exports `.apkg` + Markdown report + JSON plan
  log, and purges any previous audit import from its work copy so a rebuild
  cannot ship stale notes.
- **T3 — Bold repair + tag union (`PLAN_VERSION` 2).** `bold_cloze_word`
  (tier 1: cloze body verbatim ×1; tier 2: reading-derived mixed-kana surface
  form ×1; ambiguity → warning) and `add_tags` (union of the target's and its
  contributing sources' tags, reserved tags excluded, never removes).
  Fixed the `<br>`-matches-`<b` defect that had silently disabled every
  repair.
- **T4 — Audit hygiene.** Audit notes carry the same tags as the cards they
  take values from (診察 = `asbplayer yomitan`), no bookkeeping tags at all;
  stable GUIDs make re-imports update in place; `--note-id` pins cards the
  moving "last N" window would drop.
- **T5 — Installable add-on.** Package layout (`mining_fixer/`), entry
  point with two Tools actions, `applier.py` (per-note atomicity, idempotence,
  exact undo), `collection_io.py` (collection adapter + run logs),
  `preview_dialog.py` (per-row checkboxes, not-fixable and warning tabs),
  config defaults shipped as Anki's config, dev install documented.
- **T6 — CI and docs.** `tests` workflow (ruff + suite, no Anki needed),
  actions pinned to current majors, and this documentation set.
- **T7 — Browser integration.** Right-click a selection in the Browse window →
  *preview and apply on selection*: the selection is the target set, the whole
  configured deck stays available as sources, foreign note types and stale ids
  are reported rather than dropped, and duplicates/order are handled in the
  pure `plan.scope_from_selection`. Verified end to end on a copy of the real
  collection (10 selected targets, 16 writes, exact undo; a solo child still
  sourced its parent outside the selection).
- **T9 — Source confidence (wrong-source protection).** A scene source is
  trusted only when it is unambiguous and close: divergent parent payloads
  ship unchecked (`divergent-parents`), containment matches beyond
  `scene_auto_gap_hours` ship unchecked (`far-from-source`), and a
  byte-identical sentence stays trusted regardless of distance. Batch sends
  every such note to review. On a 1,000-note selection this demoted 18 notes
  (48 rows) that would otherwise have been written from an arbitrarily chosen
  parent.
- **T10 — Bulk runs are the default experience.** A batch run ships with
  both information-preserving replaces enabled (`batch.py` defaults), the
  window shows counts and a preview report instead of a decision queue, and
  the dialog states exactly what it will do before the run.
- **T11 — Subtitle-noise repair (bulk-fix dimension 2, B7 slice 1).**
  `normalize.repair_sentence` (`strip-arrows` at line tails only — the
  owner decision of 2026-11-15 keeps `<br>` line breaks and spacing as
  mined; the audio-aligned-breaks direction is recorded in BULK_FIX.md)
  behind the opt-in `repair_sentence` op (`PLAN_VERSION` 3): skipped when
  expansion or bold already owns the `Sentence`, dropped when it would
  change the tested word's occurrence count, idempotent, off by default
  (`sentence_repair_rules: []`, `batch_repair_sentence: false`). Pinned
  against real deck values; the Ring 3 old → new diff on a collection copy
  is still pending.
- **T12 — Furigana regeneration (bulk-fix dimension 3, B7 slice 2).**
  `regenerate_furigana` (`PLAN_VERSION` 4) rebuilds `Sentence (furigana)`
  from the note's own post-write Sentence through the installed Japanese
  Support add-on's MeCab/Kakasi reading (`reading.mecab.reading` — the
  same engine its `regenerateReading` uses, which itself refuses non-empty
  destinations; entry points re-verified 2026-11-15). Bridge:
  `collection_io.japanese_support_furigana_generator` (lazy, `None`
  headless). Guards (Q-D11): generated from the sentence the plan leaves
  behind (repair precedes furigana, one plan), defers to a queued scene
  fill of the field, `furigana-generation-failed` on an empty result or a
  raised engine error, `furigana-base-mismatch` when the ruby's base text
  no longer carries the sentence (pure
  `normalize.furigana_base_matches`), one unavailable-engine warning per
  run, off by default (`batch_regenerate_furigana: false`). Ring 3
  battery pending (curated per-class cards, TEST_STRATEGY.md).
- **T8 — Batch mode for hundreds/thousands of notes.** A counts-only dialog
  with a lossless-by-default policy (`batch.py`), opt-in Sentence/Source
  tiers, note- and group-atomic selection, and a review shortlist instead of
  a thousand checkboxes. The run itself: Anki backup first (abort on failure),
  undo log written before the first write, chunked apply, post-write
  verification, and a dry-run report. Hardening shipped with it: distinct
  note rows (a note with several cards appeared twice), case-insensitive tag
  handling, unique undo-log names, field preflight, per-note write failures
  reported instead of aborting, and a log-first single-run path. Verified on
  1000 real notes: 2.2 s plan, 1.5 s apply, verification clean, 793 untouched
  notes byte-identical, re-run a no-op, undo exact.

## Slice map

| Slice | Verified by |
|---|---|
| T1 | Ring 1 golden fixture; `test_matching.py`, `test_plan.py` |
| T2 | Round-trip import of the built `.apkg` (Ring 3) |
| T3 | `test_bold_repair_*`, `test_add_tags_*`; 鬱病 verified end to end |
| T4 | `test_golden_scene.py` tag assertion; apkg tag census |
| T5 | `tests/test_applier.py`, `test_addon_load.py`, Ring 3 apply + undo |
| T6 | Green CI on every push |
| T7 | `test_scope_from_selection_*`, `test_browser_context_menu_*`; Ring 3 selection run |
| T8 | `test_batch.py`, `test_invariants.py` (Hypothesis); Ring 3 1000-note run |
| T9 | `test_divergent_scene_sources_*`, `test_a_far_scene_source_*`, `test_an_identical_sentence_*`; Ring 3 demotion count |
| T10 | `test_batch.py` (defaults), `tests/test_report_summary.py` (readable preview); Ring 3 run |
| T11 | `test_normalize.py` (repair rules), `test_plan.py` (guards, exclusivity), `test_batch.py` (tier), `test_report_summary.py`; Ring 3 diff pending |
| T12 | `test_normalize.py` (base-text guard), `test_plan.py` (guards, ordering, exclusivity, engine failures), `test_batch.py` (tier), `test_report_summary.py`; Ring 3 battery pending |
| T13 | `test_batch.py` (flags, overlay keys, no-op tick), `test_plan.py` (scene-off gate); Ring 3 battery pending |
| T14 | `test_plan.py` (expression tier, word-like gate, listening predicate incl. the Frequency exception); Ring 3 battery pending |

- **T13 — Dimension picker in the batch window (B7).** Three checkboxes
  (scene propagation / line-end arrows / furigana regeneration) initialised
  from the config keys, each mapping onto documented `batch_*` keys via
  `batch.dimension_flags` / `batch.cfg_for_dimensions`; toggling rebuilds
  the preview and the counts. Ticking arrows with an empty rule list
  selects the shipped `strip-arrows` set; unticking keeps the configured
  rules for later runs. Turning scene propagation off removes scene-origin
  rows at plan time (`build_plan` honours `batch_scene_propagation`), so
  no fill can slip through selection; the lossless core (word fills, bold
  repair, tag unions) is not a dimension and always stays eligible. The
  picker can enable only documented, guarded writes. Ring 3 battery
  pending.
- **T14 — Bold from expression (B8 slice 1).** `plan._bold_repair_for`
  gained a verbatim-Expression tier (`bold-added-to-expression` badge)
  for cards whose `cloze-body` is missing or junk, the word-like gate
  (`plan._expression_is_word_like`: no whitespace/punctuation, at most 10
  characters — clause-like Expressions reported as
  `expression-not-word-like`, never bolded; over-long words skipped
  conservatively) applied to both expression-derived tiers, and the
  template's listening predicate (`plan._is_listening`: tag + usable
  audio, or no Definition/Extended definition/Frequency with Sentence
  Audio — Frequency-without-glosses stays repaired). Inflected matching
  stays open (BULK_FIX slice 8; 278 census cards). Ring 3 battery
  pending.

## Backlog

- **B7 — Bulk fix by dimensions** (the product direction; design in
  [`BULK_FIX.md`](BULK_FIX.md)): one window, select any number of cards, pick
  the dimensions to fix (source–child propagation, sentence repair, furigana
  generation after the sentence is repaired, later expression repair and
  formatting), press apply. Includes multi-deck selection and, later, other
  note types and languages behind a language/note-type profile. Slice 1 (the
  sentence-repair dimension) shipped as T11, slice 2 (furigana regeneration)
  as T12 (both off by default) and the single-window dimension picker as
  T13; the repair→propagate DAG sequencing is still open.
- **B6 — Source-first pipeline** (author's idea, text in
  [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md)): normalise a source card before
  its children — strip continuation arrows (line breaks stay as mined; see
  BULK_FIX.md), regenerate its furigana through the installed Japanese
  Support add-on, and only then plan the children. Requires
  a new opt-in policy tier (it rewrites a non-empty source field) and a
  "source changed since this card was filled" check for already-filled
  children.
- **B8 — Bold from expression** (owner ask 2026-11-16; design in
  [`BULK_FIX.md`](BULK_FIX.md) dimension 6 / slice 8). **Shipped portion
  (T14):** the bold repair gained a verbatim-Expression tier (前人未到
  shaped cards), the word-like gate that refuses clause-like Expressions
  (漢字は読めるようになりたいかな) for every expression-derived tier, and
  the template's own listening predicate (tag + usable audio, or no
  glosses/no Frequency with `Sentence Audio`). Still open: inflected
  matching (278 census cards, e.g. 読む → 読め) and the MeCab
  token-count oracle for word-vs-clause.
- **B9 — Dictionary spelling for kana expressions** (owner ask 2026-11-16;
  text in [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) §F2, design in
  [`BULK_FIX.md`](BULK_FIX.md) dimension 4 / slice 4). Rewrite a kana-only
  `Expression` to its kanji spelling (いきなり → 行き成り, ときに → 時に)
  using an offline dictionary — never a hand-written table. This is a new
  non-empty write on `Expression` (QUALITY Q-D2 needs a seventh approved
  write first), so it ships opt-in with a preview diff, its own badge and
  the run log. Exactly one dictionary form, or the card is reported and left
  alone; the T14 word-like gate applies (ときに is 時 + に). The same lookup
  also supplies bold-match candidates in the other spelling direction.
  Blocked on: dictionary source decision, QUALITY amendment, Ring 3 sample
  review. Not started.
- **B10 — Bold when the sentence spells the word differently** (owner ask
  2026-11-16, deferred the same day: "No, leave them"; text in
  [`FUTURE_FEATURES.md`](FUTURE_FEATURES.md) §F3, design in
  [`BULK_FIX.md`](BULK_FIX.md) dimension 6 / slice 8). The easy half is
  shipped (T14); the changed-form half (word 読む, sentence 読め) stays
  unfixed. The okurigana-stem rule was rejected on evidence (2026-11-16
  read-only sample: 82 of 272 matched, many over-long bolds because kana
  runs cross word boundaries). The honest path is MeCab segmentation
  through Japanese Support — the same engine T12 calls — with an
  exactly-one-token requirement and the T14 guards unchanged. Blocked on
  nothing technical beyond that engine pass; the owner chose to wait. Not
  started.
- **B2 — Rendered card preview.** Render each row's real front/back HTML
  (Anki's card rendering API) in a side pane, so a reviewer sees the card as
  the template shows it rather than as field values.
- **B3 — AnkiWeb release.** Package script (zip with `manifest.json` +
  `__init__.py` at the root, dev artefacts excluded), numeric package id so
  AnkiWeb can deliver updates, release workflow, and a changelog.
- **B4 — Multi-note-type configuration.** Today one deck + note type and one
  field-name set; a per-note-type field mapping would let the same install
  serve a second mining setup.
- **B5 — Review ergonomics for guards.** Surface *why* a row is unchecked in
  the row itself (the badges already carry it; a short tooltip would make it
  legible without opening the tabs).

## Working agreements (from experience)

- One user request = one workstream: finish, verify on a copy, commit, push,
  watch CI.
- Docs change with behaviour in the same commit (see `AGENTS.md` §6).
- Real-collection verification happens on a copy, never on the live profile.
- Root-level scratch files (`*.backup`, `debug_*.py`, probe collections) must
  never be committed — `dist/`, `meta.json`, `__pycache__/` are gitignored for
  the same reason.
- Numbers in docs (test counts, default config values, field names) are facts:
  re-verify or delete them.
