"""The snippet under a PDF's card when a search's quoted phrase is in its text
(docs/ready-to-build/folder-import-and-file-previews.md, "Searchable file text", the snippet's
cases agreed 2026-11-01)."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

import app.services.file_text_search as file_text_search_module
from app.services.embedded_references import _render_file_embed_body, _render_file_link_body
from app.services.file_text_search import file_texts
from app.services.file_text_snippets import file_text_snippet, with_file_text_snippets
from app.services.snapshot import shows_file_text_snippets

FILE = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
LEASE_TEXT = (
    "Lease agreement between the landlord and Sam Rivera. " * 3
    + "Rent is due on the first of each month, paid to the landlord's account. "
    + "The deposit is returned within 30 days of the lease ending. " * 3
)


def _file(name: str) -> SimpleNamespace:
    return SimpleNamespace(title=name, original_filename=name, mime_type="application/pdf", size_bytes=1, thumbnail_kind="pdf")


# Cards and links drawn as the list draws them: a snippet test on hand-made markup kept passing
# when the card changed shape, while the list showed no snippets (2026-11-03).
def _card(file_id: str, name: str) -> str:
    return _render_file_embed_body(record=_file(name), reference_note_id=file_id, static_export=False)


def _link(file_id: str, name: str) -> str:
    return _render_file_link_body(record=_file(name), reference_note_id=file_id, link_text=None, static_export=False)


@pytest.fixture
def texts(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Files' text as if stored, the filters taken as 'maybe' (the filter has its own tests)."""
    stored = {FILE: LEASE_TEXT, OTHER: "Kelp wrap and sea glass, a receipt from the harbor shop."}
    monkeypatch.setattr(file_texts, "loaded_file_ids", lambda: frozenset(stored))
    monkeypatch.setattr(file_texts, "term_matches", lambda file_id, term: term.strip().casefold() in stored[file_id].casefold())
    monkeypatch.setattr(file_texts, "text_of", lambda file_id: stored[file_id])
    monkeypatch.setattr(file_texts, "is_cut", lambda file_id: False)
    return stored


def test_a_matched_file_shows_a_snippet_around_the_first_match_cut_at_word_edges(texts) -> None:
    snippet = file_text_snippet(FILE, ("rent is due",))
    assert "Rent is due on the first of each month" in snippet
    assert snippet.startswith("…") and snippet.endswith("…")
    assert not snippet.startswith("… ") and len(snippet) < 260


def test_one_file_several_phrases_one_snippet_from_the_first_match(texts) -> None:
    snippet = file_text_snippet(FILE, ("deposit", "rent is due"))
    assert snippet.index("Rent is due") < snippet.index("deposit")


def test_no_phrase_in_the_text_no_snippet(texts) -> None:
    assert file_text_snippet(FILE, ("harbor",)) == ""
    assert file_text_snippet(FILE, ()) == ""


def test_the_snippet_goes_inside_the_matched_cards_only(texts) -> None:
    rendered = f"<div>Signed {_card(FILE, 'Lease.pdf')} and {_card(OTHER, 'Receipt.pdf')}</div>"
    shown = with_file_text_snippets(rendered, ("rent is due",))
    assert shown.count('class="note-file-text-snippet"') == 1
    lease_card = shown[shown.index(f'data-file-ref-id="{FILE}"'):shown.index(f'data-file-ref-id="{OTHER}"')]
    # Inside the card, last: under its name and buttons, then the card closes.
    assert lease_card.index('class="note-file-text-snippet"') > lease_card.index("note-file-download")
    assert re.search(r'class="note-file-text-snippet">[^<]*</span></span> and ', shown) is not None


def test_several_matched_files_each_get_their_snippet(texts) -> None:
    rendered = f"<div>{_card(FILE, 'Lease.pdf')}{_card(OTHER, 'Receipt.pdf')}</div>"
    shown = with_file_text_snippets(rendered, ("lease", "harbor"))
    assert shown.count('class="note-file-text-snippet"') == 2


def test_a_phrase_only_in_the_files_name_shows_no_snippet(texts) -> None:
    rendered = _card(OTHER, "Receipt.pdf")
    assert with_file_text_snippets(rendered, ("receipt.pdf",)) == rendered


def test_no_phrases_or_no_searchable_file_leaves_the_html_as_it_is(texts) -> None:
    rendered = f"<div>{_card(FILE, 'Lease.pdf')}</div>"
    assert with_file_text_snippets(rendered, ()) == rendered
    unknown = _card("33333333-3333-3333-3333-333333333333", "Notes.pdf")
    assert with_file_text_snippets(unknown, ("lease",)) == unknown


def test_the_snippet_text_is_escaped(texts) -> None:
    texts[OTHER] = "Bring <script>alert(1)</script> to the harbor & more."
    shown = with_file_text_snippets(_card(OTHER, "Receipt.pdf"), ("harbor",))
    assert "<script>" not in shown and "&lt;script&gt;" in shown


def test_a_link_to_a_file_in_running_text_gets_no_snippet(texts) -> None:
    link = _link(FILE, "Lease.pdf")
    assert with_file_text_snippets(link, ("rent is due",)) == link


def test_a_cut_files_card_says_how_far_search_reaches(texts, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_texts, "is_cut", lambda file_id: True)
    shown = with_file_text_snippets(_card(FILE, "Lease.pdf"), ("harbor",))
    assert f'data-file-ref-id="{FILE}" title="Search covers its first ~2,000 pages.">' in shown
    assert file_text_search_module.MAX_FILE_TEXT_CHARACTERS > 0


@pytest.mark.parametrize(("flags", "is_search_redacted", "shows"), [
    ({"isEditing": False, "isCollapsed": False, "isCollapsible": True}, False, True),
    ({"isEditing": True, "isCollapsed": False, "isCollapsible": True}, False, False),
    # Folded: the user's choice; no snippet.
    ({"isEditing": False, "isCollapsed": True, "isCollapsible": True}, False, False),
    # Saved folded with nothing to fold (one card): no arrow to open it, so the snippet shows.
    ({"isEditing": False, "isCollapsed": True, "isCollapsible": False}, False, True),
    ({"isEditing": False, "isCollapsed": False, "isCollapsible": False}, True, False),
])
def test_which_notes_in_the_list_show_snippets(flags: dict[str, bool], is_search_redacted: bool, shows: bool) -> None:
    assert shows_file_text_snippets(flags, is_search_redacted=is_search_redacted) is shows
