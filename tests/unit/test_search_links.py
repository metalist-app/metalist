"""Links that open a search, [[search:…]] (docs/ready-to-build/search-links.md)."""
from __future__ import annotations

import pytest

from app.security.rendered_html import sanitize_rendered_html
from app.services.embedded_references import collect_active_reference_tokens, first_line_preview
from app.services.search_links import (
    SearchLink,
    parse_search_link,
    rename_tag_in_search,
    rename_tag_in_search_links,
    render_search_link,
    same_search,
)


@pytest.mark.parametrize(
    ("inner", "link"),
    [
        ("search:work -archive", SearchLink(search="work -archive", link_text="")),
        ("search:work -archive|Current work", SearchLink(search="work -archive", link_text="Current work")),
        ("search:  recipes  ", SearchLink(search="recipes", link_text="")),
    ],
)
def test_a_search_link_is_its_search_and_optional_text(inner: str, link: SearchLink) -> None:
    assert parse_search_link(inner) == link


@pytest.mark.parametrize("inner", ["search:", "search:   ", "search:work|", "search:work|  ", "Search:work", "work", "00000000-0000-4000-8000-000000000000"])
def test_anything_else_is_not_a_search_link(inner: str) -> None:
    assert parse_search_link(inner) is None


def test_a_search_link_draws_its_text_with_the_search_as_tooltip_and_survives_sanitizing() -> None:
    drawn = sanitize_rendered_html(render_search_link(SearchLink(search='work "due soon"', link_text="Current work"), static_export=False))
    assert 'class="note-search-link"' in drawn
    assert 'data-search-query="work &quot;due soon&quot;"' in drawn
    assert 'title="work &quot;due soon&quot;"' in drawn
    assert ">Current work<" in drawn
    # A link without text reads its search, so it needs no tooltip.
    plain = sanitize_rendered_html(render_search_link(SearchLink(search="recipes", link_text=""), static_export=False))
    assert ">recipes<" in plain and "title=" not in plain


def test_an_export_keeps_the_markup() -> None:
    assert render_search_link(SearchLink(search="work", link_text="Job"), static_export=True) == "[[search:work|Job]]"


def test_a_search_link_is_never_a_reference() -> None:
    assert collect_active_reference_tokens("<div>[[search:work]] and [[search:x|y]]</div>") == []


def test_a_first_line_with_a_search_link_reads_its_text() -> None:
    assert first_line_preview("<div>See [[search:work -archive|Current work]] daily</div>") == "See Current work daily"
    assert first_line_preview("<div>[[search:recipes]]</div>") == "recipes"


@pytest.mark.parametrize(
    ("search", "renamed"),
    [
        ("work -archive", "job -archive"),
        ("Work -archive", "job -archive"),
        ("-work +work", "-job +job"),
        ("work=high work:hours>2", "job=high job:hours>2"),
        ('work "work is fun" workshop', 'job "work is fun" workshop'),
        ("home OR work", "home OR job"),
        ("homework", "homework"),
    ],
)
def test_a_rename_changes_the_tag_terms_only(search: str, renamed: str) -> None:
    assert rename_tag_in_search(search, old="work", new="job") == renamed


def test_a_rename_rewrites_the_searches_in_a_notes_search_links_only() -> None:
    content = '<div>[[search:work -archive|Current work]] and [[search:"work"]] and work</div>'
    assert rename_tag_in_search_links(content, old="work", new="job") == (
        '<div>[[search:job -archive|Current work]] and [[search:"work"]] and work</div>'
    )
    assert rename_tag_in_search_links("<div>no links</div>", old="work", new="job") == "<div>no links</div>"


@pytest.mark.parametrize(
    ("first", "second", "same"),
    [
        ("work -archive", "work  -archive ", True),
        ("work -archive", "-archive work", True),
        ("work -archive", "Work -ARCHIVE", True),
        ('"due soon" "call back"', '"call back" "due soon"', True),
        ("a OR b", "b OR a", True),
        ('"due soon"', '"soon due"', False),
        ("work", "work -archive", False),
    ],
)
def test_searches_with_the_same_terms_are_the_same_search(first: str, second: str, same: bool) -> None:
    assert same_search(first, second) is same
