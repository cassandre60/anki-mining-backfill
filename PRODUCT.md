# Mining Backfill — Product Definition

Authoritative source for *what this add-on is supposed to do*. Code
implements this document, tests enforce it, architecture serves it.
(See `AGENTS.md` for the authority hierarchy.)

## Problem

Mining a Japanese sentence with asbplayer + Yomitan creates a card per word.
The *first* card of a scene usually gets everything — the full scene sentence,
furigana, sentence audio, the picture, the timestamped source. Every later
card from the same scene is created from a fragment, and depending on where
the mining run was interrupted it ends up missing some of:

- the full scene `Sentence` (it holds only the subtitle fragment the word
  appeared in, or — worse — dictionary-entry text when the lookup was
  mis-mined),
- `Sentence (furigana)`, `Sentence Audio`, `Picture`, the timestamped
  `Source` (still the asbplayer blob URL),
- word-level fields (`Definition`, `Extended definition`, `Pitch Accent`,
  `Frequency`, `Word Audio`, `furigana`, `reading`),
- the **bold** term inside `Sentence` that marks the word being studied.

Fixing these by hand costs minutes per card, and the information already
exists — it is sitting in an enriched sibling card.

## Target users

Anki users mining Japanese with asbplayer + Yomitan into a "Japanese Note
type (Sentence card by Default)"-style note type, who want their incomplete
cards completed from the siblings they already have — without retyping
anything and without risking a field they have hand-edited.

## Core user journeys

1. **Preview and apply in Anki.** Tools → *Mining Backfill: preview and
   apply…*; the dialog lists every proposed write (note, field, exact
   old → new, source card, badges) with the guarded rows unchecked. The user
   applies, then studies the cards.
2. **Undo.** Tools → *Mining Backfill: undo last run* reverses exactly what
   the last apply replaced.
3. **Dry run as a package.** `scripts/build_audit_package.py` exports an
   `.apkg` into a separate deck, so a whole run can be reviewed without the
   add-on touching the live collection at all.
4. **Read the run.** Every run also produces a Markdown report (per-card
   table) and a JSON plan log (every old value) for auditing outside Anki.

## Principles

- **The user's data is never destroyed.** Fills only touch empty fields; the
  four non-empty writes each keep their information (`Source` blob URL is
  logged, the mined fragment survives in `cloze-*`, the bold repair is
  markup-only, tags only grow).
- **Preview before apply.** Nothing is written until the user accepts rows.
- **Report, don't guess.** Ambiguity (two plausible bold targets, divergent
  parents, unreadable provenance) becomes a visible reason or warning.
- **Offline.** No network access of any kind.
- **Reversible.** Every write carries its old value in a run log.

## Non-goals

- **Not** a mining tool, dictionary, or definition generator: it copies what
  already exists in the collection.
- **Not** a general-purpose card fixer for arbitrary note types: field names
  and the scene/word heuristics are configured for one mining workflow
  (`mining_backfill/config.json`).
- **Not** a sync or backup system.
- **Not** automatic: there is no background watcher and no silent repair on
  card creation. The user runs it.

## Success criteria

- A user can complete a freshly mined card's missing fields in one accepted
  preview, with the bold term on the right word.
- No card is ever left half-applied, and no accepted write can be traced to a
  value the plan did not show.
- Anything the tool cannot safely do is reported, with a reason, in the same
  dialog.
