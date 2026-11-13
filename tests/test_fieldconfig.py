"""Tests for fieldconfig.py — emptiness, junk, provenance, media refs."""

from __future__ import annotations

from mining_backfill.fieldconfig import (
    has_media_ref,
    image_files,
    is_blob_source,
    is_empty,
    is_junk_value,
    looks_yomitan_gloss,
    sound_files,
)


def test_is_empty_raw_rule():
    assert is_empty("")
    assert is_empty("   ")
    assert is_empty("\n ")
    # markup-only content occupies the field: never overwritten
    assert not is_empty("<hr>")
    assert not is_empty("<br>")
    assert not is_empty("&nbsp;")


def test_junk_separators_and_media_only():
    assert is_junk_value("<hr>")
    assert is_junk_value("<br><br>")
    assert is_junk_value(" [sound:a.webm] ")
    assert is_junk_value(" <img src=a.jpeg> ")


def test_junk_placeholders_and_attribution():
    assert is_junk_value("—")
    assert is_junk_value("???")
    assert is_junk_value("(大辞林 第四版)")  # attribution only
    assert not is_junk_value("(大辞林 第四版) しんさつ【診察】医者が病人を調べること。")


def test_junk_doubled_reading_pitch_artifact():
    assert is_junk_value("しんさつしつしんさつしつ", reading="しんさつしつ")
    assert is_junk_value("しんさつ", reading="しんさつ")
    assert not is_junk_value("しんさつしつ", reading="しんさつ")


def test_junk_definition_equal_to_expression():
    assert is_junk_value("診察", expression="診察")
    assert not is_junk_value("診察すること", expression="診察")


def test_yomitan_provenance_requires_gloss_text():
    # markup-only scaffolding is NOT provenance
    assert not looks_yomitan_gloss('.yomitan-glossary ul[data-sc-content="glossary"] > li')
    # attribution + real gloss text is
    assert looks_yomitan_gloss(
        "(大辞林 第四版) しんさつ【診察】医者が病人の体を調べること。"
        '.yomitan-glossary [data-dictionary="大辞林 第四版"]'
    )
    assert not looks_yomitan_gloss("plain text without markup")


def test_blob_source():
    assert is_blob_source(
        "asbplayerhttps://app.asbplayer.dev/?video=blob%3Ahttps%3A%2F%2Fapp.asbplayer.dev%2F4311f"
    )
    assert not is_blob_source("Dr. Rintaro Episode 6.mp4 (20m19s)")


def test_media_ref_extraction():
    v = ' [sound:asbp_x.webm] <img src="asbp_y.jpeg"> '
    assert sound_files(v) == ["asbp_x.webm"]
    assert image_files(v) == ["asbp_y.jpeg"]
    assert has_media_ref(v)
    assert not has_media_ref("plain")
