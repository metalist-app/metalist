"""`/*help*/` in a search finds the notes whose own tag-bar comments contain `help`, in any case
(docs/ui/search-semantics.md, Comment Terms; agreed with the maintainer 2026-11-11)."""
from __future__ import annotations

import pytest

from app.services.input_errors import InputRejected
from app.services.search_index import NOTHING_INHERITED, SearchIndex, SearchRecord, extract_tags_for_search
from app.services.search_query import format_search_query, parse_search_query, search_highlight_phrases
from app.usecases.search_context_tags import ensure_tags_match_search_query, note_has_text_term

_NOTES = {
    "exact": ("Home - Workday", "Bookmarks/ /*help*/"),
    "capital": ("A link", "/*Help me*/"),
    "inside a word": ("Another link", "/*helpful links*/ work"),
    "spaced": ("Spaced", "/*  need   help  now */"),
    "text only": ("I need help", "work"),
    "value": ("Valued", 'title="help"'),
    "other comment": ("Other", "/*later*/"),
}


@pytest.fixture
def vault() -> SearchIndex:
    index = SearchIndex()
    index.attach_inherited_values_reader(lambda note_ids: {note_id: NOTHING_INHERITED for note_id in note_ids})
    index.rebuild(
        [SearchRecord(note_id=note_id, content_text=text, tags=tags, tag_terms=extract_tags_for_search(tags))
         for note_id, (text, tags) in _NOTES.items()],
        raw_tag_terms_by_id={note_id: extract_tags_for_search(tags) for note_id, (_text, tags) in _NOTES.items()},
        progress_update=lambda processed: None, progress_interval=len(_NOTES),
    )
    return index


@pytest.mark.parametrize(
    ("search", "found"),
    [
        ("/*help*/", {"exact", "capital", "inside a word", "spaced"}),
        ("/*HELP*/", {"exact", "capital", "inside a word", "spaced"}),
        ("/*help me*/", {"capital"}),
        ("/*  need help */", {"spaced"}),
        ("-/*help*/", {"text only", "value", "other comment"}),
        ("Bookmarks/ /*help*/", {"exact"}),
        ("/*help*/ work", {"inside a word"}),
        ("/*help*/ OR /*later*/", {"exact", "capital", "inside a word", "spaced", "other comment"}),
        # Not closed yet, as while typing: searched as if closed.
        ("/*hel", {"exact", "capital", "inside a word", "spaced"}),
        ('"help"', {"exact", "capital", "inside a word", "spaced", "text only"}),
    ],
)
def test_a_comment_term_finds_the_tag_bar_comments_containing_it(vault: SearchIndex, search: str, found: set[str]) -> None:
    assert vault.query_note_ids(search) == found


def test_a_comment_term_is_read_whole_and_never_highlighted() -> None:
    parsed = parse_search_query("/*help me*/ -/*later*/ \"plan\"")
    assert parsed.first_clause.required_text == ("/*help me*/", "plan")
    assert parsed.first_clause.forbidden_text == ("/*later*/",)
    assert parsed.first_clause.required_tags == frozenset()
    assert search_highlight_phrases(parsed) == ("plan",)
    assert format_search_query(parsed) == '/*help me*/ "plan" -/*later*/'
    with pytest.raises(InputRejected, match="between /\\* and \\*/"):
        parse_search_query("/* */")


# A note made or moved under the search gets the comment itself, unless it has it.
def test_a_note_under_a_comment_search_gets_the_comment() -> None:
    assert ensure_tags_match_search_query(parent_id=None, content="", tags="work", search_query="/*help*/") == "work /*help*/"
    assert ensure_tags_match_search_query(parent_id=None, content="", tags="/*Help me*/", search_query="/*help*/") == "/*Help me*/"
    assert note_has_text_term("/*help*/", content="I need help", tags="") is False
