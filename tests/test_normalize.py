"""Tests for normalize.py"""

from __future__ import annotations

from normalize import (
    kana_fold,
    norm_reading,
    norm_sentence,
    norm_sentence_match,
    reading_from_furigana,
    word_key,
)


def test_sound_tags_and_images_removed():
    assert norm_sentence("[sound:a.webm] はい <img src=x.jpg> そうです") == "はいそうです"


def test_html_and_entities():
    assert norm_sentence("<br>ことば&nbsp;のみ</div>") == "ことばのみ"


def test_whitespace_removed_for_cjk():
    assert norm_sentence("先生は今 診察中ですので") == "先生は今診察中ですので"


def test_latin_whitespace_collapsed_not_removed():
    assert norm_sentence("a b") == "a b"
    assert norm_sentence("a  b") == "a b"


def test_nfkc_halfwidth_katakana():
    assert norm_sentence("[ｲﾔﾎﾝ] たとえ") == "[イヤホン]たとえ"


def test_nfkc_fullwidth_round_brackets_decompose():
    assert norm_sentence("（受付）") == "(受付)"


def test_cjk_brackets_kept():
    assert norm_sentence("【怒り】") == "【怒り】"
    assert norm_sentence("⦅夢⦆") == "⦅夢⦆"


def test_punctuation_folded():
    assert norm_sentence("はい｡そうです。") == "はい.そうです."


def test_invisible_characters_removed():
    assert norm_sentence("こと\u200bば\ufeffです") == "ことばです"
    assert norm_sentence("なに\u27a1\ufe0f") == "なに➡"


def test_trailing_continuation_markers_stripped_for_matching():
    assert norm_sentence_match("先生は今 診察中ですので➡") == "先生は今診察中ですので"
    assert norm_sentence_match("まだ おかあさんのオッパイが➡") == "まだおかあさんのオッパイが"
    # interior markers survive: only the tail is stripped
    assert norm_sentence_match("➡はい") == "➡はい"


def test_kana_fold():
    assert kana_fold("シンサツ") == "しんさつ"
    assert kana_fold("ヴィルス") == "ゔぃるす"
    assert kana_fold("ジョーカー") == "じょーかー"  # long vowel kept


def test_norm_reading():
    assert norm_reading("シンサツ") == "しんさつ"
    assert norm_reading("しきゅう") == "しきゅう"


def test_reading_from_furigana_interleaved():
    # the naive "concatenate payloads" bug would give しいた
    assert reading_from_furigana("死[し]に 至[いた]る") == "しにいたる"
    assert reading_from_furigana("先[ま]ず") == "まず"
    assert reading_from_furigana("耳[みみ]を 傾[かたむ]ける") == "みみをかたむける"
    assert reading_from_furigana("大人[おとな]") == "おとな"
    assert reading_from_furigana("人々[ひとびと]") == "ひとびと"
    assert reading_from_furigana("診察[しんさつ]") == "しんさつ"


def test_reading_from_furigana_malformed():
    assert reading_from_furigana("[かんじ") is None
    assert reading_from_furigana("漢字[かん") is None
    assert reading_from_furigana("") is None


def test_word_key():
    assert word_key("診察", "しんさつ") == ("診察", "しんさつ")
    assert word_key("診察", "", "診察[しんさつ]") == ("診察", "しんさつ")
    assert word_key("", "しんさつ") is None
