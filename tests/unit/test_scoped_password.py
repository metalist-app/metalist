"""A password in a note's text: the region `((@password))` names (docs/ui/content-formatting.md,
"A password in a note's text"). It shows and copies as a password note's value does, and the AI,
exports and prints get what they get of a password note, while the rest of the note reads as usual."""

from types import SimpleNamespace

from app.services.content_formatting import (
    CREDENTIAL_MASK,
    SCOPED_PASSWORD_REDACTION,
    agent_note_text_from_kept_text,
    extract_agent_note_text,
    format_note_content_for_view,
    redact_scoped_passwords,
    text_shown_without_passwords,
)
from app.services.credential_display import CredentialDisplay
from app.services.note_gallery import _caption
import app.services.tag_suggestions as tag_suggestions_module
from app.services.tag_suggestions import _new_tags_from_note_words
from tests.unit.test_segment_aware_tag_suggestions import _EmptyOntology

PASSWORD = "S3cret!pw"
BANK_NOTE = f"<div>Login for the bank: (({PASSWORD})) then 2FA</div>"
BANK_TAGS = "bank ((@password))"


def _no_titles(_url: str) -> None:
    return None


def test_in_metalist_the_region_is_dots_that_copy_the_password() -> None:
    rendered = format_note_content_for_view(content_html=BANK_NOTE, tags=BANK_TAGS, credentials=CredentialDisplay.DOTS)
    assert "Login for the bank: " in rendered
    assert " then 2FA" in rendered
    assert f'data-copy-value="{PASSWORD}">{CREDENTIAL_MASK}</span>' in rendered
    # Only the copy value holds it: never the page's text, never the delimiters.
    assert rendered.count(PASSWORD) == 1
    assert "((" not in rendered


def test_where_credentials_are_hidden_the_region_is_the_mask_with_nothing_to_copy() -> None:
    rendered = format_note_content_for_view(content_html=BANK_NOTE, tags=BANK_TAGS, credentials=CredentialDisplay.HIDDEN)
    assert PASSWORD not in rendered
    assert CREDENTIAL_MASK in rendered
    assert "Login for the bank: " in rendered


def test_an_export_that_includes_passwords_shows_it() -> None:
    rendered = format_note_content_for_view(content_html=BANK_NOTE, tags=BANK_TAGS, credentials=CredentialDisplay.SHOWN)
    assert f">{PASSWORD}</span>" in rendered


def test_another_renderer_named_with_it_never_draws_the_password() -> None:
    for tags in ("((@latex @password))", "((@password @json))"):
        rendered = format_note_content_for_view(content_html=BANK_NOTE, tags=tags, credentials=CredentialDisplay.HIDDEN)
        assert PASSWORD not in rendered, tags


def test_styles_named_with_it_style_the_dots() -> None:
    rendered = format_note_content_for_view(
        content_html=BANK_NOTE, tags="((@password @bold))", credentials=CredentialDisplay.DOTS)
    assert 'class="meta-credential-value meta-bold"' in rendered


def test_in_markdown_and_csv_notes_the_region_is_dots_too() -> None:
    markdown = format_note_content_for_view(
        content_html=BANK_NOTE, tags="((@password)) @markdown", credentials=CredentialDisplay.HIDDEN)
    assert PASSWORD not in markdown
    assert CREDENTIAL_MASK in markdown
    table = format_note_content_for_view(
        content_html=f"<div>site,password<br>bank,(({PASSWORD}))</div>", tags="((@password)) @csv",
        credentials=CredentialDisplay.HIDDEN)
    assert PASSWORD not in table
    assert "<td>bank</td>" in table


def test_the_ai_reads_the_rest_of_the_note_and_the_redaction_in_its_place() -> None:
    expected = f"Login for the bank: {SCOPED_PASSWORD_REDACTION} then 2FA"
    assert extract_agent_note_text(content_html=BANK_NOTE, tags=BANK_TAGS, title_lookup=_no_titles) == (expected, False)
    kept_text = f"Login for the bank: (({PASSWORD})) then 2FA"
    assert agent_note_text_from_kept_text(
        content_html=BANK_NOTE, kept_text=kept_text, tags=BANK_TAGS, title_lookup=_no_titles) == (expected, False)


def test_a_link_inside_the_region_is_not_looked_up_for_the_ai() -> None:
    linked = '<div>Key: ((<a href="https://example.com/secret-token">secret</a>)) done</div>'
    looked_up = []

    def lookup(url: str) -> None:
        looked_up.append(url)

    text, _ = agent_note_text_from_kept_text(
        content_html=linked, kept_text="Key: ((secret)) done", tags=BANK_TAGS, title_lookup=lookup)
    assert "secret-token" not in text
    assert looked_up == []


def test_redaction_follows_the_renderers_delimiters() -> None:
    tags = "((@password))"
    # Each region, delimiters and all; a run of three is no `((`.
    assert redact_scoped_passwords("a ((x)) b (((y))) c", tags) == f"a {SCOPED_PASSWORD_REDACTION} b (((y))) c"
    # A region never closed runs to the end: what follows the opener may be the password.
    assert redact_scoped_passwords("a ((half typed", tags) == f"a {SCOPED_PASSWORD_REDACTION}"
    # Each wrapper the tag bar gives @password.
    assert redact_scoped_passwords("[one] {two}", "[@password] {@password}") == (
        f"{SCOPED_PASSWORD_REDACTION} {SCOPED_PASSWORD_REDACTION}")
    # Other wrappers, and notes without the tag, are left alone.
    assert redact_scoped_passwords("((x)) [y]", "((@bold)) [@password]") == f"((x)) {SCOPED_PASSWORD_REDACTION}"
    assert redact_scoped_passwords("((x))", "bank") == "((x))"


def test_a_whole_password_note_is_still_withheld_whole() -> None:
    assert extract_agent_note_text(content_html=BANK_NOTE, tags="@password", title_lookup=_no_titles) == (
        "[REDACTED: @password]", True)


def test_a_region_never_closed_is_a_password_to_the_end() -> None:
    # Half typed, or a first line drawn alone (a folded note, a link) while it closes later.
    for content in (f"<div>Bank: (({PASSWORD}</div>", f"<div>Bank: (({PASSWORD}</div><div>more))</div>"):
        for credentials in (CredentialDisplay.DOTS, CredentialDisplay.HIDDEN):
            first_line = content.split("</div>")[0] + "</div>"
            rendered = format_note_content_for_view(content_html=first_line, tags=BANK_TAGS, credentials=credentials)
            assert f">{PASSWORD}<" not in rendered, rendered
            assert "Bank: " in rendered
            assert rendered.endswith("</span></div>"), rendered


def test_text_shown_elsewhere_shows_passwords_as_dots() -> None:
    # A first line in a link, a caption, a [[ suggestion, a backlink.
    assert text_shown_without_passwords(f"Bank: (({PASSWORD})) ok", BANK_TAGS) == f"Bank: {CREDENTIAL_MASK} ok"
    assert text_shown_without_passwords(f"Bank: (({PASSWORD}", BANK_TAGS) == f"Bank: {CREDENTIAL_MASK}"
    assert text_shown_without_passwords(PASSWORD, "@password") == CREDENTIAL_MASK
    assert text_shown_without_passwords("Bank: ((x))", "bank") == "Bank: ((x))"


def test_a_gallery_caption_shows_a_password_as_dots() -> None:
    note = SimpleNamespace(content=f"<div>Bank: (({PASSWORD}))<img src='x.png'></div>", tags=BANK_TAGS)
    assert _caption(note, lambda content_html: content_html) == f"Bank: {CREDENTIAL_MASK}"
    whole = SimpleNamespace(content=f"<div>{PASSWORD}<img src='x.png'></div>", tags="@password")
    assert _caption(whole, lambda content_html: content_html) == CREDENTIAL_MASK


def test_tag_suggestions_offer_no_word_of_a_note_with_a_password(monkeypatch) -> None:
    monkeypatch.setattr(tag_suggestions_module, "get_ontology", _EmptyOntology)
    content = f"<div>Bank: (({PASSWORD})) Sesame</div>"
    # The tag bar's ((@password)) reaches the server unwrapped, as @password.
    assert _new_tags_from_note_words(written=["@password"], prefix="S", content_html=content, limit=10).tags == []
    assert "Sesame" in _new_tags_from_note_words(written=["bank"], prefix="S", content_html=content, limit=10).tags
