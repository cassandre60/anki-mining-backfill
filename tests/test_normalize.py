"""Tests for normalize.py"""

from __future__ import annotations

from mining_fixer.normalize import (
    REPAIR_RULES,
    kana_fold,
    norm_reading,
    norm_sentence,
    norm_sentence_match,
    reading_from_furigana,
    repair_sentence,
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


# --- repair_sentence (bulk-fix dimension 2) ---------------------------------
#
# Fixtures are real Sentence values from the configured deck (census
# 2026-11-15): multi-line subtitle dumps joined with <br>, line-tail arrows,
# ideographic beat spaces, bold markup in the middle of it all.

ALL_RULES = REPAIR_RULES


def test_repair_strips_line_tail_arrows():
    text = "あしたの朝刊の見出しは<br>こうニャ！➡"
    new, applied = repair_sentence(text, ALL_RULES)
    assert applied == ("strip-arrows",)
    assert new == "あしたの朝刊の見出しは<br>こうニャ！"


def test_repair_keeps_the_line_breaks_and_spacing_it_does_not_ship():
    # Owner decision 2026-11-15: <br> line breaks and spacing are the
    # sentence's pause structure and stay exactly as mined — see BULK_FIX.md.
    text = "俺は弱くて 誰も助けらんなかった<br>それどころか 伏黒を殺し<b>かけた</b>"
    assert repair_sentence(text, ALL_RULES) == (text, ())


def test_repair_keeps_midline_arrows():
    # f:X→Y is mathematical notation, not a continuation marker.
    text = "任意の<br>xεXに対してただひとつのyεYが対応しているとき，関数f:X→Yが定まったといい，"
    new, applied = repair_sentence(text, ALL_RULES)
    assert applied == ()
    assert new == text


def test_repair_keeps_bold_markup_around_a_tail_arrow():
    text = "俺は弱くて 誰も助けらんなかった<br>それどころか 伏黒を殺し<b>かけた</b>➡"
    new, applied = repair_sentence(text, ALL_RULES)
    assert applied == ("strip-arrows",)
    assert new == "俺は弱くて 誰も助けらんなかった<br>それどころか 伏黒を殺し<b>かけた</b>"


def test_repair_br_variants_and_vs16_arrow():
    new, applied = repair_sentence("一つ目<br/>二つ目<BR />三つ目➡", ALL_RULES)
    assert applied == ("strip-arrows",)
    assert new == "一つ目<br/>二つ目<BR />三つ目"
    new, applied = repair_sentence("一つ目➡️<br>二つ目", ALL_RULES)  # arrow + VS16
    assert applied == ("strip-arrows",)
    assert new == "一つ目<br>二つ目"


def test_repair_is_idempotent():
    texts = [
        "あしたの朝刊の見出しは<br>こうニャ！➡",
        "「絶」\u3000念オーラを完全に絶つ技<br>自身の気配を消したり<br><b>疲労回復</b>に効果がある➡",
    ]
    for text in texts:
        once, _ = repair_sentence(text, ALL_RULES)
        twice, applied_twice = repair_sentence(once, ALL_RULES)
        assert twice == once, text
        assert applied_twice == (), text


def test_repair_noop_on_clean_or_empty_text():
    assert repair_sentence("きれいな文。", ALL_RULES) == ("きれいな文。", ())
    assert repair_sentence("", ALL_RULES) == ("", ())
    # Whitespace-only values are left exactly as they are (is_empty gate).
    assert repair_sentence("   ", ALL_RULES) == ("   ", ())


def test_repair_unknown_rules_are_ignored():
    new, applied = repair_sentence("前➡<br>後", ("strip-arrows", "nonsense"))
    assert applied == ("strip-arrows",)
    assert new == "前<br>後"
