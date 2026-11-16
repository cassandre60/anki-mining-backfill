#!/usr/bin/env python3
"""List the cards a run cannot fix, with the word and a plain reason.

Read-only and copy-free: the collection is opened `immutable` (a consistent
snapshot of the live file — Anki can keep running). Nothing is written.

    python3 scripts/unfixed_report.py --profile-dir "<Anki profile dir>" --last 300

Output: how many of the newest N cards a run fixes, then one line per card
it cannot — `word — reason`, in the same plain words the batch window uses.
This is the list to work through for cards that need re-mining (reason
"nothing to copy from — no other card contains this sentence") versus cards
the tool deliberately leaves alone (ambiguous bolding, disagreeing parents).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from mining_fixer.batch import default_ops, reason_text, select  # noqa: E402
from mining_fixer.matching import NoteRecord  # noqa: E402
from mining_fixer.plan import build_plan  # noqa: E402

PLAIN = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()  # noqa: E731


def load_records(db_path: Path, note_type_name: str) -> tuple[list[NoteRecord], list[str]]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True, timeout=30)
    con.create_collation(
        "unicase", lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold())
    )
    try:
        row = con.execute("select id from notetypes where name=?", (note_type_name,)).fetchone()
        if row is None:
            raise SystemExit(f"note type {note_type_name!r} not found")
        ntid = row[0]
        names = {
            ord_: name
            for ord_, name in con.execute(
                "select ord, name from fields where ntid=? order by ord", (ntid,)
            )
        }
        order = [names[o] for o in sorted(names)]
        records = [
            NoteRecord(
                note_id=nid,
                notetype_id=ntid,
                fields=dict(zip(order, flds.split("\x1f"), strict=False)),
                tags=frozenset(tags.split()),
            )
            for nid, flds, tags in con.execute(
                "select id, flds, tags from notes where mid=?", (ntid,)
            )
        ]
    finally:
        con.close()
    return records, order


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", required=True, type=Path)
    parser.add_argument("--last", type=int, default=300)
    args = parser.parse_args()

    cfg = json.loads((REPO_ROOT / "mining_fixer" / "config.json").read_text(encoding="utf-8"))
    db = args.profile_dir / "collection.anki2"
    records, _order = load_records(db, cfg["note_type_name"])
    newest = sorted(records, key=lambda r: r.note_id, reverse=True)[: args.last]
    ids = [r.note_id for r in newest]

    plan = build_plan(records, cfg, scope_note_ids=ids, media_exists=lambda _n: True)
    selection = select(plan, default_ops(cfg))
    fixed = {w.note_id for w in selection.rows}
    reasons = {item.note_id: item.reason for item in selection.left_alone}

    planned: dict[int, list] = {}
    for write in plan.writes:
        planned.setdefault(write.note_id, []).append(write)

    def why(note_id: int, note: NoteRecord) -> str:
        gaps = [
            field
            for field in ("Sentence Audio", "Picture", "Translation", "Sentence (furigana)")
            if not (note.get(field) or "").strip()
        ]
        real_gaps = [field for field in gaps if field != "Sentence (furigana)"]
        if not real_gaps:
            return "furigana only — filled inside Anki"
        if "Sentence Audio" not in real_gaps and "Picture" not in real_gaps:
            # The scene media is there; what is left is a translation (and the
            # ruby, which Anki fills), and no other card has one to copy.
            suffix = " (furigana is filled inside Anki)" if "Sentence (furigana)" in gaps else ""
            return f"only {', '.join(real_gaps)} missing — nothing to copy from{suffix}"
        if note_id in reasons:
            return reason_text(reasons[note_id])
        if note_id in planned:
            badges = {badge for w in planned[note_id] for badge in w.badges}
            if "divergent-parents" in badges:
                return "parents disagree — suggested only, not trusted"
            if "far-from-source" in badges:
                return "source is far away — suggested only, not trusted"
            if any(not w.default_checked for w in planned[note_id]):
                return "row needs your review (guarded)"
            return "row not enabled by policy"
        return reason_text(str(plan.reasons.get(note_id, "already complete")))

    print(
        f"newest {len(newest)} cards: {len(fixed)} fixed by a run, {len(newest) - len(fixed)} not"
    )
    print("(furigana regeneration runs only inside Anki and is not counted here)\n")
    for note in newest:
        if note.note_id in fixed:
            continue
        word = PLAIN(note.get("Expression")) or PLAIN(note.get("cloze-body")) or note.note_id
        print(f"  {str(word)[:28]:30} {why(note.note_id, note)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
