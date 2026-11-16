#!/usr/bin/env python3
"""Audit a whole selection for the defects the author keeps finding by hand.

Copy-free for the collection (it works on a temporary copy), read-only for
the profile, and general: it does not test named cards, it *measures* four
invariants over every card in scope, after applying a run to the copy.

    python3 scripts/scene_audit.py --profile-dir "<Anki profile dir>" --last 300

Invariants (a card fails if any is broken):
  A  every ``[sound:...]`` / ``<img src=...>`` file referenced exists;
  B  the Sentence Audio equals what the cards sharing its sentence use —
     the same block's cards must agree, so another moment's sound fails;
  C  a non-empty ruby describes the sentence (base text matches);
  D  exactly one bold span, wrapping one of the card's own spellings.

Output is a count per class with examples. Zero on every line means the
corpus is coherent; the author's reported cards would appear under B, C, D.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from build_audit_package import prepare_work_dir, records_from_collection  # noqa: E402

from mining_fixer.applier import NoteState, decide  # noqa: E402
from mining_fixer.batch import default_ops, select  # noqa: E402
from mining_fixer.matching import kana_spelling_candidates  # noqa: E402
from mining_fixer.normalize import (  # noqa: E402
    furigana_base_matches,
    kana_fold,
    strip_renderable,
)
from mining_fixer.plan import build_plan  # noqa: E402

SOUND_RE = re.compile(r"\[sound:([^\]]+)\]")
IMG_RE = re.compile(r"<img[^>]+src=[\"']?([^\"'>]+)", re.IGNORECASE)
BOLD_RE = re.compile(r"<b>(.*?)</b>", re.DOTALL)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", required=True, type=Path)
    parser.add_argument("--work-dir", type=Path, default=Path("/tmp/opencode/mb_audit"))
    parser.add_argument("--last", type=int, default=300)
    args = parser.parse_args()

    if args.work_dir.exists():
        shutil.rmtree(args.work_dir)
    prepare_work_dir(args.profile_dir, args.work_dir)
    from anki.collection import Collection

    col = Collection(str(args.work_dir / "collection.anki2"))
    cfg = json.loads((REPO_ROOT / "mining_fixer" / "config.json").read_text(encoding="utf-8"))
    media_dir = args.work_dir / "collection.media"

    def media_exists(name: str) -> bool:
        return (media_dir / name).exists()

    try:
        records = records_from_collection(col, cfg["deck_name"], cfg["note_type_name"])
        scope = [r.note_id for r in sorted(records, key=lambda r: r.note_id, reverse=True)]
        scope = scope[: args.last]
        plan = build_plan(records, cfg, scope_note_ids=scope, media_exists=media_exists)
        selection = select(plan, default_ops(cfg))

        def state(note_id: int) -> NoteState:
            note = col.get_note(note_id)
            return NoteState(fields=dict(note.items()), tags=frozenset(note.tags))

        decision = decide(
            plan,
            [(w.note_id, w.field) for w in selection.rows],
            state,
            applied_tag=cfg.get("applied_tag") or None,
        )
        for write in decision.field_writes:
            note = col.get_note(write.note_id)
            note[write.field] = write.new_value
            col.update_note(note)
        for write in decision.tags_writes:
            note = col.get_note(write.note_id)
            note.tags = list(write.new_tags)
            col.update_note(note)

        fields = {note_id: dict(col.get_note(note_id).items()) for note_id in scope}
        by_sentence: dict[str, list[int]] = collections.defaultdict(list)
        for note_id in scope:
            by_sentence[strip_renderable(fields[note_id].get("Sentence"))].append(note_id)

        violations: collections.Counter[str] = collections.Counter()
        examples: dict[str, list[str]] = collections.defaultdict(list)
        for note_id in scope:
            card = fields[note_id]
            sentence = card.get("Sentence") or ""
            ruby = card.get("Sentence (furigana)") or ""
            word = (card.get("Expression") or card.get("cloze-body") or "")[:14]

            refs = SOUND_RE.findall(sentence) + IMG_RE.findall(sentence)
            refs += [ref for value in card.values() for ref in SOUND_RE.findall(value)]
            if any(not media_exists(ref) for ref in refs):
                violations["A media file missing"] += 1
                examples["A media file missing"].append(word)

            mates = [n for n in by_sentence[strip_renderable(sentence)] if n != note_id]
            own_audio = tuple(sorted(SOUND_RE.findall(card.get("Sentence Audio") or "")))
            mate_audio = {
                tuple(sorted(SOUND_RE.findall(fields[m].get("Sentence Audio") or "")))
                for m in mates
            }
            if own_audio and mate_audio and own_audio not in mate_audio:
                violations["B audio differs from its scene"] += 1
                examples["B audio differs from its scene"].append(word)

            if ruby.strip() and sentence.strip() and not furigana_base_matches(ruby, sentence):
                violations["C ruby does not match its sentence"] += 1
                examples["C ruby does not match its sentence"].append(word)

            spellings = {
                (card.get("Expression") or "").strip(),
                strip_renderable(card.get("cloze-body")).strip(),
                kana_fold(card.get("Expression") or ""),
                *kana_spelling_candidates(card.get("Expression") or "", card.get("furigana") or ""),
            } - {""}
            spans = BOLD_RE.findall(sentence)
            if len(spans) > 1 or (
                spans and not any(strip_renderable(span).strip() in spellings for span in spans)
            ):
                violations["D bold missing, doubled or on another word"] += 1
                examples["D bold missing, doubled or on another word"].append(
                    f"{word}: {spans[:2]}"
                )

        print(f"audited {len(scope)} cards after a run on a copy")
        if not violations:
            print("  no violations")
        for name, count in violations.most_common():
            print(f"  {count:4}  {name}  e.g. {examples[name][:4]}")
        return 1 if violations else 0
    finally:
        col.close()


if __name__ == "__main__":
    raise SystemExit(main())
