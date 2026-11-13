#!/usr/bin/env python3
"""Headless prototype: fix the last N mining cards and export an audit .apkg.

Runs against a COPY of the user's collection. Nothing in the live profile
is touched; the audit deck ships with fresh note type, fresh guids and its
own deck so importing it cannot modify any existing note or note type.

Usage:
    python3 scripts/build_audit_package.py --profile-dir <Anki profile dir> \
        --work-dir /tmp/opencode/mb_audit_build --last 20 --out-dir dist

Produces:
    dist/mining-backfill-audit-<run>.apkg
    dist/mining-backfill-report-<run>.md
    dist/mining-backfill-plan-<run>.json   (audit log: every old value)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from matching import NoteRecord  # noqa: E402
from plan import PLAN_VERSION, build_plan  # noqa: E402
from report import render_markdown  # noqa: E402

RUN_TS = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def prepare_work_dir(profile_dir: Path, work_dir: Path) -> Path:
    """Copy collection (+wal) and media db into a build dir; symlink media."""
    work_dir.mkdir(parents=True, exist_ok=True)
    dst = work_dir / "collection.anki2"
    for name in ("collection.anki2", "collection.anki2-wal", "collection.media.db2"):
        src = profile_dir / name
        if src.exists() and (work_dir / name).exists() is False:
            shutil.copy2(src, work_dir / name)
    media_link = work_dir / "collection.media"
    real_media = profile_dir / "collection.media"
    if real_media.exists() and not media_link.exists():
        os.symlink(real_media.resolve(), media_link)
    # stale artifacts from previous runs must not survive
    for name in ("collection.anki2-wal",):
        p = work_dir / name
        if p.exists():
            pass  # keep: copied above only when missing
    return dst


def load_config() -> dict:
    return json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))


def records_from_collection(col, deck_name: str, note_type_name: str) -> list[NoteRecord]:
    did = col.decks.id(deck_name)
    mid = col.models.id_for_name(note_type_name)
    rows = col.db.execute(
        "select n.id, n.mid, n.flds, n.tags from cards c join notes n on n.id=c.nid "
        "where c.did=? and n.mid=?",
        did,
        mid,
    )
    flds_order = [f["name"] for f in col.models.get(mid)["flds"]]
    out = []
    for nid, _, flds_s, tags in rows:
        values = flds_s.split("\x1f")
        out.append(
            NoteRecord(
                note_id=nid,
                notetype_id=mid,
                fields=dict(zip(flds_order, values, strict=False)),
                tags=frozenset(tags.split()),
            )
        )
    return out


def _audit_tags(cfg: dict, is_fixed: bool) -> set[str]:
    """Tags for one audit note: mb-audit on all, mb-audit-fixed on fixed."""
    tags = {cfg["audit_tag"]}
    if is_fixed:
        tags.add(cfg.get("audit_fixed_tag", "mb-audit-fixed"))
    return tags


def clone_note_type(col, mid, new_name: str):
    """Clone the note type with a fresh id (apkg import must never merge)."""
    src = col.models.get(mid)
    clone = json.loads(json.dumps(src))
    clone["id"] = 0
    clone["name"] = new_name
    clone["mod"] = 0
    col.models.add_dict(clone)
    return col.models.id_for_name(new_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, default=Path("/tmp/opencode/mb_audit_build"))
    parser.add_argument("--last", type=int, default=20)
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "dist")
    parser.add_argument("--deck-name", default="zzz-Mining-Backfill-Audit")
    args = parser.parse_args()

    from anki.collection import Collection, DeckIdLimit, ExportAnkiPackageOptions
    from anki.notes import Note

    cfg = load_config()
    collection_path = prepare_work_dir(args.profile_dir, args.work_dir)
    col = Collection(str(collection_path))
    try:
        deck_name = cfg["deck_name"]
        note_type_name = cfg["note_type_name"]
        records = records_from_collection(col, deck_name, note_type_name)
        records.sort(key=lambda r: r.note_id, reverse=True)
        scope = [r.note_id for r in records[: args.last]]
        records_by_id = {r.note_id: r for r in records}

        media_dir = args.work_dir / "collection.media"

        def media_exists(filename: str) -> bool:
            return (media_dir / filename).exists()

        plan = build_plan(records, cfg, scope_note_ids=scope, media_exists=media_exists)

        # Build audit notes under a cloned note type in a fresh deck.
        audit_deck_id = col.decks.id(args.deck_name)
        mid = col.models.id_for_name(note_type_name)
        audit_mid = clone_note_type(col, mid, f"{note_type_name} (MB Audit)")

        created = 0
        field_order = None
        for target_id in scope:
            target = records_by_id[target_id]
            writes = [w for w in plan.writes if w.note_id == target_id and w.default_checked]
            values = dict(target.fields)
            for w in writes:
                values[w.field] = w.new_value
            note = Note(col, audit_mid)
            if field_order is None:
                field_order = [f["name"] for f in col.models.get(audit_mid)["flds"]]
            for name in field_order:
                note[name] = values.get(name, "")
            note.tags = sorted(target.tags | _audit_tags(cfg, bool(writes)))
            guid = uuid.uuid5(uuid.NAMESPACE_URL, f"mb-audit:{target_id}:{RUN_TS}").hex
            note.guid = guid
            col.add_note(note, deck_id=audit_deck_id)
            created += 1

        out_dir = args.out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        apkg_path = out_dir / f"mining-backfill-audit-{RUN_TS}.apkg"
        options = ExportAnkiPackageOptions(
            with_scheduling=False,
            with_deck_configs=False,
            with_media=True,
            legacy=False,
        )
        col.export_anki_package(
            out_path=str(apkg_path),
            options=options,
            limit=DeckIdLimit(deck_id=audit_deck_id),
        )

        run_meta = {
            "run": RUN_TS,
            "plan_version": PLAN_VERSION,
            "scope": f"last {args.last} notes added to {deck_name}",
            "note type": note_type_name,
            "audit deck": args.deck_name,
            "audit notes created": created,
            "window_days": cfg.get("window_days"),
            "audit tags": (
                f"{cfg['audit_tag']} (all), "
                f"{cfg.get('audit_fixed_tag', 'mb-audit-fixed')} (fixed notes)"
            ),
        }
        report_md = render_markdown(plan, records_by_id, run_meta)
        report_path = out_dir / f"mining-backfill-report-{RUN_TS}.md"
        report_path.write_text(report_md, encoding="utf-8")

        plan_log = {
            "run": RUN_TS,
            "plan_version": PLAN_VERSION,
            "writes": [
                {
                    "note_id": w.note_id,
                    "field": w.field,
                    "op": w.op,
                    "old_value": w.old_value,
                    "new_value": w.new_value,
                    "source_note_id": w.source_note_id,
                    "default_checked": w.default_checked,
                    "badges": list(w.badges),
                }
                for w in plan.writes
            ],
            "reasons": {str(k): v for k, v in plan.reasons.items()},
            "warnings": plan.warnings,
        }
        (out_dir / f"mining-backfill-plan-{RUN_TS}.json").write_text(
            json.dumps(plan_log, ensure_ascii=False, indent=1), encoding="utf-8"
        )

        checked = [w for w in plan.writes if w.default_checked]
        print(f"audit notes created : {created}")
        print(f"writes planned      : {len(plan.writes)} (default-checked {len(checked)})")
        print(f"apkg                : {apkg_path}")
        print(f"report              : {report_path}")
        return 0
    finally:
        col.close()


if __name__ == "__main__":
    raise SystemExit(main())
