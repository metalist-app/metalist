"""A password shows as dots, never as its text (the maintainer, 2026-11-03;
docs/ui/content-formatting.md, @password). Before, the row held the real password as text and
blurred it: hidden from a glance, not from the page, where it could be selected, found and read
aloud, its length showing through. Now MetaList shows CREDENTIAL_MASK (8 bullets, whatever the
length) and only data-copy-value holds the value, so a click still copies it.

A link to an @password or @username note works like that note's own row (agreed 2026-10-26): the
lock or user icon, then the value, and clicking the value copies it; the link's reference icon
still goes to the note. An embed shows the note's own row. Exports, prints and the AI get the mask
unless the user includes passwords in an export, which then shows them as text."""

from __future__ import annotations

import re

import pytest

from app.services.credential_display import CredentialDisplay
from app.services.content_formatting import CREDENTIAL_MASK, format_note_content_for_view
from app.services.embedded_references import EmbedRenderContext, get_note_reference_preview, render_note_content_with_embeds
from tests.unit.snapshot_note_fixture import SnapshotTestNote as _Note

SOURCE_ID = "11111111-1111-4111-8111-111111111111"
SECRET = "hunter2-correct-horse"
SHORT_SECRET = "Zq"
PASSWORD_LABEL = 'role="img" aria-label="Hidden password"'


def _context(secret: str, source_tags: str) -> EmbedRenderContext:
    source = _Note(SOURCE_ID, None, None, None, False, f"<div>{secret}</div>", source_tags)
    return EmbedRenderContext(
        has_note=lambda note_id: note_id == SOURCE_ID, get_note=lambda note_id: source,
        get_children=lambda parent_id: [], has_file=lambda file_id: False, get_file=lambda file_id: None,
        is_property_used=lambda property_name: False,
        is_shown_in_gallery=lambda gallery_note_id, note_id: True,
        static_collapse_arrows=False,
    )


def _render(content_html: str, source_tags: str, *, credentials: CredentialDisplay, static_export: bool,
            secret: str) -> str:
    return render_note_content_with_embeds(
        note_id="host", content_html=content_html, tags="", context=_context(secret, source_tags),
        static_export=static_export, credentials=credentials,
    )


def _link(rendered: str) -> str:
    match = re.search(r'<a href="#" class="note-reference-link".*?</a>', rendered, re.DOTALL)
    assert match is not None, rendered
    return match.group(0)


def _value_only_copied(rendered: str, secret: str) -> None:
    """The password is in the page once, as the value a click copies; its text is the mask."""
    assert rendered.count(secret) == 1, rendered
    assert f'data-copy-value="{secret}">{CREDENTIAL_MASK}</span>' in rendered
    assert PASSWORD_LABEL in rendered
    assert "blur" not in rendered


@pytest.mark.parametrize("secret", [SECRET, SHORT_SECRET], ids=["long", "short"])
def test_a_password_notes_own_row_shows_eight_dots_and_copies_the_value(secret: str) -> None:
    rendered = format_note_content_for_view(content_html=f"<div>{secret}</div>", tags="@password",
                                            credentials=CredentialDisplay.DOTS)
    assert '<div class="meta-credential meta-credential-password">' in rendered
    _value_only_copied(rendered, secret)


def test_a_username_still_shows_its_text() -> None:
    rendered = format_note_content_for_view(content_html=f"<div>{SECRET}</div>", tags="@username",
                                            credentials=CredentialDisplay.DOTS)
    assert f'data-copy-value="{SECRET}">{SECRET}</span>' in rendered
    assert CREDENTIAL_MASK not in rendered


@pytest.mark.parametrize("secret", [SECRET, SHORT_SECRET], ids=["long", "short"])
def test_a_link_to_a_password_note_is_its_copyable_row_of_dots(secret: str) -> None:
    rendered = _render(f"<div>See [[{SOURCE_ID}]] for the login</div>", "@password",
                       credentials=CredentialDisplay.DOTS, static_export=False, secret=secret)
    link = _link(rendered)
    # The reference icon, which goes to the note, then the note's own row.
    assert 'class="note-reference-link-icon note-reference-icon"' in link
    assert '<span class="meta-credential meta-credential-password">' in link
    _value_only_copied(link, secret)


def test_a_link_to_a_username_note_shows_its_text() -> None:
    rendered = _render(f"<div>See [[{SOURCE_ID}]] for the login</div>", "@username",
                       credentials=CredentialDisplay.DOTS, static_export=False, secret=SECRET)
    assert f'class="meta-credential-value" data-copy-value="{SECRET}">{SECRET}</span>' in _link(rendered)


def test_an_embed_of_a_password_note_shows_its_own_row_of_dots() -> None:
    rendered = _render(f"<div>![[{SOURCE_ID}]]</div>", "@password",
                       credentials=CredentialDisplay.DOTS, static_export=False, secret=SECRET)
    assert '<div class="meta-credential meta-credential-password">' in rendered
    _value_only_copied(rendered, SECRET)


def test_a_password_notes_title_elsewhere_is_the_mask() -> None:
    # Where a link to the note shows its first line (a chip, a tab), never the password.
    preview = get_note_reference_preview(reference_note_id=SOURCE_ID, context=_context(SECRET, "@password"),
                                         credentials=CredentialDisplay.DOTS)
    assert preview == CREDENTIAL_MASK


@pytest.mark.parametrize("static_export", [False, True], ids=["the AI", "an export"])
def test_where_credentials_are_hidden_a_link_shows_the_mask(static_export: bool) -> None:
    rendered = _render(f"<div>See [[{SOURCE_ID}]] for the login</div>", "@password",
                       credentials=CredentialDisplay.HIDDEN, static_export=static_export, secret=SECRET)
    assert SECRET not in rendered
    assert CREDENTIAL_MASK in rendered


def test_an_export_including_passwords_shows_them_as_text() -> None:
    rendered = format_note_content_for_view(content_html=f"<div>{SECRET}</div>", tags="@password",
                                            credentials=CredentialDisplay.SHOWN)
    assert f'data-copy-value="{SECRET}">{SECRET}</span>' in rendered
    assert CREDENTIAL_MASK not in rendered
