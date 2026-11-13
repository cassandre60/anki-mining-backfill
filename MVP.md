# Mining Backfill — MVP / Current Scope

`PRODUCT.md` answers *what this add-on is*.
This file answers *what is actually built right now*. Do not widen this
scope inside a coding session — new work enters through
`IMPLEMENTATION_PLAN.md`.

## MVP goal (achieved, v0.2.0)

A user installs the add-on, opens one dialog, reviews the proposed fixes for
their newest mined cards, applies them, and can undo the whole thing — with
the collection never touched by anything the dialog did not show.

## Included capabilities (shipped and tested)

| Capability | Where | Evidence |
|---|---|---|
| Scene completion (full sentence, furigana, audio, picture, timestamped source) | `matching.find_scene_parents`, `plan._scene_writes_for` | golden fixture, byte-exact |
| Word backfill (`Definition`, `Extended definition`, `Pitch Accent`, `Frequency`, `Word Audio`, `furigana`, `reading`) | `matching.word_groups`, `plan._word_writes_for` | unit tests + real-collection run |
| Bold repair when `Sentence` has no bold term | `plan._bold_repair_for` | 鬱病 verified end to end |
| Tag union from contributing sources (never removes) | `plan._tags_write_for` | golden test pins 診察 = `asbplayer yomitan` |
| Preview dialog with per-row checkboxes, not-fixable and warning tabs | `preview_dialog.py` | import check + real-apply run |
| Apply with per-note re-assertion and no-op re-runs | `applier.decide` | `tests/test_applier.py` (13 tests) |
| Undo of the last run | `applier.decide_undo`, `__init__._on_undo` | real-collection run |
| Audit `.apkg` builder (dry runs) | `scripts/build_audit_package.py` | rebuilt package verified to the note |
| CI gate (ruff + suite) | `.github/workflows/tests.yml` | green on every push |

## Excluded from the MVP

- **Browser selection as the scope.** The dialog plans the newest
  `preview_last_n` notes of the configured deck. Using the Browser selection
  is planned (`IMPLEMENTATION_PLAN.md` B1).
- **Rendered front/back HTML per row.** Rows show field values, not the card
  as the template renders it (B2).
- **AnkiWeb release.** Today it is a dev install: symlink into `addons21/`
  plus a hand-written `meta.json`. Publishing gives a numeric package id,
  self-updates and one-click install (B3).
- **Packaging script.** No `.ankiaddon`/zip build step exists yet (B3).
- **Config dialog.** Defaults ship in `mining_backfill/config.json`; Anki's
  built-in config editor (Tools → Add-ons → Config) shows the merged config
  and stores edits in `meta.json`. No custom config UI (not planned).
- **Any auto-update of the AnkiWeb listing**, any network feature: permanently
  out (PRODUCT.md, non-goals).

## Known limitations

- Scope is a moving "last N": a card can leave it as new cards are mined. The
  audit builder has `--note-id` for pinning; the dialog does not yet (B1 fixes
  this properly).
- The word-group key is `(Expression, reading, furigana)`-derived; a card whose
  `reading` field is empty-but-`furigana`-populated is matched on `furigana`.
  There is deliberately no reading-only matching.
- Confidence is expressed as default-check state plus badges, not as a score:
  guarded rows arrive unchecked and the user decides.
- The plan is computed when the dialog opens; a card edited in another window
  mid-review is re-asserted at apply time and reported as `changed since
  preview` rather than retried.

## Acceptance criteria (every release)

- `ruff check .` and `ruff format --check .` clean; `python3 -m pytest` green
  (84 tests with Anki installed).
- CI (`tests` workflow) green on the released commit.
- The golden fixture test still reproduces the author's manual fix
  byte-for-byte on all five fields.
- A real-collection apply + undo run on a **copy** lands every checked write
  verbatim and restores it.
