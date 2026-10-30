"""Small text helpers shared by several modules."""
from __future__ import annotations

import re
import unicodedata

INVISIBLE_CHARS_RE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")   # bidi marks, BOM


def strip_invisible_chars(text: str) -> str:
    """NFKC-normalise (full-width digits, odd spaces...) and drop invisible bidi marks."""
    return INVISIBLE_CHARS_RE.sub("", unicodedata.normalize("NFKC", text))


def normalize_name(name: str) -> str:
    """Form of a name used for comparing (case, '~' prefix and invisible chars ignored)."""
    return strip_invisible_chars(name).strip().lstrip("~").strip().casefold()
