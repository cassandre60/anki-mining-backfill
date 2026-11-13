# Mining Backfill — Quality Rules (Invariants)

Answers: *what properties must remain true?*
`TEST_STRATEGY.md` answers how each one is mechanically verified.
An invariant may not be relaxed inside a coding session; change this file
first, with the reason.

## Data safety

- **Q-D1 — Fills only touch empty fields.** A field with any non-whitespace
  content is never written by a `fill`; markup-only values like `<hr>` count
  as occupied.
- **Q-D2 — Four approved non-empty writes, each information-preserving.**
  `replace_source` (blob URL is logged), `expand_sentence` (fragment survives
  in `cloze-*`), `bold_cloze_word` (rendered text unchanged),
  `add_tags` (superset only). `OPS_TOUCHING_NONEMPTY` is the single source of
  truth and a test asserts no other op writes a non-empty value.
- **Q-D3 — Bold is markup-only.** A bold write is emitted only when
  `strip_renderable(new) == strip_renderable(old)`; verified per write.
- **Q-D4 — Sentence and Sentence (furigana) are atomic.** Both come from the
  same parent; a furigana fill paired with a guarded expansion ships
  unchecked (`stale-fragment-furigana-risk`).
- **Q-D5 — Tags only grow.** The tag write is a union with the live tag set:
  `new ⊇ live ⊇ old`. Reserved tags never propagate: `marked`, `leech`,
  `optout_tag` (`no-autofill`), `applied_tag` (`auto-filled`).
- **Q-D6 — No bookkeeping tags.** Audit/working state lives in deck/row
  structure and run logs, not in tag names the user did not ask for.
- **Q-D7 — Every write carries its old value in a run log.** Undo depends on
  it; the audit builder emits the same for dry runs.
- **Q-D8 — Junk is never a source.** Doubled-reading pitch-accent artefacts,
  attribution-only definitions, `<hr>`-only fields and placeholder values are
  excluded; the singleton-kanji guard refuses `尾ける`-style sense fills.
- **Q-D9 — Media is verified on disk** before a media fill is offered; a
  missing file drops the row with a warning instead of writing a dead
  reference.

## Correctness of decisions

- **Q-C1 — Never guess.** Ambiguity becomes a visible `reason` or `warning`:
  `no-parent-that-fills`, `cloze-word-ambiguous`, `cloze-word-not-in-sentence`,
  divergent parents. No tie is resolved by choosing one of several plausible
  values.
- **Q-C2 — Scope is a hard cap.** Scene parents are searched only inside the
  temporal window (default ±3 days, `MAX_WINDOW_MS` ceiling). A miss is
  reported; the window is never widened silently.
- **Q-C3 — Determinism.** The same records and config produce the same writes,
  in the same order (`(note_id, field, op)`); `PLAN_VERSION` is bumped when
  plan meaning changes.
- **Q-C4 — The preview is the truth.** What the dialog shows is exactly what
  the applier writes: `build_plan` output is the only input to both.
- **Q-C5 — Opt-out is respected.** A note tagged `optout_tag` is never a
  target; it may still be a *source*, and is badged when used.
- **Q-C6 — Nothing is written without explicit acceptance.** Rows are
  `default_checked` only when every guard passed; the user still has to press
  Apply.

## Apply behaviour

- **Q-A1 — Per-note atomicity.** If any accepted row of a note is stale at
  apply time, *no* row of that note is written; the note is reported as
  `changed since preview`.
- **Q-A2 — Re-running is a no-op.** Rows already at their target value are
  reported as `already applied`, never rewritten.
- **Q-A3 — Undo is exact and conservative.** It restores only fields still
  holding the applied value, removes only the tags the run added, and reports
  `changed since the run` instead of clobbering a later edit. Undo is itself
  idempotent.
- **Q-A4 — One collection update per note**, so Anki's own undo entry stays
  meaningful.

## System

- **Q-S1 — The pure core never imports `anki`, `aqt` or PyQt** (AST-enforced).
  This is what makes the headless builder, the suite and CI possible.
- **Q-S2 — The add-on survives import.** Anything in `__init__.py` that
  raises is what users see as "add-on failed to load": the `aqt` import is
  optional, handlers import lazily, and failures print instead of throwing.
- **Q-S3 — Fully offline.** No network access, ever.
- **Q-S4 — Development tooling never writes to a live profile.** Copies and
  scratch bases only; the only writer of a real collection is the add-on,
  after Apply.
- **Q-S5 — Deterministic audit identities.** Audit notes use
  `uuid5(mb-audit:<note id>)`, so re-importing a rebuilt package updates in
  place instead of duplicating.
- **Q-S6 — No secrets** in code, config, fixtures or logs.

## Acceptance

- **Q-T1 — The golden fixture stays byte-exact.** `tests/test_golden_scene.py`
  reproduces the author's manual 診察 fix on all five fields, plus the tag
  union (`asbplayer yomitan`).
- **Q-T2 — Gates are clean.** `ruff check`, `ruff format --check` and the
  suite pass locally and on CI for the released commit.
- **Q-T3 — A new test must be able to fail.** Tests for bug fixes are verified
  to fail against the unfixed code (or the observation that made the bug
  visible is recorded in the test).
