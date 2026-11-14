# Mining Backfill — Implementation Plan

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
- **T5 — Installable add-on.** Package layout (`mining_backfill/`), entry
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

## Backlog

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
