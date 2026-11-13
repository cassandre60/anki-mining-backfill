# Mining Backfill

An Anki add-on that completes incompletely-mined Japanese cards by copying
from their enriched siblings — the already-finished card of the same scene,
or a sibling card of the same word. Built for asbplayer + Yomitan mining
workflows where enrichment is interrupted: the card stays without scene
audio, picture, timestamped source, or the full scene sentence, and fixing
each one by hand costs minutes per card.

**Status: prototype / audit build.** The matching core and the headless
audit-package builder are complete and tested; the in-Anki (aqt) preview
dialog is the next step. See [Roadmap](#roadmap).

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

## The audit package

The prototype builds an `.apkg` you import into Anki to audit the fixes
without touching your collection:

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

## Development

```
python3 -m pytest -q     # 63 tests, incl. the golden fixture test
ruff check . && ruff format .
```

The golden test (`tests/test_golden_scene.py`) reproduces a real manual fix
from the author's collection **byte-for-byte on all five fields** — media,
source, furigana, and the sentence with the bold retargeted to the card's
own word. The core modules (`normalize.py`, `fieldconfig.py`,
`matching.py`, `plan.py`, `report.py`) import no `anki`/`aqt` — enforced by
an AST test — so the same code runs headless, in tests, and inside Anki.

## Roadmap

- [ ] aqt add-on shell: preview dialog rendering real front/back HTML per
  row, apply with TOCTOU re-assertion, backup + inverse-patch restore.
- [x] CI workflow: `ruff` + the full test suite on every push and pull
  request (`.github/workflows/tests.yml`).
- [ ] AnkiWeb add-on release.

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE).
