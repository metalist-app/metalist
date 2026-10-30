"""Tag suggestions read a link's fetched title as text of the note
(docs/ui/tag-bar.md; agreed 2026-10-28): the same titles quoted search reads, only
the note's own links, and only once a title is known."""

from __future__ import annotations

import pytest

import app.services.tag_suggestions as tag_suggestions_module
from app.services.link_titles import link_title_store
from tests.unit.test_segment_aware_tag_suggestions import _EmptyOntology
from tests.unit.test_tag_suggestion_reasons import _reasons, _use

VIDEO = "https://www.youtube.com/watch?v=GYx4sourdough"
TITLE = "Sourdough Starter From Scratch - YouTube"
ROWS = [("bread-1", "sourdough-starter"), ("bread-2", "sourdough-starter"), ("site", "youtube"), ("other", "cooking")]
# Every tag is listed by use after those with evidence: without the title, nothing names it.
BY_USE = ("Listed by use: you've tagged 2 notes with it",)
TITLE_REASON = ('Named in the title of a link in this note: "sourdough starter"', "You've tagged 2 notes with it")


class _Titles:
    """The fetched titles, by address; a title arriving moves the store's revision."""

    def __init__(self) -> None:
        self.titles: dict[str, str] = {}
        self.revision = 0

    def arrive(self, url: str, title: str) -> None:
        self.titles[url] = title
        self.revision += 1

    def get_ok_title(self, url: str) -> str | None:
        if url not in self.titles:  # shockharness: ignore[DEF002] reason="a title not fetched yet is unknown, as in the store"
            return None
        return self.titles[url]


@pytest.fixture
def titles(monkeypatch: pytest.MonkeyPatch) -> _Titles:
    known = _Titles()
    monkeypatch.setattr(link_title_store, "get_ok_title", known.get_ok_title)
    monkeypatch.setattr(link_title_store, "get_revision", lambda: known.revision)
    _use(monkeypatch, rows=ROWS, ontology=_EmptyOntology())
    return known


def test_a_link_note_is_suggested_tags_its_title_names_once_the_title_is_known(titles: _Titles) -> None:
    assert _reasons(anchors=[], prefix="", content=VIDEO)["sourdough-starter"] == BY_USE
    titles.arrive(VIDEO, TITLE)
    assert _reasons(anchors=[], prefix="", content=VIDEO)["sourdough-starter"] == TITLE_REASON


def test_a_title_arriving_while_typing_shows_in_the_next_suggestions(titles: _Titles) -> None:
    assert _reasons(anchors=[], prefix="sour", content=VIDEO)["sourdough-starter"] == (
        'Matches what you typed: "sour"', *BY_USE,
    )
    titles.arrive(VIDEO, TITLE)
    typed = _reasons(anchors=[], prefix="sour", content=VIDEO)
    assert list(typed)[0] == "sourdough-starter"
    assert typed["sourdough-starter"] == TITLE_REASON


def test_text_of_the_note_is_named_as_the_note_not_the_title(titles: _Titles) -> None:
    titles.arrive(VIDEO, TITLE)
    reasons = _reasons(anchors=[], prefix="", content=f"My sourdough starter notes {VIDEO}")
    assert reasons["sourdough-starter"][0] == 'Named in this note: "sourdough starter"'


def test_only_the_notes_own_links_count(titles: _Titles) -> None:
    # A child of the link note: its own text has no link, so no title counts.
    titles.arrive(VIDEO, TITLE)
    assert _reasons(anchors=[], prefix="", content="Feeding schedule")["sourdough-starter"] == BY_USE


def test_the_site_name_still_counts_and_a_labeled_link_keeps_its_label(titles: _Titles) -> None:
    reasons = _reasons(anchors=[], prefix="", content=f'<a href="{VIDEO}">Cooking class</a>')
    assert reasons["cooking"][0] == 'Named in this note: "cooking"'
    assert _reasons(anchors=[], prefix="", content=VIDEO)["youtube"][0] == 'Named in this note: "youtube"'


def test_single_word_tags_named_in_a_title(monkeypatch: pytest.MonkeyPatch, titles: _Titles) -> None:
    # Reported 2026-10-29: a HashCloak tutorial on Lean, its address holding "(part-1)".
    url = "https://hashcloak.com/blog/tutorial-introduction-to-formal-verification-with-lean-(part-1)"
    _use(monkeypatch, rows=[("t", "tutorial"), ("l", "Lean"), ("y", "YouTube"), ("v", "video")], ontology=_EmptyOntology())
    titles.arrive(url, "Tutorial: Introduction to Formal Verification with Lean (Part 1) - HashCloak")
    reasons = _reasons(anchors=["interesting"], prefix="", content=url)
    assert set(list(reasons)[:2]) == {"tutorial", "Lean"}
    assert reasons["Lean"][0] == 'Named in the title of a link in this note: "Lean"'
