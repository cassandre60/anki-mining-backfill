#!/usr/bin/env python3
"""Restore cards corrupted by the buggy moment-group / audio runs (QUALITY Q-D16/Q-D17).

At midnight (run-20261117-002025) a buggy moment-group rule with a 20-second
tolerance lumped three distinct scenes (14m50s, 15m01s, 15m20s) into one and
overwrote the sentences of 自負, 自閉症, and 予て with neighbouring scene text.
Then at 12:40 (run-20261117-124026) a buggy audio-majority rule overwrote the
audio of 自負, 自閉症, and 類い希 with the 15m20s clip.

This script restores those four cards to their true, pre-corruption state:
- 自負 (1794831660430): 15m01s sentence with bold 自負, audio 901356, pic 901556
- 自閉症 (1794831715530): 15m01s sentence with bold 自閉症, audio 901356, pic 901556
- 予て (1794831385615): 14m50s sentence with bold かねて, audio 889878, pic 890078
- 類い希 (1794831801529): original 40.7s audio 901356_7gwwhbhy.webm

Usage:
    python3 scripts/restore_corrupted_cards.py --profile-dir "<profile>" [--apply]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

RESTORATIONS = {
    1794831385615: {
        "name": "予て",
        "fields": {
            "Sentence": (
                "(街子) 蓮見先生<br>ありがとうございました｡<br>それでは次に<br>"
                "宮川教授 お願いいたします｡<br>本日は 皆さんに<br>私の研究に関しての<br>"
                "ご協力のお願いを<br>させていただきたいと思います｡<br>私は <b>かねて</b>より<br>"
                "精神疾患と脳との関係について<br>研究してまいりました｡"
            ),
            "Sentence (furigana)": (
                "( 街[がい] 子[こ]) 蓮見[はすみ] 先生[せんせい]<br>"
                "ありがとうございました｡<br>それでは 次[つぎ]に<br>"
                " 宮川[みやがわ] 教授[きょうじゅ]お 願[ねが]いいたします｡<br>"
                " 本日[ほんじつ]は 皆[みな]さんに<br>"
                " 私[わたし]の 研究[けんきゅう]に 関[かん]しての<br>"
                "ご 協力[きょうりょく]のお 願[ねが]いを<br>"
                "させていただきたいと 思[おも]います｡<br>"
                " 私[わたし]は <b>かねて</b>より<br>"
                " 精神疾患[せいしんしっかん]と 脳[のう]との 関係[かんけい]について<br>"
                " 研究[けんきゅう]してまいりました｡"
            ),
            "Sentence Audio": " [sound:asbp_dr._rintaro_episode_7__1_889878_zd91gj01.webm] ",
            "Picture": '<img src="asbp_dr._rintaro_episode_7__1_890078_irfgmztv.jpeg">',
            "Source": "Dr. Rintaro Episode 7 (1).mp4 (14m50s)",
        },
    },
    1794831660430: {
        "name": "自負",
        "fields": {
            "Sentence": (
                "本日は 皆さんに<br>私の研究に関しての<br>ご協力のお願いを<br>"
                "させていただきたいと思います｡<br>私は かねてより<br>"
                "精神疾患と脳との関係について<br>研究してまいりました｡<br>中でも<br>"
                "自閉症と脳機能については<br>エキスパートであると<br><b>自負</b>しております｡"
            ),
            "Sentence (furigana)": (
                "本日[ほんじつ]は 皆[みな]さんに<br>"
                " 私[わたし]の 研究[けんきゅう]に 関[かん]しての<br>"
                "ご 協力[きょうりょく]のお 願[ねが]いを<br>"
                "させていただきたいと 思[おも]います｡<br>"
                " 私[わたし]はかねてより<br>"
                " 精神疾患[せいしんしっかん]と 脳[のう]との 関係[かんけい]について<br>"
                " 研究[けんきゅう]してまいりました｡<br> 中[ちゅう]でも<br>"
                " 自閉症[じへいしょう]と 脳[のう] 機能[きのう]については<br>"
                "エキスパートであると<br>"
                " <b>自負[じふ]</b>しております｡"
            ),
            "Sentence Audio": " [sound:asbp_dr._rintaro_episode_7__1_901356_x830iyzy.webm] ",
            "Picture": '<img src="asbp_dr._rintaro_episode_7__1_901556_phi6krts.jpeg">',
            "Source": "Dr. Rintaro Episode 7 (1).mp4 (15m01s)",
        },
    },
    1794831715530: {
        "name": "自閉症",
        "fields": {
            "Sentence": (
                "本日は 皆さんに<br>私の研究に関しての<br>ご協力のお願いを<br>"
                "させていただきたいと思います｡<br>私は かねてより<br>"
                "精神疾患と脳との関係について<br>研究してまいりました｡<br>中でも<br>"
                "<b>自閉症</b>と脳機能については<br>エキスパートであると<br>自負しております｡"
            ),
            "Sentence (furigana)": (
                "本日[ほんじつ]は 皆[みな]さんに<br>"
                " 私[わたし]の 研究[けんきゅう]に 関[かん]しての<br>"
                "ご 協力[きょうりょく]のお 願[ねが]いを<br>"
                "させていただきたいと 思[おも]います｡<br>"
                " 私[わたし]はかねてより<br>"
                " 精神疾患[せいしんしっかん]と 脳[のう]との 関係[かんけい]について<br>"
                " 研究[けんきゅう]してまいりました｡<br> 中[ちゅう]でも<br>"
                " <b>自閉症[じへいしょう]</b>と 脳[のう] 機能[きのう]については<br>"
                "エキスパートであると<br>"
                " 自負[じふ]しております｡"
            ),
            "Sentence Audio": " [sound:asbp_dr._rintaro_episode_7__1_901356_x830iyzy.webm] ",
            "Picture": '<img src="asbp_dr._rintaro_episode_7__1_901556_phi6krts.jpeg">',
            "Source": "Dr. Rintaro Episode 7 (1).mp4 (15m01s)",
        },
    },
    1794831801529: {
        "name": "類い希",
        "fields": {
            "Sentence Audio": " [sound:asbp_dr._rintaro_episode_7__1_901356_7gwwhbhy.webm] ",
            "Source": "Dr. Rintaro Episode 7 (1).mp4 (15m01s)",
        },
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-dir", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="write to the collection")
    args = parser.parse_args()

    from anki.collection import Collection

    col_path = args.profile_dir / "collection.anki2"
    if not col_path.is_file():
        print(f"Error: collection not found at {col_path}", file=sys.stderr)
        return 1

    col = Collection(str(col_path))
    try:
        log_records: list[dict] = []
        for nid, info in RESTORATIONS.items():
            try:
                note = col.get_note(nid)
            except Exception as e:
                print(f"Note {nid} ({info['name']}): could not load: {e}")
                continue

            current_fields = dict(note.items())
            changes = []
            for field_name, target_value in info["fields"].items():
                cur = current_fields.get(field_name, "")
                if cur.strip() != target_value.strip():
                    changes.append((field_name, cur, target_value))

            print(f"\nNote {nid} ({info['name']}): {len(changes)} field(s) to restore")
            for field_name, cur, target_value in changes:
                print(f"  {field_name:20}: {cur[:35]!r} -> {target_value[:35]!r}")

            if changes and args.apply:
                for field_name, _, target_value in changes:
                    note[field_name] = target_value
                col.update_note(note)
                log_records.append(
                    {
                        "note_id": nid,
                        "fields": [{"field": f, "prior": c, "applied": t} for f, c, t in changes],
                        "tags_applied": list(note.tags),
                        "tags_prior": list(note.tags),
                    }
                )

        if args.apply and log_records:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            log_dir = args.profile_dir / "mining_fixer" / "undo"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"run-{stamp}.json"
            log_data = {
                "version": 1,
                "kind": "restore-corrupted-cards",
                "timestamp": stamp,
                "records": log_records,
            }
            log_file.write_text(
                json.dumps(log_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"\nRestored {len(log_records)} note(s). Undo log written to:\n  {log_file}")
        elif not args.apply:
            print("\nDry-run complete. Run with --apply to write changes.")
        return 0
    finally:
        col.close()


if __name__ == "__main__":
    raise SystemExit(main())
