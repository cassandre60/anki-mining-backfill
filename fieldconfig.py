"""Field classification, emptiness, junk detection and provenance.

Pure module: no anki/aqt imports.

The emptiness rule is the safety backbone of the add-on: a field counts as
occupied if its *raw* string has any non-whitespace content. Markup-only
content such as ``<hr>`` therefore occupies a field and is never
overwritten. Junk detection is separate: a junk value may not be used as a
*source* for fills, but it still protects its field from overwrites.
"""

from __future__ import annotations

import re

from normalize import strip_renderable

__all__ = [
    "is_empty",
    "is_junk_value",
    "looks_yomitan_gloss",
    "is_blob_source",
    "sound_files",
    "image_files",
    "has_media_ref",
    "is_meaningful_definition",
    "FIELD_CLOZE",
    "FIELD_NEVER_COPY",
]

# Fields whose values describe the mined sentence fragment itself; they are
# never copied anywhere.
FIELD_CLOZE = ("cloze-prefix", "cloze-body", "cloze-suffix")
FIELD_NEVER_COPY = frozenset(FIELD_CLOZE)

_PLACEHOLDERS = {
    "-",
    "－",
    "—",
    "–",
    "n/a",
    "na",
    "none",
    "なし",
    "無し",
    "???",
    "todo",
    "tbd",
    "x",
}

_SOUND_FILE_RE = re.compile(r"\[sound:([^\]]+)\]", re.IGNORECASE)
_IMG_FILE_RE = re.compile(r"<img[^>]*\bsrc=[\"']([^\"']+)[\"']", re.IGNORECASE)
_MEDIA_ONLY_RE = re.compile(r"^(?:\s|\[sound:[^\]]*\]|<img\b[^>]*>)+$", re.IGNORECASE)
_SEPARATOR_ONLY_RE = re.compile(
    r"^(?:\s|<br\s*/?>|<hr\s*/?>|</?(?:div|p|span)[^>]*>)*$", re.IGNORECASE
)

_ATTRIBUTION_RE = re.compile(r"^\s*(?:\([^()]{0,80}\)|【[^【】]{0,80}】)", re.MULTILINE)
_PLACEHOLDER_STRIP_RE = re.compile(r"^[.,!?:;\s]+|[.,!?:;\s]+$")
_LICENSE_RE = re.compile(r"©|copyright|licensed|cc[- ]by|所有権|著作権", re.IGNORECASE)


def is_empty(value: str) -> bool:
    """The only gate for writing: raw string, whitespace-only means empty.

    ``<hr>`` and other markup-only values are NOT empty: they occupy the
    field and are never overwritten.
    """
    return not (value or "").strip()


def _only_media_refs(value: str) -> bool:
    """True when the value consists solely of sound/image references."""
    return bool(_MEDIA_ONLY_RE.match(value or "")) and has_media_ref(value)


def is_junk_value(value: str, expression: str = "", reading: str = "") -> bool:
    """True when a value must not be used as a fill *source*.

    Junk values still occupy their field (never overwritten); they are
    merely ineligible as sources. Doubled-reading Pitch Accent artifacts
    (``しんさつしつしんさつしつ``) and attribution-only definitions count
    as junk.
    """
    if is_empty(value):
        return True
    if _SEPARATOR_ONLY_RE.match(value or ""):
        return True
    if _only_media_refs(value):
        return True
    plain = strip_renderable(value).strip()
    if not plain:
        return True
    if _ATTRIBUTION_RE.search(value):
        remainder = strip_renderable(_ATTRIBUTION_RE.sub("", value, count=1)).strip()
        if not remainder:
            return True
    stripped = _PLACEHOLDER_STRIP_RE.sub("", plain.lower())
    if not stripped or stripped in _PLACEHOLDERS:
        return True
    if _LICENSE_RE.search(plain) and len(plain) < 120:
        return True
    if _is_multiplied_reading(value, reading):
        return True
    for label in (expression, reading):
        if label:
            norm = strip_renderable(label).strip()
            if norm and plain == norm:
                return True
    return False


def _is_multiplied_reading(value: str, reading: str) -> bool:
    if not reading:
        return False
    plain = strip_renderable(value).strip()
    if not plain:
        return False
    read = strip_renderable(reading).strip()
    if not read:
        return False
    if plain == read:
        return True
    doubled = read * 2
    return plain == doubled or plain == doubled.replace(" ", "")


_SELECTOR_TOKEN_RE = re.compile(
    r"\.yomitan-glossary|\bdata-sc-content\b|\bdata-dictionary\b|"
    r"\bul\b|\bol\b|\bli\b|&gt;|>|\{[^{}]*\}",
    re.IGNORECASE,
)


def looks_yomitan_gloss(value: str) -> bool:
    """Yomitan provenance: a *gloss node with text*, not mere markup.

    Provenance by markup presence alone is unreliable (scaffolding-only
    values are common), so require visible dictionary text after removing
    CSS-selector scaffolding and bracket attributes.
    """
    if not value or ("yomitan-glossary" not in value and "data-dictionary" not in value):
        return False
    # Remove bracketed attributes, selector scaffolding and the first
    # attribution prefix, then require remaining visible text.
    text = re.sub(r"\[[^\[\]]*\]", "", value)
    text = _SELECTOR_TOKEN_RE.sub(" ", text)
    text = _ATTRIBUTION_RE.sub("", text, count=1)
    plain = strip_renderable(text).strip()
    if not plain:
        return False
    # Visible CJK text is the strongest signal; otherwise accept non-empty
    # leftover text (English monolingual glosses) once scaffolding is gone.
    has_cjk = any("\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff" for ch in plain)
    return has_cjk or len(plain) >= 4


def is_meaningful_definition(value: str) -> bool:
    """True when a definition field carries real gloss text."""
    if is_junk_value(value):
        return False
    if looks_yomitan_gloss(value):
        return True
    plain = strip_renderable(value).strip()
    return len(plain) >= 2


def is_blob_source(value: str) -> bool:
    """True when Source still holds the un-enriched asbplayer blob URL."""
    v = value or ""
    return v.startswith("asbplayer") or "app.asbplayer.dev" in v


# Fields whose useful values ARE media references: a media-only value is
# the desired payload there, not junk.
MEDIA_FIELDS = frozenset({"Sentence Audio", "Picture", "Word Audio"})


def eligible_source(field_name: str, value: str, expression: str = "", reading: str = "") -> bool:
    """Field-aware source eligibility for a fill value."""
    if is_empty(value):
        return False
    if field_name in MEDIA_FIELDS:
        return has_media_ref(value)
    return not is_junk_value(value, expression=expression, reading=reading)


def sound_files(value: str) -> list[str]:
    return [m.group(1).strip() for m in _SOUND_FILE_RE.finditer(value or "")]


def image_files(value: str) -> list[str]:
    return [m.group(1).strip() for m in _IMG_FILE_RE.finditer(value or "")]


def has_media_ref(value: str) -> bool:
    return bool(sound_files(value) or image_files(value))
