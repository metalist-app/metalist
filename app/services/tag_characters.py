"""Which characters tags and searches keep, and how tag text is normalized (docs/ui/tag-bar.md,
Whitespace + Tokens).

Tags may use letters in any script (decided 2026-10-30). Three rules keep tags that look the
same from differing: text is stored in one Unicode form (NFC); control characters and the
invisible characters in app/static/config/tag-characters.json are dropped, while every
Unicode space separates like a space; and the browser folds case exactly as the server's
str.casefold does (tag-characters.js, from the same JSON).
"""

from __future__ import annotations

import json
import unicodedata
from importlib.resources import files
from typing import Final, Literal

_DATA = json.loads(files("app").joinpath("static/config/tag-characters.json").read_text(encoding="utf-8"))
# The data writes code points in hexadecimal.
_HEXADECIMAL = 16
# The one Unicode form tags and searches are kept in.
NORMAL_FORM: Final[Literal["NFC"]] = "NFC"
_CONTROL_CATEGORY = "Cc"

INVISIBLE_CHARACTERS = frozenset(chr(int(code, _HEXADECIMAL)) for code in _DATA["invisible"])
if not INVISIBLE_CHARACTERS:
    raise RuntimeError("app/static/config/tag-characters.json lists no invisible characters")


def is_text_character(character: str) -> bool:
    """Whether a tag, a tag comment or a search may keep this character: any character but a
    control character or an invisible one. Spaces count (callers split tags on them)."""
    if not isinstance(character, str) or len(character) != 1:
        raise TypeError(f"is_text_character expects one character, got {character!r}")
    if character in INVISIBLE_CHARACTERS:
        return False
    return unicodedata.category(character) != _CONTROL_CATEGORY


def normalize_text(text: str) -> str:
    """Text in the one form tags and searches use (NFC)."""
    if not isinstance(text, str):
        raise TypeError(f"normalize_text expects a string, got {type(text)}")
    return unicodedata.normalize(NORMAL_FORM, text)


def clean_tag_text(text: str) -> str:
    """A tag bar's text as stored: NFC, every whitespace character kept as the separator it
    is, other control characters and the invisible ones dropped."""
    normalized = normalize_text(text)
    return "".join(
        character for character in normalized
        if character.isspace() or is_text_character(character)
    )
