#!/usr/bin/env python3
"""Ring 3 acceptance battery: preview the plan for one card per defect class.

Runs against a COPY of the user's collection (``--profile-dir`` ->
``--work-dir``, the builder's pattern). Nothing is written: the script prints
what the plan would do for each card and whether that matches the class's
expectation (TEST_STRATEGY.md, "Acceptance runs use a curated battery").

Usage:
    python3 scripts/acceptance_battery.py --profile-dir "<Anki profile dir>" \
        --work-dir /tmp/opencode/mb_battery --battery battery.json

``--arrows`` / ``--furigana`` force those dimensions on for the run; with
the shipped defaults both are already on, so the flags are only needed when
the config switched one off.

Battery file (one or more note ids per class):
    {
      "classes": {
        "arrow-only": [1794600000001],
        "midline-arrow": [1794600000002],
        ...
      }
    }

Classes (TEST_STRATEGY.md): arrow-only, midline-arrow, arrow-around-bold,
anchor-risk, expansion-queued, bold-repair-queued, stale-furigana,
correct-furigana, child-with-scene-fill, blob-source, divergent-parents,
nothing-to-fix.

The furigana classes need Japanese Support's engine, which only exists inside
a running Anki; headless, the planner reports the dimension unavailable (a
warning) and those classes cannot pass. Run them from the add-on instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_audit_package import (  # noqa: E402
    load_config,
    prepare_work_dir,
    records_from_collection,
)

from mining_fixer.plan import (  # noqa: E402
    OP_BOLD_CLOZE_WORD,
    OP_EXPAND_SENTENCE,
    OP_REGENERATE_FURIGANA,
    OP_REPAIR_SENTENCE,
    OP_REPLACE_SOURCE,
    build_plan,
)

#: What each class must prove (TEST_STRATEGY.md). One key per class:
#: ``op`` = a write with this op must exist; ``no_op`` = it must not;
#: ``unchecked`` = a row left unchecked must exist; ``no_writes`` = none.
EXPECTATIONS: dict[str, dict] = {
    "arrow-only": {"op": OP_REPAIR_SENTENCE},
    "midline-arrow": {"no_op": OP_REPAIR_SENTENCE},
    "arrow-around-bold": {"op": OP_REPAIR_SENTENCE},
    "anchor-risk": {"no_op": OP_REPAIR_SENTENCE},
    "expansion-queued": {"op": OP_EXPAND_SENTENCE},
    "bold-repair-queued": {"op": OP_BOLD_CLOZE_WORD},
    "stale-furigana": {"op": OP_REGENERATE_FURIGANA},
    "correct-furigana": {"no_op": OP_REGENERATE_FURIGANA},
    "child-with-scene-fill": {"no_op": OP_REGENERATE_FURIGANA},
    "blob-source": {"op": OP_REPLACE_SOURCE},
    "divergent-parents": {"unchecked": True},
    "nothing-to-fix": {"no_writes": True},
}


def load_battery(path: Path) -> dict[str, list[int]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    classes = data.get("classes")
    if not isinstance(classes, dict):
        raise SystemExit('battery file must hold {"classes": {"<class>": [note ids]}}')
    unknown = sorted(set(classes) - set(EXPECTATIONS))
    if unknown:
        raise SystemExit(f"unknown battery class(es): {', '.join(unknown)}")
    return {name: [int(nid) for nid in ids] for name, ids in classes.items()}


def verdict(writes, reasons, expectation: dict) -> tuple[bool, str]:
    note_writes = list(writes)
    ops = {w.op for w in note_writes}
    if "op" in expectation:
        ok = expectation["op"] in ops
        return ok, f"expected a {expectation['op']} row"
    if "no_op" in expectation:
        ok = expectation["no_op"] not in ops
        return ok, f"expected no {expectation['no_op']} row"
    if "unchecked" in expectation:
        ok = any(not w.default_checked for w in note_writes)
        return ok, "expected a row left unchecked"
    if "no_writes" in expectation:
        return not note_writes, "expected no writes at all"
    return False, "unknown expectation"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--battery", required=True, type=Path)
    parser.add_argument("--arrows", action="store_true", help="force the arrow tier on")
    parser.add_argument("--furigana", action="store_true", help="force the furigana tier on")
    args = parser.parse_args()

    classes = load_battery(args.battery)
    ids = sorted({nid for note_ids in classes.values() for nid in note_ids})
    if not ids:
        raise SystemExit("battery file lists no note ids")

    cfg = load_config()
    if args.arrows:
        cfg["batch_repair_sentence"] = True
        cfg["sentence_repair_rules"] = ["strip-arrows"]
    if args.furigana:
        cfg["batch_regenerate_furigana"] = True

    from anki.collection import Collection

    prepare_work_dir(args.profile_dir, args.work_dir)
    col = Collection(str(args.work_dir / "collection.anki2"))
    try:
        records = records_from_collection(col, cfg["deck_name"], cfg["note_type_name"])
        plan = build_plan(
            records,
            cfg,
            scope_note_ids=ids,
            media_exists=lambda name: (args.work_dir / "collection.media" / name).exists(),
        )
    finally:
        col.close()

    by_note: dict[int, list] = {}
    for write in plan.writes:
        by_note.setdefault(write.note_id, []).append(write)

    failures = 0
    print(f"battery: {len(classes)} class(es), {len(ids)} card(s)")
    for name, note_ids in classes.items():
        expectation = EXPECTATIONS[name]
        for nid in note_ids:
            ok, want = verdict(by_note.get(nid, []), plan.reasons.get(nid), expectation)
            rows = ", ".join(
                f"{w.field}:{w.op}{'' if w.default_checked else '(unchecked)'}"
                for w in by_note.get(nid, [])
            ) or (plan.reasons.get(nid) or "no rows")
            print(f"{'PASS' if ok else 'FAIL'}  {name:<22} note {nid} — {want}; got: {rows}")
            failures += 0 if ok else 1
    for warning in plan.warnings:
        print(f"warning: {warning}")
    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
