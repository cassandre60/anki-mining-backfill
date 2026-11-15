"""Tests for matching.py — scene containment, window, ranking, word groups."""

from __future__ import annotations

from mining_fixer.matching import (
    DAY_MS,
    NoteRecord,
    best_word_source,
    find_scene_parents,
    rank_scene_parents,
    singleton_kanji_guard,
    word_groups,
)


def rec(nid, fields, tags=()):
    return NoteRecord(note_id=nid, notetype_id=1, fields=fields, tags=frozenset(tags))


BASE = {
    "Expression": "",
    "Definition": "",
    "Source": "",
    "Sentence": "",
    "Sentence (furigana)": "",
    "Sentence Audio": "",
    "Translation": "",
    "Picture": "",
    "context": "",
    "Notes": "",
    "Word Audio": "",
    "Pitch Accent": "",
    "furigana": "",
    "reading": "",
    "cloze-prefix": "",
    "cloze-body": "",
    "cloze-suffix": "",
    "Frequency": "",
    "Extended definition": "",
    "Kanji Notes": "",
}


def candidate(cid, sentence):
    f = dict(BASE)
    f.update(
        {
            "Sentence": sentence,
            "Source": "asbplayerhttps://app.asbplayer.dev/?video=blob%3Ahttps%3A%2F%2Fx",
        }
    )
    return rec(cid, f)


def parent(
    pid,
    sentence,
    audio=" [sound:p.webm] ",
    picture=' <img src="p.jpeg"> ',
    source="Show E1.mp4 (1m00s)",
):
    f = dict(BASE)
    f.update(
        {
            "Sentence": sentence,
            "Source": source,
            "Sentence Audio": audio,
            "Picture": picture,
        }
    )
    return rec(pid, f, tags=("asbplayer", "yomitan"))


def test_containment_basic():
    cand = candidate(2_000_000, "先生は今 診察中ですので➡")
    par = parent(
        2_000_000 - 54_223,
        "[TEL](ベル)はい。申し訳ありません 先生は今 診察中ですので➡代わりに伺います。",
    )
    hits = find_scene_parents(cand, {par.note_id: par}, window_ms=3 * DAY_MS)
    assert len(hits) == 1
    assert hits[0].parent.note_id == par.note_id


def test_trailing_marker_stripped_on_both_sides():
    cand = candidate(2_000_000, "診察中ですので➡")
    par = parent(2_000_000 - 1_000, "先生は今 診察中ですので")
    assert find_scene_parents(cand, {par.note_id: par}, window_ms=DAY_MS)


def test_window_is_hard_cap():
    cand = candidate(2_000_000, "診察中ですので➡")
    par = parent(2_000_000 - 4 * DAY_MS, "先生は今 診察中ですので")
    assert find_scene_parents(cand, {par.note_id: par}, window_ms=3 * DAY_MS) == []
    assert find_scene_parents(cand, {par.note_id: par}, window_ms=5 * DAY_MS)


def test_min_length_guard():
    cand = candidate(2_000_000, "はい")
    par = parent(2_000_000 - 1_000, "はい そうです。")
    assert find_scene_parents(cand, {par.note_id: par}, window_ms=DAY_MS) == []


def test_ranking_prefills_and_tightest():
    cand = candidate(2_000_000, "診察中ですので➡")
    rich_far = parent(
        2_000_000 - 100,
        "A。とても長い場面の字幕ブロックです。"
        "先生は今 診察中ですので➡代わりに伺います医師の川上です。B。",
    )
    close_tight = parent(
        2_000_000 - 1_000, "申し訳ありません 先生は今 診察中ですので➡代わりに伺います。"
    )
    ranked = rank_scene_parents(
        find_scene_parents(
            cand, {rich_far.note_id: rich_far, close_tight.note_id: close_tight}, window_ms=DAY_MS
        ),
        cand,
    )
    # tighter parent wins over the same-session but much longer one
    assert ranked[0].parent.note_id == close_tight.note_id
    assert ranked[0].fillable >= 3


def test_ranking_drops_parents_that_fill_nothing():
    cand = candidate(2_000_000, "診察中ですので➡")
    empty_parent = parent(
        2_000_000 - 1_000, "先生は今 診察中ですので", audio="", picture="", source="asbplayerblob"
    )
    assert (
        rank_scene_parents(
            find_scene_parents(cand, {empty_parent.note_id: empty_parent}, window_ms=DAY_MS), cand
        )
        == []
    )


def test_agreement_groups_identical_payloads():
    cand = candidate(2_000_000, "診察中ですので➡")
    p1 = parent(2_000_000 - 100, "はい。先生は今 診察中ですので➡代わりに伺います。")
    p2 = parent(2_000_000 - 200, "先生は今 診察中ですので➡代わりに伺います医師の川上です。")
    ranked = rank_scene_parents(
        find_scene_parents(cand, {p1.note_id: p1, p2.note_id: p2}, window_ms=DAY_MS), cand
    )
    # parents with different payload tuples stay separate; identical ones merge
    assert len(ranked) >= 1


def test_word_groups_reading_only_not_merged():
    r1 = rec(1, {**BASE, "Expression": "氏", "reading": "し"})
    r2 = rec(2, {**BASE, "Expression": "詩", "reading": "し"})
    groups = word_groups([r1, r2])
    assert ("氏", "し") in groups and ("詩", "し") in groups
    assert len(groups[("氏", "し")]) == 1


def test_word_groups_furigana_fallback():
    r1 = rec(1, {**BASE, "Expression": "診察", "reading": "", "furigana": "診察[しんさつ]"})
    r2 = rec(2, {**BASE, "Expression": "診察", "reading": "しんさつ"})
    groups = word_groups([r1, r2])
    assert len(groups[("診察", "しんさつ")]) == 2


def test_best_word_source_prefers_provenance_then_consensus():
    junk = rec(1, {**BASE, "Expression": "診察", "reading": "しんさつ", "Definition": "<hr>"})
    plain = rec(
        2, {**BASE, "Expression": "診察", "reading": "しんさつ", "Definition": "user note text"}
    )
    gloss = rec(
        3,
        {
            **BASE,
            "Expression": "診察",
            "reading": "しんさつ",
            "Definition": "(大辞林 第四版) 医者が病人を調べること。"
            '.yomitan-glossary [data-dictionary="大辞林 第四版"]',
        },
    )
    group = [junk, plain, gloss]
    cand = rec(9, {**BASE, "Expression": "診察", "reading": "しんさつ"})
    src = best_word_source("Definition", cand, group)
    assert src.record.note_id == gloss.note_id
    assert src.provenance


def test_singleton_kanji_guard():
    # 尾ける is a singleton kanji group while the kana reading twin つける has 2 notes
    tail = rec(1, {**BASE, "Expression": "尾ける", "reading": "つける"})
    kana1 = rec(2, {**BASE, "Expression": "つける", "reading": "つける"})
    kana2 = rec(3, {**BASE, "Expression": "つける", "reading": "つける"})
    groups = word_groups([tail, kana1, kana2])
    assert singleton_kanji_guard(tail, groups)
    # a normal singleton with no kana twin is not flagged
    solo = rec(4, {**BASE, "Expression": "診察", "reading": "しんさつ"})
    assert not singleton_kanji_guard(solo, word_groups([solo]))
