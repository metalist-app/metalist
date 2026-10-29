"""A web link to a site its note's ancestors already link to shows its text alone: no
site icon, no " · domain" (docs/ui/content-formatting.md, Links In View Mode; agreed
2026-10-28). The ancestors count where they are shown above the note: the list, an
embed's own notes, full screen, downloads and prints; a note drawn on its own keeps both."""

from __future__ import annotations

import re

import pytest

import app.services.note_fullscreen as fullscreen_module
from app.services.content_formatting import format_note_content_for_view, showing_sites_above, sites_linked_in
from app.services.link_icons import link_icon_store
from app.services.link_titles import site_of_url
from tests.unit import test_html_export as export_tests
from tests.unit import test_note_fullscreen as fullscreen_tests
from tests.unit.test_snapshot_embedded_references import _Note, _state_for

VIDEO_ID = "11111111-1111-4111-8111-111111111111"
CHAPTERS_ID = "22222222-2222-4222-8222-222222222222"
SONG_ID = "33333333-3333-4333-8333-333333333333"
HOLDER_ID = "44444444-4444-4444-8444-444444444444"
ICON = "AAAA"

VIDEO = '<div>Sourdough video <a href="https://www.youtube.com/watch?v=abc">watch it</a></div>'
CHAPTERS = (
    '<div><a href="https://youtu.be/abc?t=0">0:00 Intro</a></div>'
    '<div><a href="https://m.youtube.com/watch?v=abc&amp;t=57">0:57 Starter</a></div>'
    '<div><a href="https://en.wikipedia.org/wiki/Sourdough">Sourdough on Wikipedia</a></div>'
)
SONG = '<div><a href="https://music.youtube.com/watch?v=song">The song</a></div>'
_ANCHOR_RE = re.compile(r'<a\b[^>]*href="https?://[^"]*"[^>]*>(.*?)</a>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


@pytest.fixture(autouse=True)
def _known_icons(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every site's icon is known, so a link shows one unless the rule leaves it out.
    monkeypatch.setattr(link_icon_store, "get_icon_base64", lambda url: ICON)


def _links(markup: str) -> list[tuple[str, bool]]:
    """Each web link's text as shown, and whether it shows its site's icon."""
    return [
        (" ".join(_TAG_RE.sub("", inner).split()), "link-title-icon" in inner)
        for inner in _ANCHOR_RE.findall(markup)
    ]


CHAPTERS_ALONE = [
    ("0:00 Intro · youtu.be", True), ("0:57 Starter · m.youtube.com", True),
    ("Sourdough on Wikipedia · en.wikipedia.org", True),
]
CHAPTERS_UNDER_VIDEO = [("0:00 Intro", False), ("0:57 Starter", False), ("Sourdough on Wikipedia · en.wikipedia.org", True)]


@pytest.mark.parametrize(("url", "site"), [
    ("https://www.youtube.com/watch?v=abc", "youtube.com"),
    ("https://m.youtube.com/watch?v=abc", "youtube.com"),
    ("https://music.youtube.com/watch?v=song", "youtube.com"),
    ("https://youtu.be/abc", "youtube.com"),
    ("https://old.reddit.com/r/Breadit", "reddit.com"),
    ("https://news.bbc.co.uk/story", "bbc.co.uk"),
    ("https://en.wikipedia.org/wiki/Sourdough", "wikipedia.org"),
])
def test_a_site_is_its_own_domain_whatever_the_subdomain(url: str, site: str) -> None:
    assert site_of_url(url) == site


def test_the_sites_a_note_links_to_are_read_from_its_whole_text() -> None:
    content = (
        '<div>Plan</div><div>Source: <a href="https://www.youtube.com/watch?v=x">video</a></div>'
        '<div>and https://old.reddit.com/r/Breadit, www.example.com without a scheme</div>'
    )
    assert sites_linked_in(content) == frozenset({"youtube.com", "reddit.com"})
    assert sites_linked_in("<div>no links</div>") == frozenset()


def test_links_to_a_site_shown_above_drop_its_icon_and_domain() -> None:
    assert _links(format_note_content_for_view(content_html=CHAPTERS, tags="", redact_credentials=False)) == CHAPTERS_ALONE
    with showing_sites_above(frozenset({"youtube.com"})):
        drawn = format_note_content_for_view(content_html=CHAPTERS, tags="", redact_credentials=False)
    assert _links(drawn) == CHAPTERS_UNDER_VIDEO


def _list_notes() -> dict[str, _Note]:
    return {
        VIDEO_ID: _Note(VIDEO_ID, None, None, HOLDER_ID, False, VIDEO, ""),
        CHAPTERS_ID: _Note(CHAPTERS_ID, VIDEO_ID, None, None, False, CHAPTERS, ""),
        SONG_ID: _Note(SONG_ID, CHAPTERS_ID, None, None, False, SONG, ""),
        HOLDER_ID: _Note(HOLDER_ID, None, VIDEO_ID, None, False, f"<div>![[{CHAPTERS_ID}]]</div>", ""),
    }


def _list_state(monkeypatch: pytest.MonkeyPatch, notes: dict[str, _Note]):
    children = {None: [VIDEO_ID, HOLDER_ID], VIDEO_ID: [CHAPTERS_ID], CHAPTERS_ID: [SONG_ID]}
    return _state_for(monkeypatch=monkeypatch, notes=notes, children_by_parent=children)


def test_in_the_list_a_note_under_a_link_to_the_site_drops_it_and_so_do_its_children(monkeypatch) -> None:
    state = _list_state(monkeypatch, _list_notes())
    assert _links(state.payloads[VIDEO_ID]["content"]) == [("watch it · youtube.com", True)]
    assert _links(state.payloads[CHAPTERS_ID]["content"]) == CHAPTERS_UNDER_VIDEO
    assert _links(state.payloads[SONG_ID]["content"]) == [("The song", False)]


def test_an_ancestor_link_anywhere_in_its_text_counts_and_removing_it_brings_the_site_back(monkeypatch) -> None:
    notes = _list_notes()
    notes[VIDEO_ID].content = f"<div>Bread notes</div><div>Source: {VIDEO[len('<div>Sourdough video '):]}"
    assert _links(_list_state(monkeypatch, notes).payloads[CHAPTERS_ID]["content"]) == CHAPTERS_UNDER_VIDEO
    notes[VIDEO_ID].content = "<div>Sourdough video, no link</div>"
    state = _list_state(monkeypatch, notes)
    assert _links(state.payloads[CHAPTERS_ID]["content"]) == CHAPTERS_ALONE
    # The song still sits under the chapters, which link to YouTube.
    assert _links(state.payloads[SONG_ID]["content"]) == [("The song", False)]


def test_an_embedded_note_keeps_its_sites_and_its_children_in_the_embed_follow_it(monkeypatch) -> None:
    holder = _list_state(monkeypatch, _list_notes()).payloads[HOLDER_ID]["content"]
    assert _links(holder) == [*CHAPTERS_ALONE, ("The song", False)]


def test_full_screen_follows_the_notes_it_shows(monkeypatch) -> None:
    notes = {
        VIDEO_ID: fullscreen_tests._Note(VIDEO_ID, None, VIDEO, ""),
        CHAPTERS_ID: fullscreen_tests._Note(CHAPTERS_ID, VIDEO_ID, CHAPTERS, ""),
        SONG_ID: fullscreen_tests._Note(SONG_ID, CHAPTERS_ID, SONG, ""),
    }
    store = fullscreen_tests._FakeNoteStore(notes=notes, children={None: [VIDEO_ID], VIDEO_ID: [CHAPTERS_ID], CHAPTERS_ID: [SONG_ID]})
    monkeypatch.setattr(fullscreen_module, "note_store", store)
    monkeypatch.setattr(fullscreen_module, "file_registry", fullscreen_tests._FakeFileRegistry())
    from_video = fullscreen_module.build_note_fullscreen_markup(VIDEO_ID)
    assert _links(from_video) == [("watch it · youtube.com", True), *CHAPTERS_UNDER_VIDEO, ("The song", False)]
    # Opened on the chapters, nothing is shown above them.
    from_chapters = fullscreen_module.build_note_fullscreen_markup(CHAPTERS_ID)
    assert _links(from_chapters) == [*CHAPTERS_ALONE, ("The song", False)]


@pytest.mark.parametrize("purpose", ["download", "print"])
def test_downloads_and_prints_look_as_metalist_does(monkeypatch, purpose: str) -> None:
    Note = export_tests._Note
    notes = {
        VIDEO_ID: Note(VIDEO_ID, None, None, None, False, VIDEO, ""),
        CHAPTERS_ID: Note(CHAPTERS_ID, VIDEO_ID, None, None, False, CHAPTERS, ""),
        SONG_ID: Note(SONG_ID, CHAPTERS_ID, None, None, False, SONG, ""),
    }
    document = export_tests._export(
        monkeypatch, notes, {None: [VIDEO_ID], VIDEO_ID: [CHAPTERS_ID], CHAPTERS_ID: [SONG_ID]},
        purpose=purpose, title="Bread", include_credentials=False, editing_note_id=None,
    )
    shown = list(dict.fromkeys(_links(export_tests._notes_markup(document))))
    assert shown == [("watch it · youtube.com", True), *CHAPTERS_UNDER_VIDEO, ("The song", False)]
