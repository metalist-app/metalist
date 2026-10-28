"""A link to an @password or @username note works like that note's own row (agreed 2026-10-26):
the lock or user icon, then the value (a password blurred), and clicking the value copies it, with
no stop at the note on the way; the link's reference icon still goes to the note. An @password
note's content is the password itself: the link used to show it in plain text, as text that did
nothing. Exports, prints and the AI still get the mask. An embed (a note that is only the
reference) shows the note's own row, as before."""

from __future__ import annotations

import re

import pytest

from app.services.content_formatting import CREDENTIAL_MASK
from app.services.embedded_references import EmbedRenderContext, render_note_content_with_embeds
from tests.unit.snapshot_note_fixture import SnapshotTestNote as _Note

SOURCE_ID = "11111111-1111-4111-8111-111111111111"
SECRET = "hunter2-correct-horse"


def _render(content_html: str, source_tags: str, *, redact_credentials: bool, static_export: bool) -> str:
    source = _Note(SOURCE_ID, None, None, None, False, f"<div>{SECRET}</div>", source_tags)
    context = EmbedRenderContext(
        has_note=lambda note_id: note_id == SOURCE_ID, get_note=lambda note_id: source,
        get_children=lambda parent_id: [], has_file=lambda file_id: False, get_file=lambda file_id: None,
        is_property_used=lambda property_name: False,
        static_collapse_arrows=False,
    )
    return render_note_content_with_embeds(
        note_id="host", content_html=content_html, tags="", context=context,
        static_export=static_export, redact_credentials=redact_credentials,
    )


def _link(rendered: str) -> str:
    match = re.search(r'<a href="#" class="note-reference-link".*?</a>', rendered, re.DOTALL)
    assert match is not None, rendered
    return match.group(0)


@pytest.mark.parametrize("credential", ["password", "username"])
def test_a_link_to_a_credential_note_is_its_copyable_row(credential: str) -> None:
    rendered = _render(f"<div>See [[{SOURCE_ID}]] for the login</div>", f"@{credential}",
                       redact_credentials=False, static_export=False)

    link = _link(rendered)
    # The reference icon, which goes to the note, then the note's own row.
    assert 'class="note-reference-link-icon note-reference-icon"' in link
    assert f'<span class="meta-credential meta-credential-{credential}">' in link
    assert f'class="meta-credential-value" data-copy-value="{SECRET}">{SECRET}</span>' in link
    assert CREDENTIAL_MASK not in link


@pytest.mark.parametrize("static_export", [False, True], ids=["the AI", "an export"])
def test_where_credentials_are_hidden_a_link_shows_the_mask(static_export: bool) -> None:
    rendered = _render(f"<div>See [[{SOURCE_ID}]] for the login</div>", "@password",
                       redact_credentials=True, static_export=static_export)

    assert SECRET not in rendered
    assert CREDENTIAL_MASK in rendered


def test_an_embed_of_a_password_note_shows_its_own_row() -> None:
    rendered = _render(f"<div>![[{SOURCE_ID}]]</div>", "@password", redact_credentials=False, static_export=False)

    assert '<div class="meta-credential meta-credential-password">' in rendered
    assert f'data-copy-value="{SECRET}"' in rendered
