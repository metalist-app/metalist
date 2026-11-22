"""Links to a place in a note, `[[UUID#words in it]]` (docs/ui/references.md, "Links to a place
in a note"; agreed with the maintainer, 2026-11-21): the link says where it leads and reads
"first line > words" unless it has text of its own; an embed shows its whole note; after `#`
the `[[` list offers the note's lines, headings first."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import pytest

import app.services.reference_lines as reference_lines
from app.services.credential_display import CredentialDisplay
from app.services.embedded_references import (
    EmbedRenderContext,
    collect_reference_tokens_from_html,
    parse_reference_inner,
    render_note_content_with_embeds,
)
from app.services.note_gallery import every_note_shown
from app.services.reference_lines import MAX_LINE_CHARACTERS, NO_NOTE, ReferenceLine, note_lines, note_named_by_id

TRIP = "c0000000-0000-4000-8000-000000000001"
DAY = "c0000000-0000-4000-8000-000000000002"
SECRET = "c0000000-0000-4000-8000-000000000003"
HOST = "c0000000-0000-4000-8000-000000000004"


@dataclass(frozen=True)
class _Note:
    id: str
    content: str
    tags: str
    is_collapsed: bool


NOTES: Dict[str, _Note] = {
    TRIP: _Note(TRIP, "<div>Trip plan</div><div>Packing</div><div>## Day 3: Porto</div><div>Bridge walk at dusk</div>", "@markdown", False),
    DAY: _Note(DAY, "<div>Day 5: Lisbon</div><div>Tram 28</div>", "@heading", False),
    SECRET: _Note(SECRET, "<div>hunter2 on the tram</div>", "@password", False),
    HOST: _Note(HOST, "", "", False),
}
CHILDREN: Dict[str, List[str]] = {TRIP: [DAY, SECRET]}


# --- What is written ---------------------------------------------------------------------------

def test_the_words_after_the_hash_are_where_the_link_leads() -> None:
    assert parse_reference_inner(TRIP).section == ""
    assert parse_reference_inner(f"{TRIP}#Day 3").section == "Day 3"
    titled = parse_reference_inner(f"{TRIP}#Day 3|the Porto day")
    assert (titled.note_id, titled.section, titled.link_text) == (TRIP, "Day 3", "the Porto day")
    # A # with nothing after it is a link to the whole note; a # in the shown text is text.
    assert parse_reference_inner(f"{TRIP}#").section == ""
    assert parse_reference_inner(f"{TRIP}|issue #4").section == ""
    # The note's HTML holds & as an entity: the words are read as text.
    assert parse_reference_inner(f"{TRIP}#Bed &amp; breakfast").section == "Bed & breakfast"


def test_a_link_to_a_place_is_still_a_link_to_its_note() -> None:
    [token] = collect_reference_tokens_from_html(f"<div>See [[{TRIP}#Day 3]]</div>")
    assert (token.note_id, token.section, token.is_embed) == (TRIP, "Day 3", False)


# --- How it is drawn -----------------------------------------------------------------------------

def _drawn(content: str) -> str:
    context = EmbedRenderContext(
        has_note=lambda note_id: note_id in NOTES, get_note=lambda note_id: NOTES[note_id],
        get_children=lambda parent_id: CHILDREN.get(parent_id, []), has_file=lambda file_id: False,
        get_file=lambda file_id: None, is_property_used=lambda name: False,
        is_shown_in_gallery=every_note_shown, static_collapse_arrows=False,
    )
    return render_note_content_with_embeds(
        note_id=HOST, content_html=content, tags="", context=context, static_export=False, credentials=CredentialDisplay.HIDDEN,
    )


def test_the_link_says_where_it_leads_and_reads_its_note_then_the_words() -> None:
    drawn = _drawn(f"<div>[[{TRIP}#Day 3]]</div>")
    assert 'data-ref-section="Day 3"' in drawn
    assert '<span class="note-reference-link-title">Trip plan &gt; Day 3</span>' in drawn


def test_a_long_note_line_and_long_words_each_read_by_their_first_part(monkeypatch: pytest.MonkeyPatch) -> None:
    # The maintainer's link, 2026-11-21: "way too long" in full.
    monkeypatch.setitem(NOTES, TRIP, _Note(TRIP, "<div>galleries are confusing. the icons should be swapped</div>", "", False))
    drawn = _drawn(f"<div>[[{TRIP}#only some pdfs displayed? also, galleries don't show up in]]</div>")
    assert '<span class="note-reference-link-title">galleries are confusing &gt; only some pdfs displayed?</span>' in drawn
    # Where the link leads is the words as written, whole.
    assert 'data-ref-section="only some pdfs displayed? also, galleries don&#x27;t show up in"' in drawn


def test_a_link_with_text_of_its_own_shows_that_text_alone() -> None:
    drawn = _drawn(f"<div>[[{TRIP}#Day 3|the Porto day]]</div>")
    assert 'data-ref-section="Day 3"' in drawn
    assert '<span class="note-reference-link-title">the Porto day</span>' in drawn


def test_a_link_to_the_whole_note_is_drawn_as_before() -> None:
    drawn = _drawn(f"<div>[[{TRIP}]]</div>")
    assert "data-ref-section" not in drawn and "&gt;" not in drawn


def test_an_embed_shows_its_whole_note_whatever_follows_a_hash() -> None:
    drawn = _drawn(f"<div>![[{TRIP}#Day 3]]</div>")
    assert "data-ref-section" not in drawn and " &gt; Day 3" not in drawn
    assert "Packing" in drawn and "Bridge walk at dusk" in drawn


def test_the_words_are_escaped_in_the_page() -> None:
    drawn = _drawn(f'<div>[[{TRIP}#a &lt;b&gt; "c"]]</div>')
    assert 'data-ref-section="a &lt;b&gt; &quot;c&quot;"' in drawn
    assert "<b>" not in drawn


# --- The lines offered after # -------------------------------------------------------------------

@pytest.fixture
def vault(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Store:
        def contains(self, note_id: str) -> bool:
            return note_id in NOTES

        def get(self, note_id: str) -> _Note:
            return NOTES[note_id]

        def children(self, note_id: str) -> List[str]:
            return CHILDREN.get(note_id, [])

    monkeypatch.setattr(reference_lines, "store", _Store())
    monkeypatch.setattr(reference_lines, "get_cached_content", lambda note_id: NOTES[note_id].content)


def _offered(line_query: str) -> List[ReferenceLine]:
    return list(note_lines(note_id=TRIP, first_line="Trip plan", line_query=line_query).lines)


def test_headings_come_first_then_the_other_lines_in_order(vault: None) -> None:
    assert _offered("") == [
        ReferenceLine("Day 3: Porto", True), ReferenceLine("Day 5: Lisbon", True),
        ReferenceLine("Packing", False), ReferenceLine("Bridge walk at dusk", False), ReferenceLine("Tram 28", False),
    ]


def test_the_notes_own_first_line_and_a_passwords_text_are_never_offered(vault: None) -> None:
    texts = [line.text for line in _offered("")]
    assert "Trip plan" not in texts
    assert not any("hunter2" in text for text in texts)
    assert _offered("hunter") == []


def test_typed_words_narrow_the_lines_whatever_their_capitals(vault: None) -> None:
    assert [line.text for line in _offered("por")] == ["Day 3: Porto"]
    assert [line.text for line in _offered("TRAM")] == ["Tram 28"]
    assert _offered("no such words") == []


def test_a_line_is_offered_as_a_link_can_hold_it(vault: None, monkeypatch: pytest.MonkeyPatch) -> None:
    long_line = "word " * 30
    monkeypatch.setitem(NOTES, TRIP, _Note(TRIP, f"<div>Trip plan</div><div>See [[x]] there</div><div>a | b</div><div>{long_line}</div><div>[[only a link]]</div>", "", False))
    texts = [line.text for line in _offered("") if not line.is_heading]
    assert texts[:2] == ["See", "a"]
    assert len(texts[2]) <= MAX_LINE_CHARACTERS and texts[2].endswith("word") and not texts[2].endswith(" ")
    # A line that is only a link has no words to lead to.
    assert all("[" not in text and "|" not in text for text in texts)


def test_a_note_is_named_by_its_id_only_when_it_is_in_the_vault(vault: None) -> None:
    assert note_named_by_id(TRIP) == TRIP
    assert note_named_by_id("c0000000-0000-4000-8000-00000000ffff") == NO_NOTE
    assert note_named_by_id("Trip plan") == NO_NOTE
