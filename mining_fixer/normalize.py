"""Pure text normalization for Mining Fixer matching keys.

No anki/aqt imports: this module must stay importable by the headless
prototype and by tests without Anki installed.

Normalization produces *matching keys* only. Values copied into notes are
never normalized.

Field formats observed in the real collection:

- ``Sentence``: subtitle text with optional speaker/stage tags in square or
  round brackets (``[TEL](受付)``), the continuation marker ``➡``, HTML
  markup, sound tags and images.
- ``furigana``: Yomitan-style per-kanji ruby written inline as ``漢字[かんじ]``
  (base form outside, reading inside brackets), with kana/okurigana
  interleaved verbatim.
- ``reading``: plain kana (hiragana or katakana).
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Iterable

__all__ = [
    "REPAIR_RULES",
    "norm_sentence",
    "norm_sentence_match",
    "norm_word_text",
    "norm_reading",
    "reading_from_furigana",
    "repair_sentence",
    "furigana_base_matches",
    "word_key",
    "strip_renderable",
    "kana_fold",
]

# --- removals ---------------------------------------------------------------

_SOUND_RE = re.compile(r"\[sound:[^\]]*\]", re.IGNORECASE)
_ANKI_REF_RE = re.compile(r"\[anki:[^\]]*\]", re.IGNORECASE)
_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
# Zero-width/format characters that survive NFKC (CJK subtitle dumps carry
# them): ZWSP, BOM, ZWNJ, ZWJ, directional marks, variation selectors.
_INVISIBLE_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff\u200e\u200f\ufe00-\ufe0f]")

# --- punctuation folding ----------------------------------------------------
# Map CJK and fullwidth punctuation onto canonical ASCII forms so that
# subtitle dumps that disagree on fullwidth/halfwidth style still match.
_PUNCT_TABLE = {
    "。": ".",
    "．": ".",
    ".": ".",
    "、": ",",
    "，": ",",
    ",": ",",
    "！": "!",
    "!": "!",
    "？": "?",
    "?": "?",
    "：": ":",
    ":": ":",
    "；": ";",
    ";": ";",
}

_PUNCT_TRANSLATION = str.maketrans(_PUNCT_TABLE)

# --- trailing continuation / truncation markers -----------------------------
# Subtitle dumps end lines with a continuation arrow (➡), ellipsis or
# tildes. Strip them at the tail of a matching key so a fragment whose dump
# dropped the marker still matches the parent scene line.
_TRAILING_MARKS_RE = re.compile(r"(?:[\u27a1\u21d2\u2192\u2026\uff5e~\ufe0f\s])+$")

_WHITESPACE_RE = re.compile(r"\s+")
_LATIN_RE = re.compile(r"[A-Za-z0-9]")

# Sentence-internal brackets that are load-bearing for scene identity:
# stage directions and speaker tags. Kept verbatim (after NFKC, which
# decomposes fullwidth round brackets ()() but leaves 【】 and ⦅⦆ intact).
#
# NOT removed anywhere: scene brackets, quotes, ➡, 。、 (only folded to their
# canonical forms).


def _strip_markup(text: str) -> str:
    """Remove sound tags, images, HTML tags and invisible characters."""
    text = _SOUND_RE.sub("", text)
    text = _ANKI_REF_RE.sub("", text)
    text = _IMG_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE_RE.sub("", text)
    return text


_BRACKET_MASK_RE = re.compile(r"\[[^\[\]]*\]|\([^()]*\)|【[^【】]*】")


def _collapse_whitespace(text: str) -> str:
    """Conditional whitespace rule.

    Lines containing Latin letters or digits keep a single space between
    runs (so ``a b`` never matches ``ab``); pure CJK lines drop whitespace
    entirely (Japanese has no inter-word spaces). Bracket payloads
    (``[TEL]``, ``(受付)``) are masked before the Latin test so speaker
    tags on Japanese lines do not flip the rule.
    """
    probe = _BRACKET_MASK_RE.sub("", text)
    if _LATIN_RE.search(probe):
        return _WHITESPACE_RE.sub(" ", text).strip()
    return _WHITESPACE_RE.sub("", text)


def norm_sentence(text: str) -> str:
    """Normalization used for the scene-containment key (brackets kept)."""
    return _collapse_whitespace(_strip_markup(text).translate(_PUNCT_TRANSLATION))


def norm_sentence_match(text: str) -> str:
    """Like :func:`norm_sentence`, plus trailing continuation-marker strip."""
    return _TRAILING_MARKS_RE.sub("", norm_sentence(text))


def norm_word_text(text: str) -> str:
    """Normalization for the word-identity key (Expression)."""
    return norm_sentence(text)


def strip_renderable(text: str) -> str:
    """Plain-text rendering of a field value (for junk detection/preview)."""
    return _collapse_whitespace(_strip_markup(text).translate(_PUNCT_TRANSLATION))


def kana_fold(text: str) -> str:
    """Katakana (U+30A1-U+30F6) to hiragana by code-point offset.

    Does not fold the long-vowel mark (ー) or dakuten: folding those merges
    distinct words (おばさん/おばあさん, か/が).
    """
    return "".join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in text)


def norm_reading(text: str) -> str:
    """Normalization for readings: markup strip, NFKC, katakana -> hiragana."""
    return kana_fold(_collapse_whitespace(_strip_markup(text).translate(_PUNCT_TRANSLATION)))


# --- furigana ---------------------------------------------------------------

_KANJI_RE = re.compile(r"[㐀-\u4dbf\u4e00-\u9fff\u3005\u3006]")
_FURIGANA_BRACKET_RE = re.compile(r"\[([^\[\]]*)\]")
_FURIGANA_ANNOTATION_RE = re.compile(r"\[[^\[\]]*\]")


def reading_from_furigana(furigana: str) -> str | None:
    """Derive a plain reading from Yomitan-style inline ruby.

    Walks the string left-to-right: kanji runs disappear (their reading is
    the following bracket payload), brackets dissolve into their payload,
    bare kana survives. ``死[し]に 至[いた]る`` -> ``しにいたる``.

    Returns ``None`` when the markup is malformed (unbalanced brackets) or
    the payload contains characters a reading cannot have (kanji or Latin
    beyond the long-vowel mark, the ・ separator and iteration marks).
    """
    if not furigana.strip():
        return None
    if furigana.count("[") != furigana.count("]"):
        return None
    out: list[str] = []
    pos = 0
    for match in _FURIGANA_BRACKET_RE.finditer(furigana):
        base = furigana[pos : match.start()]
        out.append(_KANJI_RE.sub("", base))
        out.append(match.group(1))
        pos = match.end()
    out.append(_KANJI_RE.sub("", furigana[pos:]))
    reading = "".join(out)
    reading = kana_fold(
        _WHITESPACE_RE.sub("", _strip_markup(reading).translate(_PUNCT_TRANSLATION))
    )
    if not reading:
        return None
    # A reading may contain kana, the long-vowel mark, the middle dot and
    # iteration marks only.
    if not re.fullmatch(r"[ぁ-ゖー・ヽヾ]+", reading):
        return None
    return reading


def word_key(expression: str, reading: str, furigana: str = "") -> tuple[str, str] | None:
    """Word-identity key: (normalized expression, normalized reading).

    The reading is normalized; when the reading field is blank it is
    derived from the furigana field (``None`` on failure). Returns ``None``
    when no usable expression exists (empty or sentence-length values are
    the caller's decision).
    """
    expr = norm_word_text(expression)
    if not expr:
        return None
    read = norm_reading(reading)
    if not read:
        read = reading_from_furigana(furigana) or ""
        read = kana_fold(read)
    return (expr, read)


def furigana_base_matches(generated: str, sentence: str) -> bool:
    """True when a generated furigana value carries exactly the sentence.

    The deck's ruby convention is per-kanji bracket annotations
    (``漢字[かんじ]``); Japanese Support's reading engine emits the same
    shape. The guard: the generated value's base text — bracket readings
    stripped, markup removed, whitespace squeezed — must equal the
    sentence's plain text (square-bracket speaker tags such as ``[TEL]``
    are stripped on the sentence side by the same convention). Unbalanced
    brackets mean the engine mangled the text; that is a mismatch too.
    Pure.
    """
    if (generated or "").count("[") != (generated or "").count("]"):
        return False
    base = _FURIGANA_ANNOTATION_RE.sub("", generated or "")
    plain_sentence = _FURIGANA_ANNOTATION_RE.sub("", sentence or "")
    return _WHITESPACE_RE.sub("", strip_renderable(base)) == _WHITESPACE_RE.sub(
        "", strip_renderable(plain_sentence)
    )


# --- sentence repair (bulk-fix dimension 2: subtitle noise) -----------------
#
# The configured deck's Sentence fields are subtitle dumps: a continuation
# arrow (➡ / → / ⇒) at a line tail marks "the line continues". The census of
# 2026-11-15 found such arrows in 0.4% of the deck's 17,589 notes (<br> in
# 72.1%, padding runs in 0.3%). The owner decision of 2026-11-15 keeps the
# shipped scope to the arrows: `<br>` line breaks and spacing are the
# sentence's pause structure and stay exactly as mined — the future
# direction is deriving the breaks from the audio itself (BULK_FIX.md,
# "Audio-aligned line breaks"). Repair rewrites ONLY the noise it ships;
# bold markup, sound tags, images, brackets and every spoken character pass
# through untouched.

REPAIR_RULES = ("strip-arrows",)

# A continuation arrow only ever marks "the line continues", so it is
# stripped only at a line tail — immediately before a <br>, a newline or the
# end of the value. The same glyphs in mid-line positions are real notation
# (関数f:X→Y) and are never touched.
_ARROW_TAIL_RE = re.compile(
    "[\u2192\u21d2\u27a1]+\ufe0f?(?=[ \t]*(?:<br\\s*/?>|\n|$))", re.IGNORECASE
)


def repair_sentence(text: str, rules: Iterable[str]) -> tuple[str, tuple[str, ...]]:
    """Repair subtitle noise in a ``Sentence`` value (pure).

    Config-driven rule list. The shipped rule set is exactly:

    - ``strip-arrows`` — remove continuation arrows only at line tails.

    ``<br>`` line breaks and spacing are deliberately NOT rewritten (owner
    decision 2026-11-15). Unknown rule names are ignored here and warned
    about by the planner. Returns ``(new_text, applied_rules)``;
    ``applied_rules`` is empty when nothing changed. The transformation is
    idempotent.
    """
    if not (text or "").strip():
        return text, ()
    wanted = tuple(rules)
    applied: list[str] = []
    s = text
    if "strip-arrows" in wanted:
        stripped = _ARROW_TAIL_RE.sub("", s)
        if stripped != s:
            applied.append("strip-arrows")
            s = stripped
    if not applied:
        return text, ()
    return s, tuple(applied)
