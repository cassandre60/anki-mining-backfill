# Mining Fixer — Test Strategy

Answers: *how do we mechanically prove `QUALITY.md` stays true?*

```text
QUALITY.md (WHAT must hold)
    ↓
TEST_STRATEGY.md (HOW it is verified)
    ↓
tests/ · linters · ad-hoc real-collection runs · CI
```

## The rings (cheap → expensive)

Every behaviour is verified in exactly one ring — the cheapest ring that can
observe it. A new check goes in the innermost ring that can see the behaviour
and moves outward only when it needs more of the real world.

| Ring | What | Where it runs | Cost |
|---|---|---|---|
| **Ring 0 — pure units** (`tests/test_normalize.py`, `test_fieldconfig.py`, `test_matching.py`, `test_plan.py`, `test_applier.py`, `test_batch.py`, `test_invariants.py`, `test_layer_boundary.py`) | Every pure function against plain values: normalization keys, field semantics, parent ranking, plan guards and badges, the apply/undo decision matrix, the batch policy (tiers, group and note atomicity, review shortlist), **property-based invariants** over generated plans (every write's precondition holds, apply→undo restores exactly, re-running is a no-op, an edited field aborts its note), and the AST-enforced layer boundary. No Anki, no Qt, no collection, no network. | Local + CI | ms–2 s |
| **Ring 1 — golden acceptance** (`tests/test_golden_scene.py`) | The pipeline must reproduce the author's real manual fix (診察, from scene 至急) **byte-for-byte on all five fields** plus the tag union, from a frozen fixture (`tests/fixtures/golden_scene.json`). This is the anchor: if it moves, behaviour moved. | Local + CI | ms |
| **Ring 2 — add-on load contract** (`tests/test_addon_load.py`) | Imports the package *the way Anki does* (folder name → package, stubbed `aqt`), asserting the two Tools entries are added once, the banner reports the packaged version, a missing main window does not raise, and the Browser context-menu action appears **only** when notes are selected (ids captured when the menu opened). Catches "add-on failed to load" and menu-wiring regressions. | Local + CI | ms |
| **Ring 3 — real-collection verification** (ad-hoc scripts, not committed as tests) | Apply + undo against a **copy** of the real collection (every checked write lands verbatim, guarded-only notes untouched, undo restores exactly); the audit builder's `--last`/`--note-id` scope and package round-trip; the entry point against the real `aqt` package. A live-GUI pass is manual: apply from the Browser selection, then close the Browser and quit Anki, watching the debug console — Anki's legacy-editor teardown has its own known crash (see `AGENTS.md`), and no headless harness here reproduces the Browser's save/close path reliably. | Author's machine, on demand | seconds–minutes |
| **Ring 4 — CI gate** (`.github/workflows/tests.yml`) | `ruff check` + `ruff format --check` + the whole suite on every push and PR, with **no Anki installed**. Green exit code is the gate. | GitHub Actions | ~15 s |

Ring 3 exists because Rings 0–2 cannot see Anki's own API behaviour. It is
deliberately not a committed test: it needs a real collection, which CI does
not have and must never be given.

## Coverage contract (no duplication)

- Every pure function is pinned in exactly ONE ring.
- The **apply and undo decision matrix** lives in `tests/test_applier.py`
  against a dict-backed fake `NoteState` reader — including the cases that
  matter: one stale row skipping a whole note, re-run detection, tags-only-add
  with a tag gained since preview, `applied_tag` on written notes, undo of
  edited notes, idempotent undo, and the undo-log lookup (newest log across
  the current and the pre-rename `mining_backfill` folder, none when the
  newest log is unreadable).
- **The repair pipeline** (bulk-fix dimension 2) is pinned in
  `tests/test_normalize.py` (real deck values, tail arrows stripped while
  line breaks, spacing and bold markup stay untouched, idempotence,
  mid-line arrows kept), `tests/test_plan.py` (checked write
  with rule badges, off without rules, exclusivity with expansion/bold,
  tested-word occurrence guard, unknown-rule warning) and
  `tests/test_batch.py` (the opt-in `batch_repair_sentence` tier).
- **Bold repair** (template contract) is pinned in `tests/test_plan.py`:
  the three tiers (cloze-body, Expression verbatim, reading-derived
  surface form), exactly-one occurrence, markup-only verification,
  ambiguity reported, the word-like gate (a clause-like Expression such
  as 漢字は読めるようになりたいかな is refused with
  `expression-not-word-like`; an over-long word is skipped too), and the
  listening predicate (tag + audio; no-gloss/no-frequency/audio shape;
  Frequency-without-glosses still repaired). The shipped-class/left-alone
  split comes from the 2026-11-16 census (BULK_FIX slice 8).
- **Furigana regeneration** (bulk-fix dimension 3) is pinned in
  `tests/test_normalize.py` (`furigana_base_matches`: whitespace and the
  engine's spacing quirks, speaker brackets, mangled/unbalanced output
  rejected), `tests/test_plan.py` (checked write with badges, off by
  default, noop when the ruby already matches, generator unreachable →
  one warning per run, generated from the post-repair sentence, defers to
  a queued scene fill of the field, dropped on a mangled or raising
  engine) and `tests/test_batch.py` (the opt-in `batch_regenerate_furigana`
  tier). The engine itself is never faked into the suite's core paths: it
  is an injected callable, so a broken MeCab degrades to a skip, not a
  wrong write — **never run it inside Anki from the suite**.
- **Expression repair** (bulk-fix dimension 4, self-oracled variant, Q-D12)
  is pinned in `tests/test_normalize.py` (`furigana_base` extracts the
  dictionary form from inline ruby, unusable markup yields nothing),
  `tests/test_plan.py` (the ひと握り → 一握り rewrite from the note's own
  furigana, off by default, inert when the furigana base already matches the
  Expression, silent without furigana, reading mismatch reported, kanji-less
  and clause-like bases refused, deferred while word-level writes are
  queued), and `tests/test_batch.py` (the opt-in `batch_repair_expression`
  tier, selected only when enabled).
- **Write timing** is pinned in the same file with fake editors: writes wait
  for `call_after_note_saved`, a doubled editor callback writes once, a lost
  callback is covered by the scheduler safety net, and a raising or missing
  editor still lets the run through.
- **Batch policy** lives in `tests/test_batch.py`: the default tier is
  lossless, the text unit (sentence + ruby) is atomic, a text-safety guard
  drops only the sentence while the scene's audio/picture are still filled, a
  source-confidence guard leaves the whole note alone, complete notes count as
  untouched, and tag-only notes are reported separately.
- **Source confidence** is pinned in `tests/test_plan.py`: disagreeing parents
  are never auto-checked, a far containment match ships unchecked, and a
  byte-identical sentence stays trusted at any distance.
- **Engine invariants** live in `tests/test_invariants.py` and are generated
  with Hypothesis: every write's precondition holds at decision time,
  applying then undoing restores the exact prior state, re-running a plan
  after apply writes nothing, and editing one field aborts that note.
- **Scale proof** (Ring 3): 1000 selected notes on a copy of the real
  collection — plan 2.2 s, apply 1.5 s with a backup, verification clean, the
  793 untouched notes byte-identical, re-run a no-op, undo restoring all 1000
  exactly.
- **Acceptance runs use a curated battery, not bulk 1000-note runs** (owner
  guidance, 2026-11-16). Future Ring 3 runs pick a small set where each card
  pins one defect class — a failure then names the class it broke instead of
  hiding in aggregate counts. The 1000-note run above stands as the one-off
  scale proof; it does not need repeating per dimension.

  | # | Class | Card property | Must prove |
  |---|---|---|---|
  | 1 | tail arrow only | `Sentence` ends `➡` | arrow stripped, every other character byte-identical |
  | 2 | mid-line arrow | `f:X→Y` inside a line | no write at all (pure noop) |
  | 3 | arrow around bold | `…<b>殺し</b>➡` | arrow gone, `<b>` intact |
  | 4 | anchor risk | the tested word's occurrence count would change | skipped with a warning, no write |
  | 5 | expansion queued | scene gap + tail arrow | exactly one `Sentence` row (the expansion), no repair row |
  | 6 | bold repair queued | no `<b>` in `Sentence` + tail arrow | the bold row owns the field, no repair row |
  | 7 | stale furigana | sentence fine, ruby wrong | regenerated row with an old → new diff |
  | 8 | correct furigana | already annotated as the engine would | no furigana row |
  | 9 | child of a source | child with empty ruby under a scene fill | scene fill only, no regen row |
  | 10 | blob Source | asbplayer URL | timestamped replace, URL recorded in the run log |
  | 11 | divergent parents | two parents, different payloads | left unchecked with the divergence reason |
  | 12 | nothing to fix | fully enriched note | untouched; byte-identical after apply + undo |

  Twelve cards, one per class; a new guard adds one card, not a bigger run.

  The runner is `scripts/acceptance_battery.py`: give it a copy of the
  profile (`--profile-dir` → `--work-dir`, the builder's pattern) and a
  battery JSON mapping each class to note ids; it prints PASS/FAIL per
  class from the plan alone and writes nothing. Every dimension runs by
  default (owner decision 2026-11-16), so `--arrows` / `--furigana` only
  force a dimension back on after a config switched it off. The two
  furigana classes need Japanese Support's engine, which exists only
  inside a running Anki — headless they cannot pass.
- The **UI** (`preview_dialog.py`) is not unit-tested; its import is checked
  in Ring 2 and its behaviour is exercised by Ring 3's apply run. Anything
  decision-shaped in it is delegated to `applier.py`/`plan.py` precisely so it
  can be tested there.
- `collection_io.py` is a thin adapter and is covered by Ring 3; the parts
  worth pinning (`_media_exists` behaviour, `deck_records` returning `None`
  for a missing deck) are deliberately fail-visible in its docstrings rather
  than mocked.

## Self-skipping, not faking

`test_preview_dialog_imports_with_real_anki` needs the real Anki/PyQt6 stack.
Where that is absent (CI) it **skips** via `pytest.importorskip`; it never
falls back to a stub, because a stub would not catch a broken Qt name. So the
expected counts are:

| Environment | Result |
|---|---|
| Author's machine (`python3 -m pytest`, Anki present) | **173 passed** |
| CI / a venv without Anki | **171 passed, 2 skipped** |

Both are green; the difference is exactly two self-skipping import checks
(the dialog modules need a real `aqt`).

## Fail-to-pass for bug fixes

A test added for a bug must be able to fail on the unfixed code. Two real
examples from this repo's history:

- `<b` matched `<br`, silently disabling every bold repair →
  `test_bold_repair_with_br_markup` pins the `<br>` case.
- An already-applied row was misreported as stale (re-running a plan looked
  like a conflict) → `test_rerunning_the_same_plan_is_a_noop`.

When the bug is only observable with real Anki/anime data, the observation
that made it visible is recorded in the test or in this file rather than
faked with a stub that cannot see it.

## Running things

```bash
ruff check . && ruff format --check .   # Ring 4 locally, fast
python3 -m pytest                       # Rings 0–2
gh run watch --exit-status              # Ring 4, the gate
```

The suite is hermetic and sub-second, so local runs are cheap and allowed —
unlike a heavyweight workspace suite, it cannot pin the machine. Real-collection
work (Ring 3) must always copy the collection first:

```bash
cp "$HOME/.local/share/Anki2/User 1/collection.anki2"* /tmp/opencode/probe/
ln -s "$HOME/.local/share/Anki2/User 1/collection.media" /tmp/opencode/probe/collection.media
```

## Static guards

- `test_layer_boundary.py` — no `anki`/`aqt`/PyQt import outside the three
  Qt-facing modules, relative intra-package imports only (flat module names
  would collide across add-ons in Anki's shared `sys.path`).
- `ruff` — lint (`E,F,I,UP,B,SIM`) plus formatting, line length 100.
- `test_addon_load.py` also asserts the menu labels contain no Qt mnemonic
  `&`, a rendering hazard that no runtime test would catch.
