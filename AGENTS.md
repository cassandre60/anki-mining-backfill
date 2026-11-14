# Mining Backfill — Agent Operating Rules

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

- `mining_backfill/` — **the add-on**. Anki discovers any `addons21/<folder>/`
  that contains `__init__.py` and imports that folder as a Python package.
- `scripts/`, `tests/` — development tooling. Nothing here ships.

`mining_backfill/` is packaged for AnkiWeb as a zip whose root contains
`manifest.json` and `__init__.py`; `meta.json` in that folder is a
**dev-install artefact and is gitignored** — never commit it.

## 2. Hard rules

1. **Never write to a live Anki profile from development tooling.** Copy the
   collection first (the builder does this via `--profile-dir` → `--work-dir`),
   or point Anki itself at a scratch base (`ANKI_BASE`). The only code allowed
   to modify someone's collection is the add-on itself, after the user pressed
   Apply — and it must leave an undo log.
2. **The pure core stays pure.** `normalize.py`, `fieldconfig.py`,
   `matching.py`, `plan.py`, `report.py`, `applier.py` must not import
   `anki`, `aqt` or PyQt — `tests/test_layer_boundary.py` fails if they do,
   and the headless builder plus most of the suite depend on it. Only
   `__init__.py`, `collection_io.py` and `preview_dialog.py` may touch Anki.
3. **Never guess.** Ambiguity is reported (`plan.reasons`, `plan.warnings`),
   never resolved by picking one of several plausible values.
4. **Fills only; four approved non-empty writes** (`Source`, `Sentence`,
   `bold_cloze_word`, `add_tags`) — each must preserve its information, and
   each carries badges. See `QUALITY.md`.
5. **Tags are never removed** and bookkeeping tags are never added: the audit
   deck is the container, the note carries only the target's and its sources'
   tags.
6. **Fully offline.** No network calls, no telemetry, no auto-update behaviour
   beyond Anki's own.
7. **No secrets, ever** — not in code, config, fixtures or logs. Fixtures are
   real captures from the author's collection; keep them minimal.
8. **Import-time safety.** Anything in `__init__.py` that raises is what users
   see as "add-on failed to load". Guard it, print instead of throwing.

## 3. Environment (verified on the author's machine)

- Arch Linux; Anki 26.09.4 (`/usr/bin/anki`, PyQt6 6.12); system `python3` is
  what has the `anki` package, so headless tooling runs with plain `python3`.
- `ruff` is in `/usr/bin`; pytest is **not** in system Python (Arch splits
  it) — CI installs it, or use a venv.
- Repo layout: pure core + add-on shell in `mining_backfill/`, tests in
  `tests/` (a `conftest.py` puts the repo root on `sys.path`).

## 4. Gates before you present work

```bash
ruff check . && ruff format --check .     # must be clean
python3 -m pytest                         # 90 tests with Anki installed
```

Then push and watch CI — it is the gate, and it runs without Anki (89 passed,
1 skipped):

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
  package is therefore `mining_backfill`, and the repo may be called anything.
  Verified by: `aqt/addons.py` `allAddons`/`loadAddons` and the symlinked dev
  install loading successfully.
- [2026-11-14, OpenCode] Qt treats a bare `&` in a menu label as a mnemonic,
  so `preview & apply` renders as `preview apply` with a stray underline.
  Verified by: pinning the literal menu strings in `test_addon_load.py`.
