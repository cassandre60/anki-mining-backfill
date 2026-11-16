# Mining Fixer — Agent Operating Rules

> **Authority hierarchy (conflicts resolve top-down):**
> `PRODUCT.md` (what to build) → `MVP.md` (what is in scope now) →
> `ARCHITECTURE.md` (technical structure) → `QUALITY.md` (invariants that
> must hold) → `TEST_STRATEGY.md` (how they are verified) →
> `IMPLEMENTATION_PLAN.md` (current work) → this file (how to operate here).
> **Code implements the specs; tests enforce them.** Never widen scope or
> relax an invariant inside a coding session — change the document first.

Read the documents above that your task touches before you write code, and
keep the change consistent with them.

## 1. What this repo is

An Anki add-on that completes incompletely-mined Japanese cards from their
enriched siblings. Two halves:

- `mining_fixer/` — **the add-on**. Anki discovers any `addons21/<folder>/`
  that contains `__init__.py` and imports that folder as a Python package.
- `scripts/`, `tests/` — development tooling. Nothing here ships.

`mining_fixer/` is packaged for AnkiWeb as a zip whose root contains
`manifest.json` and `__init__.py`; `meta.json` in that folder is a
**dev-install artefact and is gitignored** — never commit it.

## 2. Hard rules

1. **Never write to a live Anki profile from development tooling.** Copy the
   collection first (the builder does this via `--profile-dir` → `--work-dir`),
   or point Anki itself at a scratch base (`ANKI_BASE`). The only code allowed
   to modify someone's collection is the add-on itself, after the user pressed
   Apply — and it must leave an undo log.
2. **Never start Anki, Qt or a web engine on the author's machine.** Booting
   Anki — including `QT_QPA_PLATFORM=offscreen` or importing `aqt`/Qt in a
   long-running probe — has crashed the author's session (2026-11-14, after
   several headless Anki/WebEngine attempts). Verify GUI code by import checks
   in the suite and by asking the author to restart Anki; never by launching
   it. `python3 -m pip install` and `ruff`/`pytest` are fine; a GUI process is
   not.
3. **No heavy jobs on the author's machine.** No full-collection copies, no
   whole-deck scans, no background or forked workers, no `--watch`, no growing
   `/tmp` artifacts. Work from one existing snapshot when there is one,
   otherwise a single scoped read-only query (a few thousand notes at most),
   and delete what you create. The fast gates are `ruff check .`,
   `ruff format --check .` and the pytest suite (seconds). Anything bigger is
   a CI job.
4. **The pure core stays pure.** `normalize.py`, `fieldconfig.py`,
   `matching.py`, `plan.py`, `report.py`, `batch.py`, `applier.py` must not
   import `anki`, `aqt` or PyQt — `tests/test_layer_boundary.py` fails if they
   do, and the headless builder plus most of the suite depend on it. Only
   `__init__.py`, `collection_io.py`, `preview_dialog.py` and
   `batch_dialog.py` may touch Anki.
5. **Never guess.** Ambiguity is reported (`plan.reasons`, `plan.warnings`),
   never resolved by picking one of several plausible values.
6. **Fills only; six approved non-empty writes** (`Source`, `Sentence`,
   `bold_cloze_word`, `repair_sentence`, `regenerate_furigana`, `add_tags`)
   — each must preserve
   its information, and each carries badges. See `QUALITY.md`.
7. **Tags are never removed** and bookkeeping tags are never added: the audit
   deck is the container, the note carries only the target's and its sources'
   tags.
8. **Fully offline.** No network calls, no telemetry, no auto-update behaviour
   beyond Anki's own.
9. **No secrets, ever** — not in code, config, fixtures or logs. Fixtures are
   real captures from the author's collection; keep them minimal.
10. **Import-time safety.** Anything in `__init__.py` that raises is what users
    see as "add-on failed to load". Guard it, print instead of throwing.

## 3. Environment (verified on the author's machine)

- Arch Linux; Anki 26.09.4 (`/usr/bin/anki`, PyQt6 6.12); system `python3` is
  what has the `anki` package, so headless tooling runs with plain `python3`.
- `ruff` is in `/usr/bin`; pytest is **not** in system Python (Arch splits
  it) — CI installs it, or use a venv.
- Repo layout: pure core + add-on shell in `mining_fixer/`, tests in
  `tests/` (a `conftest.py` puts the repo root on `sys.path`).

## 4. Gates before you present work

```bash
ruff check . && ruff format --check .     # must be clean
python3 -m pytest                         # 139 tests with Anki installed
```

Then push and watch CI — it is the gate, and it runs without Anki (137 passed,
2 skipped):

```bash
gh run watch --exit-status
```

The suite is hermetic and sub-second, so local runs are cheap and allowed.
Anything that needs a **real collection** is not a suite test: run it as an
ad-hoc script against a *copy* (see `TEST_STRATEGY.md`, Ring 3).

## 5. Commits and attribution

- Conventional Commits (`feat:`, `fix:`, `refactor:`, `chore:`, `docs:`),
  imperative, one coherent change per commit.
- Never `--amend`, `rebase -i` or `--force`; never claim human authorship.
- Trailers on every commit: `Harness: OpenCode` and `Model: <actual model>`.
- Stage touched files by name; check `git status` for unrelated dirty files
  first (dev-install artefacts must never be staged).

## 6. Docs change with behaviour

A behaviour change updates the document that owns it in the same commit:
a new invariant → `QUALITY.md`; a new check → `TEST_STRATEGY.md` and the
invariant row it verifies; a shipped slice → `IMPLEMENTATION_PLAN.md`;
user-facing usage → `README.md`. Numbers quoted in docs (test counts, config
defaults, field names) are facts — re-verify or drop them.

## Project Notes

Durable, verified facts. Append; do not duplicate. Prune when superseded.

- [2026-11-14, OpenCode] Note ids are millisecond epoch creation timestamps and
  are the time axis for scene matching (window in days, hard-capped).
  Verified by: `matching.py` window math and the audit build's `added-gap:*`
  badges.
- [2026-11-14, OpenCode] The mining note type has 20 fields; the deck holds
  ~17k notes of that type, so deck-wide record loads are fine. The Tools menu
  deliberately scopes to the newest `preview_last_n` (default 30); the Browser
  context menu scopes to the selection.
  Verified by: `deck_records` query timings in the integration run.
- [2026-11-14, OpenCode] In this Anki version the Browser selection API is
  `browser.selected_notes()` (snake_case); `selected_notes_as_cards()` /
  legacy `selectedNotesAsCards` return cards, not notes. The context-menu hook
  is `gui_hooks.browser_will_show_context_menu(browser, menu)`.
  Verified by: `aqt/browser/browser.py` and `_aqt/hooks.py`, and the
  context-menu wiring test.
- [2026-11-14, OpenCode] Anki reads an add-on's packaged `config.json` as the
  default config and stores user edits in `meta.json`; `meta.json` is also
  what supplies the displayed name/version. `manifest.json` is for packaging
  and AnkiWeb.
  Verified by: `aqt/addons.py` (`addonConfigDefaults`, `getConfig`,
  `AddonMeta.from_json_meta`).
- [2026-11-14, OpenCode] Bold markup in `Sentence` is load-bearing: the card
  template's cloze fallback rebuilds the front from `cloze-*` exactly when no
  bold term exists. A card whose `cloze-*` hold dictionary text therefore
  renders the dictionary entry on the front until the repair lands.
  Verified by: reading the author's note-type templates and the 鬱病 card.
- [2026-11-14, OpenCode] `cards ⋈ notes` yields one row per *card*, so a note
  with several cards appeared twice in the record list (duplicate plan rows,
  duplicate writes). Record queries use `select distinct n.id, …`.
  Verified by: duplicate probe on 17,631 notes (`count(*) - count(distinct n.id)`
  = 0 after the fix).
- [2026-11-14, OpenCode] Anki tag matching is case-insensitive
  (`Note.has_tag` → `col.tags.in_list`), so tag unions, staleness checks and
  verification compare tags lower-cased while writing the spelling seen first.
  Verified by: `applier._tag_key` / `_merge_tags` unit tests.
- [2026-11-14, OpenCode] CI needs `hypothesis` (the property tests) in addition
  to pytest and ruff; the add-on itself needs neither.
  Verified by: `.github/workflows/tests.yml` install step + green run.
- [2026-11-14, OpenCode] The old scene planner always picked the largest
  agreement group and marked its rows checked, even when several parents would
  write *different* payloads — the wrong-source failure the author fears at
  scale. On a 1,000-note selection the divergence guard demoted 18 notes (48
  rows) from auto-fix to review; the far-from-session guard demoted none in
  that selection (sessions cluster within hours).
  Verified by: Ring 3 run on a copy + `test_divergent_scene_sources_*`.
- [2026-11-14, OpenCode] Japanese Support (installed add-on id 3918629684)
  exposes `bulkreading.regenerateReadings(nids)` and
  `reading.regenerateReading(note, src_field)` — the entry points a
  source-first furigana pipeline would call. Verify again before depending on
  them; the add-on may change.
  Verified by: reading the installed add-on's source.
- [2026-11-15, OpenCode] The add-on/repo rename to Mining Fixer is complete
  (GitHub `cassandre60/anki-mining-fixer`, package `mining_fixer`). Undo logs
  written before the rename stay undoable: `collection_io.LEGACY_UNDO_FOLDER`
  reads `<profile>/mining_backfill/undo/` but never writes there; the two
  existing logs (run-20261114-*) live there.
  Verified by: `tests/test_applier.py` lookup tests + the logs on disk.
- [2026-11-15, OpenCode] A raw read-only SQL census against the live
  collection needs `con.create_collation("unicase", …)`, and the `decks`
  table stores tree names with `\x1f` separators, so `::`-style name
  equality fails — match deck names in Python instead. Do not write;
  open with `file:…?mode=ro`.
  Verified by: the 2026-11-15 census run.
- [2026-11-15, OpenCode] Sentence-noise census (one read-only query, 17,589
  notes of the configured deck): `<br>` in 72.1%, arrows `➡`/`→` in 0.4%,
  padding runs in 0.3% — the repair dimension is a `<br>`-collapse problem.
  Recorded in `BULK_FIX.md` (open questions).
  Verified by: the census script's printed aggregates.
- [2026-11-15, OpenCode] The collection has a second, empty deck-tree path
  `Mansour Mohamed Mehdi Life Decks::Japanese::My New Japanese Deck`;
  `config.json` points at the populated `My Life Decks…` one. No action
  taken — data observation only.
  Verified by: the `decks` table listing (0 vs 17,589 notes).
- [2026-11-15, OpenCode] Owner decision: sentence repair ships
  `strip-arrows` only — `<br>` line breaks and padding stay exactly as
  mined (they are the pause structure), and the replacement direction is
  audio-aligned line breaks recorded in `BULK_FIX.md`.
  Verified by: the rollback commit's diff + `tests/test_normalize.py`.
- [2026-11-16, OpenCode] Japanese Support's public `regenerateReading`
  refuses non-empty destination fields, so it cannot repair stale ruby; the
  shipped furigana dimension (T12) calls its engine directly
  (`reading.mecab.reading`, the same function) through an injected
  generator, keeping `plan.py` pure and the suite independent of a live
  MeCab. Feed it the post-write Sentence (repair first), not the mined one.
  Verified by: reading the installed add-on's `reading.py` and the regen
  tests in `tests/test_plan.py`.
- [2026-11-16, OpenCode] "Listening card" is template behaviour, not a
  template: the mining note type has one template (`Card 1`) whose front
  goes audio-only (sentence views removed) when either path fires —
  (a) a `listening` tag token AND usable audio (`Sentence Audio` or
  `Word Audio`), or (b) no `Definition`, no `Extended definition`, no
  `Frequency`, and `Sentence Audio` present. `Frequency` without glosses is
  deliberately NOT listening (the template shows the normal sentence).
  Verified by: the template's qfmt HTML/JS read from the collection
  (read-only) on 2026-11-16.
- [2026-11-16, OpenCode] No-bold census (mining note type, 17,642 notes,
  one read-only query): 2,136 `Sentence` fields have no `<b>` — 307 empty
  (kanji-only cards), 3 tag-listening + 240 no-gloss listening shape,
  828 fixable by the shipped bold repair today (`cloze-body` occurs once),
  475 expression-verbatim word-like, 1 clause-like expression (must stay
  invalid), 278 inflection/mis-mine cases (読む→読め, 寒い→寒くなかった),
  4 with an empty `Expression`. Recorded in BULK_FIX.md dimension 6 /
  slice 8.
  Verified by: the census query's per-class counts.

## Lessons Learned

- [2026-11-14, OpenCode] `"<b" in sentence` matches `<br>`, and subtitle
  sentences are full of `<br>` — that silently disabled every bold repair in
  the first build. Use a tag regex (`<b[\s>]|<strong`).
  Verified by: `test_bold_repair_with_br_markup` and an empty bold census in
  the build output before the fix.
- [2026-11-14, OpenCode] Two broken cards were reported by the user; the real
  scope was a moving "last N" window that had dropped the older one. Ad-hoc
  repros must use the same scope as the real run, or they "pass" while
  investigating a card that is no longer in scope.
  Verified by: `--note-id` pinning the card back in and the failing census.
- [2026-11-14, OpenCode] Anki's `AddonManager.loadAddons()` imports each
  add-on folder by name; a folder name that is not a valid identifier
  (e.g. the repo's own hyphenated name) cannot be imported. The add-on
  package is therefore `mining_fixer`, and the repo may be called anything.
  Verified by: `aqt/addons.py` `allAddons`/`loadAddons` and the symlinked dev
  install loading successfully.
- [2026-11-14, OpenCode] Anki 26.09.4 can crash on Browser close with
  `RuntimeError: wrapped C/C++ object of type QWidget has been deleted` in
  `editor_legacy.cleanup → set_note(None) → widget.hide()`. The frames are all
  Anki's own: `Browser.closeWithCallback` is queued through
  `call_after_note_saved`, and if the window is torn down before the queued
  callback fires, cleanup runs against a deleted widget. Add-ons cannot fix
  Anki's teardown, but writing notes from inside a modal dialog while the
  Browser editor has a save in flight puts us in that window — so writes now
  happen after the dialog closes and after the editor flushes
  (`applier.run_after_editor_saved`, QUALITY Q-A5).
  Verified by: the pasted traceback (no Mining Fixer frame) and
  `tests/test_applier.py` timing tests.
- [2026-11-14, OpenCode] The author's machine crashed after this agent ran several
  headless Anki/Qt attempts (`aqt._run(exec=False)` under `QT_QPA_PLATFORM=offscreen`)
  and repeated full-collection copies. The exact cause is unproven, but the
  activity was the heaviest thing on the machine and is now forbidden by
  AGENTS.md §2 rules 2–3. Durable rule: never start Anki/Qt/WebEngine here;
  never copy the collection or scan the deck; use one scoped read-only query
  and CI. Verified by: the crash report and the new rules above.
- [2026-11-14, OpenCode] Qt treats a bare `&` in a menu label as a mnemonic,
  so `preview & apply` renders as `preview apply` with a stray underline.
  Verified by: pinning the literal menu strings in `test_addon_load.py`.
- [2026-11-15, OpenCode] The sentence-repair dimension shipped three rules
  the owner never asked for; they asked for arrows only and the other two
  were rolled back the same day. Do not widen an opt-in dimension beyond
  what the owner described — a census says what is *there*, not what they
  want *changed*.
  Verified by: the rollback commit + the owner-decision notes in
  `BULK_FIX.md`.
