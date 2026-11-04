"""Tags and searches in any script (docs/ui/tag-bar.md, Whitespace + Tokens; decided 2026-10-30).

The server and the browser share one character rule and one case folding, from
app/static/config/tag-characters.json: these tests keep the generated browser copy and the
lowercase fixture in step with it, and the data in step with the Python running them.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

import pytest

from app.services.search_text import build_searchable_base_text_casefold
from app.services.text_terms import text_term_matches
from app.services.tag_characters import clean_tag_text, is_text_character, normalize_text
from app.services.tag_properties import is_property_name, split_property_segments
from app.services.selected_text_tag import build_default_tag_from_selected_text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_tag_characters as generator  # noqa: E402

DATA = json.loads(generator.DATA_PATH.read_text(encoding="utf-8"))
LOWERCASE = json.loads(generator.LOWERCASE_FIXTURE_PATH.read_text(encoding="utf-8"))


def _assigned_here(code: str) -> bool:
    """Whether this Python's Unicode version knows the character (the data may be newer)."""
    return unicodedata.category(chr(int(code, 16))) != generator.UNASSIGNED_CATEGORY


def test_the_browser_copy_is_generated_from_the_data() -> None:
    # A change to the JSON needs `python3.14 scripts/generate_tag_characters.py`.
    assert generator.BROWSER_MODULE_PATH.read_text(encoding="utf-8") == generator.browser_module_text(DATA)


def test_the_data_lists_the_invisible_characters_the_generator_names() -> None:
    assert DATA["invisible"] == [generator.code_point_key(ord(character)) for character in generator.INVISIBLE_CHARACTERS]


def test_casefold_exceptions_agree_with_this_python() -> None:
    # The browser folds a character with the table when it lists it, else with toLowerCase:
    # for every character this Python knows, that must be what str.casefold gives.
    exceptions = DATA["casefoldExceptions"]
    for character in generator.assigned_characters():
        key = generator.code_point_key(ord(character))
        if key in exceptions:
            assert exceptions[key] == character.casefold(), key
        else:
            assert character.lower() == character.casefold(), key


def test_the_fixture_lists_what_its_unicode_version_leaves_unassigned() -> None:
    if LOWERCASE["unicodeVersion"] != unicodedata.unidata_version:
        pytest.skip(f"the fixture is Unicode {LOWERCASE['unicodeVersion']}, this Python {unicodedata.unidata_version}")
    assert LOWERCASE["unassigned"] == generator.unassigned_ranges()


def test_the_lowercase_fixture_agrees_with_this_python() -> None:
    # tag_characters.test.mjs checks the browser's toLowerCase against this fixture.
    lowercase = LOWERCASE["lowercase"]
    for key, lowered in lowercase.items():
        if _assigned_here(key):
            assert chr(int(key, 16)).lower() == lowered, key
    for character in generator.assigned_characters():
        if character.lower() != character:
            assert generator.code_point_key(ord(character)) in lowercase


@pytest.mark.parametrize("character,expected", [
    ("é", True), ("日", True), ("🏃", True), (" ", True), ("‍", True), ("‌", True),
    ("​", False), ("‏", False), ("﻿", False), ("­", False), ("\x07", False),
])
def test_text_characters(character: str, expected: bool) -> None:
    assert is_text_character(character) is expected


@pytest.mark.parametrize("stored,expected", [
    # Stored in one form: a decomposed é becomes the composed one.
    ("Café 日記", "Café 日記"),
    # Invisible characters go; every space stays the separator it is.
    ("fo​o ba‏r", "foo bar"),
    ("one two", "one two"),
    ("👨‍👩‍👧", "👨‍👩‍👧"),
])
def test_tags_are_stored_clean(stored: str, expected: str) -> None:
    assert clean_tag_text(stored) == expected


def test_property_names_start_with_a_letter_in_any_script() -> None:
    assert is_property_name("Größe") and is_property_name("時間") and is_property_name("miles")
    assert not is_property_name("30") and not is_property_name("") and not is_property_name("a=b")
    assert split_property_segments("Größe=5:時間=3") == ["Größe=5", "時間=3"]


def test_a_quoted_search_finds_accented_text_in_either_form() -> None:
    text = build_searchable_base_text_casefold("Trip plan naïve", "")
    assert text_term_matches(normalize_text("NAÏVE").casefold(), text)


def test_a_selected_text_tag_keeps_its_letters() -> None:
    assert build_default_tag_from_selected_text("Größe 日記") == "Größe-日記"
