# Mining Fixer — Quality Rules (Invariants)

Answers: *what properties must remain true?*
`TEST_STRATEGY.md` answers how each one is mechanically verified.
An invariant may not be relaxed inside a coding session; change this file
first, with the reason.

## Data safety

- **Q-D1 — Fills only touch fields that render as nothing.** A field with
  visible content is never written by a `fill`; markup-only values like
  `<hr>` count as occupied. One exception, guarded by a pure predicate
  (Q-D13): a *definition* field holding only empty container markup — the
  Yomitan `<ol></ol>` shell — is treated as empty, so the fill replaces the
  shell in one run.
- **Q-D2 — Eight approved non-empty writes, each information-preserving.**
  `replace_source` (blob URL is logged), `expand_sentence` (fragment survives
  in `cloze-*`), `bold_cloze_word` (rendered text unchanged),
  `repair_sentence` (only configured noise classes change, Q-D10),
  `regenerate_furigana` (the ruby layer must still carry the sentence's
  characters, Q-D11), `repair_expression` (the new spelling is the note's own
  furigana base, cross-checked against its reading field, Q-D12; the old
  spelling survives in the run log, Q-D7), `strip_empty_glossary` (only a
  definition that renders as nothing, Q-D13), `add_tags` (superset only).
  `OPS_TOUCHING_NONEMPTY` is the single source of
  truth and a test asserts no other op writes a non-empty value.
- **Q-D3 — Bold is markup-only, word-like and unique.** A bold write is
  emitted only when `strip_renderable(new) == strip_renderable(old)`;
  verified per write. The word is found in three tiers, each requiring
  exactly one occurrence: the `cloze-body` (the mined word), the
  `Expression` verbatim, or a reading-derived mixed-kana surface form
  (鬱病 → うつ病). Expression-derived tiers require the Expression to be
  *word-like* — no whitespace, no sentence punctuation, at most
  `MAX_EXPRESSION_CHARS` (10) characters; a clause-like value
  (漢字は読めるようになりたいかな) is reported
  (`expression-not-word-like`), never bolded, and MeCab tokenization is
  the recorded future oracle (BULK_FIX.md dimension 6). Cards whose
  template front is audio-only are skipped entirely — the sentence is not
  displayed: either a `listening` tag with usable audio, or no
  `Definition`/`Extended definition`/`Frequency` with `Sentence Audio`
  present (`plan._is_listening`, verified against the template). Ambiguity
  — several occurrences or several candidates — is never resolved by
  guessing.
- **Q-D4 — Sentence and Sentence (furigana) are atomic.** Both come from the
  same parent; a furigana fill paired with a guarded expansion ships
  unchecked (`stale-fragment-furigana-risk`). This *text unit* is also the
  batch's atomic unit: a batch either rewrites the sentence together with its
  ruby or leaves both alone. Audio, picture, translation and source do not
  depend on the sentence text, so they remain independent fills even when the
  sentence rewrite is not enabled.
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
- **Q-D10 — Sentence repair touches only configured noise.** The
  `repair_sentence` op rewrites a note's own `Sentence` and nothing else,
  and only through the rules configured in `sentence_repair_rules`. The
  shipped rule set is exactly `strip-arrows` (continuation arrows at line
  tails; mid-line glyphs such as `f:X→Y` are real notation and stay).
  `<br>` line breaks and spacing are deliberately NOT rewritten — they are
  the sentence's pause structure (owner decision 2026-11-15; the recorded
  future direction is deriving breaks from the audio, BULK_FIX.md). Unknown
  rule names are warned about and ignored. A repair write is never issued
  when another `Sentence` write (expansion or bold) is queued for the same
  note, and it is dropped when it would change how often the tested word
  (`cloze-body`) occurs. The transformation is idempotent. By owner
  decision (2026-11-16) the dimension runs by default: the tool fixes on
  its own (`batch_repair_sentence: true`, rules `strip-arrows`); the
  config key remains the escape hatch to switch it off, and every guard
  above still applies.
- **Q-D11 — Furigana regeneration uses Japanese Support as the only
  oracle.** The `regenerate_furigana` op rewrites `Sentence (furigana)`
  from the note's own Sentence through the installed Japanese Support
  add-on's reading engine; the planner never generates ruby itself and the
  add-on's public entry (which refuses non-empty destinations) is bypassed
  only to reach its MeCab/Kakasi reading, which is the same engine that
  entry uses. Guards: the generator input is the Sentence the plan will
  leave behind (a queued repair/expansion/bold write feeds its new value —
  repair precedes furigana, BULK_FIX.md); no other `Sentence (furigana)`
  write may be queued for the note (a scene fill owns the field first); an
  empty engine result or a raised engine error becomes a reported
  `furigana-generation-failed` reason, never a write; and the generated
  ruby's base text must carry exactly the sentence's characters
  (`normalize.furigana_base_matches`), else `furigana-base-mismatch` and no
  write. Unreachable engine (headless, add-on missing) is reported once per
  run. By owner decision (2026-11-16) it runs by default
  (`batch_regenerate_furigana: true`); the config key remains the escape
  hatch, and every guard above still applies.
- **Q-D12 — Expression repair is self-oracled and opt-in.** The
  `repair_expression` op rewrites a note's own `Expression` to the base text
  of its own `furigana` field: Yomitan records the dictionary form the lookup
  resolved to (ひと握り mined under furigana `一握[ひとにぎ]り` → 一握り).
  No dictionary seam and no hand-written kana→kanji table — the note itself
  is the oracle. Guards, each a reported reason instead of a guess:
  `reading_from_furigana(furigana)` must equal the note's normalized
  `reading` field (the furigana must describe *this* word); the base must
  differ from the Expression, contain kanji (a pure-kana rewrite would be a
  different word, never a spelling) and be word-like (the Q-D3 gate). The
  write is deferred when a word-level write is queued for the note — those
  values come from the old spelling's word group and must not land in the
  same run as the rewrite (F2 risk 4). By owner decision (2026-11-16,
  "I want things to be easy") it runs by default like every other
  dimension — automatic mode, no options to tick;
  `batch_repair_expression` remains the escape hatch to switch it off,
  and every rewrite is previewed old → new and undone from the run log
  like every other write.

- **Q-D13 — A definition that renders as nothing may be rewritten.** The
  `strip_empty_glossary` op clears a definition field only when it holds
  nothing but empty container markup (the Yomitan `<ol></ol>` shell) — the
  rendered text is empty before and after, so nothing is lost. Any media
  (`[sound:...]`, `<img>`, `[anki:...]`) or any visible character means no
  write: a real definition is never touched
  (`normalize.is_empty_glossary_shell`, pure).

  A definition field in that state is also **fillable in the same run**: the
  word-fill writes *through* the shell (`old_value` = the shell,
  `filled-through-empty-shell` badge), so one run fixes the card — the shell
  is gone and the real definition is in — and a second run is a no-op
  (owner requirement, 2026-11-16: "it should run on a card once, fix it").
  `strip_empty_glossary` remains the fallback for a shell with no sibling
  value to fill it with, and leaves the field empty for a later fill.

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
- **Q-C6 — The Browser selection is the target set, never the source set.**
  Only selected notes are written; every note of the configured deck remains
  eligible as a parent/word source. Duplicates are dropped, the user's order
  is preserved, foreign note types and ids that no longer resolve are
  reported rather than silently dropped.
- **Q-C7 — A scene source is only trusted when it is unambiguous and close.**
  If several parents would write *different* payloads, no parent is auto-chosen:
  the rows ship unchecked with a `divergent-parents` badge and a warning. A
  containment match further away than `scene_auto_gap_hours` (default 6) from
  the child ships unchecked with `far-from-source`; a byte-identical sentence
  is self-verifying and is trusted regardless of distance. Batch runs send
  every such note to review instead of writing it. Wrong-source data would be
  wrong in a way no later check could detect, so it is never guessed.
- **Q-C8 — Nothing is written without explicit acceptance.** Rows are
  `default_checked` only when every guard passed; the user still has to press
  Apply.
- **Q-C9 — Batch runs ask for no decisions.** A bulk run resolves its own
  guard policy and writes only what is provably safe:
  - **Source confidence** (`divergent-parents`, `far-from-source`) — if the
    source is not trustworthy, nothing from it is written: the rows it
    proposed are dropped (the note is *left alone* with the reason when they
    were its only rows). Because the guard is about the *source*, it does
    not freeze the card's own work — a card whose scene siblings disagree
    still gets its bold, its arrows stripped and its furigana rebuilt
    (owner-visible decision, 2026-11-16).
  - **Text safety** (`fragment-not-recoverable`, `cloze-anchor-not-unique`,
    `stale-fragment-furigana-risk`, `paired-with-expansion`) — exactly the
    text unit is dropped; the note's independent scene fields (audio,
    picture, translation) are still filled.
  - A note with nothing safe to write is reported as *left alone* with a
    reason, never as a question. The preview report lists them all.
  - **The batch default includes both information-preserving replaces**
    (sentence completion and blob-source replacement) so the tool completes
    cards instead of merely filling blanks; `batch_expand_sentence` and
    `batch_replace_source` turn each off. Both keep their information: the
    mined fragment survives in `cloze-*`, the blob URL is written to the run
    log before the write. The subtitle-noise repair is an additional opt-in
    tier (`batch_repair_sentence`, default false); rows of a disabled tier
    make the note count as excluded by policy. The Expression repair
    likewise runs by default (owner decision 2026-11-16;
    `batch_repair_expression` is the escape hatch, Q-D12).

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
- **Q-A5 — Writes happen only when the host is quiescent.** The accepted rows
  are written *after* the preview dialog has closed (never inside its nested
  event loop) and, when a Browser is open, only after that Browser's editor
  has saved pending edits (`applier.run_after_editor_saved`). A lost editor
  callback is covered by an idempotent safety net, so an apply is never
  silently dropped and never written twice. This is what keeps a pending
  editor save from landing on top of the run — and away from Anki's own
  legacy-editor teardown race.
- **Q-A6 — A bulk run is recoverable before it starts.** Every batch takes an
  Anki backup first and **aborts without writing if the backup fails**; it
  writes its undo log **before the first write**, applies in chunks, and then
  re-reads every written field and tag set to verify the values landed
  (`collection_io.apply_batch`, `applier.verify_writes`). A run that crashes
  mid-way is therefore still exactly reversible, and a partial write is
  reported rather than silently accepted.
- **Q-A7 — The configured fields must exist on the note type.** Field names
  are checked against the live note type before any write
  (`collection_io.preflight_fields`); drift aborts the run instead of raising
  halfway through. Notes deleted mid-run are skipped and reported by
  verification, never allowed to abort the rest.
- **Q-A8 — Tags compare case-insensitively**, exactly like Anki's own tag
  matching, so a case difference can neither duplicate a tag nor produce a
  false verification problem.

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
