"""A long line shown by its first part (app/utils/first_clause.py; the maintainer, 2026-11-21)."""

import pytest

from app.utils.first_clause import first_clause


@pytest.mark.parametrize(("text", "shown"), [
    # The maintainer's own link: each part by its first sentence.
    ("galleries are confusing. the icons should be swapped", "galleries are confusing"),
    ("only some pdfs displayed? also, galleries don't show up in", "only some pdfs displayed?"),
    # A question or an exclamation keeps its mark; a statement loses its full stop.
    ("What a day this was! And then it rained.", "What a day this was!"),
    # No sentence end: a short line stays whole, a long one is cut at its first comma.
    ("Day 3: Porto", "Day 3: Porto"),
    ("Trip plan, second draft", "Trip plan, second draft"),
    ("the icons should be swapped around and made clearer, and the switch moved", "the icons should be swapped around and made clearer"),
    # A first sentence that is still long is cut at its comma.
    ("galleries are confusing, the icons should be swapped and made clearer. More.", "galleries are confusing"),
    # A short opening is no clause of its own.
    ("e.g. the gallery of holiday pictures. More.", "e.g. the gallery of holiday pictures"),
    ("Well, this is odd. Next.", "Well, this is odd"),
    ("Dr. Smith went home. Then he slept.", "Dr. Smith went home"),
    # Numbers and names with dots in them stay whole.
    ("MetaList 0.32.0 came out today", "MetaList 0.32.0 came out today"),
    ("See example.com for the whole list", "See example.com for the whole list"),
    # Dots that trail off end the part like one.
    ("something went wrong... what now", "something went wrong"),
    # One line, single spaces; nothing to cut in a line that ends at its only mark.
    ("  two   spaces\nand a line break ", "two spaces and a line break"),
    ("Is this the only sentence?", "Is this the only sentence?"),
    # A line that only ends in a full stop was not cut: it stays as written.
    ("This is the only sentence.", "This is the only sentence."),
    ("", ""),
])
def test_a_line_is_shown_by_its_first_part(text: str, shown: str) -> None:
    assert first_clause(text) == shown
