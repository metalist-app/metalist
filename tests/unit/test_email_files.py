"""Email files (.eml) as cards (docs/ui/references.md, "Email files")."""

from __future__ import annotations

import base64
import os
from email.message import EmailMessage
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import app.services.email_search_text as email_search_module
import app.services.search_text as search_text_module
import app.services.email_cards as email_cards_module
from app.services.email_files import email_attachment, is_email_file, read_email
from app.services.file_view import build_email_view


def _email(*, html: str | None, text: str, attachments: list[tuple[bytes, str, str, str | None]]) -> bytes:
    message = EmailMessage()
    message["From"] = "Ada Lovelace <ada@example.org>"
    message["To"] = "Grace Hopper <grace@example.org>"
    message["Cc"] = "Linus <linus@example.org>"
    message["Subject"] = "Réunion: the plan ✓"
    message["Date"] = "Thu, 29 Oct 2026 10:15:00 -0700"
    message.set_content(text)
    if html is not None:
        message.add_alternative(html, subtype="html")
    for payload, maintype, subtype, filename in attachments:
        message.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)
    return bytes(message)


PLAN = _email(
    html=(
        '<html><head><style>p{color:red}</style><script>alert(1)</script></head><body>'
        '<p style="color:red">Hi <b>Grace</b>,</p><p>The plan. <img src="cid:logo"> '
        '<img src="https://example.org/track.gif" width="1" height="1"> <img src="https://example.org/photo.jpg" width="120"></p>'
        '<p><a href="https://example.org/plan">Open the plan</a></p></body></html>'
    ),
    text="Hi Grace,\nThe plan.",
    attachments=[(b"%PDF-1.4 plan", "application", "pdf", "plan.pdf"), (b"%PDF-1.4 unnamed", "application", "pdf", None)],
)


def test_an_email_reads_as_its_card_shows_it() -> None:
    email = read_email(PLAN)

    assert email.is_readable
    assert (email.sender, email.sender_name, email.to, email.cc) == (
        "Ada Lovelace <ada@example.org>", "Ada Lovelace", "Grace Hopper <grace@example.org>", "Linus <linus@example.org>",
    )
    assert (email.date, email.subject) == ("Thu, 29 Oct 2026 10:15:00 -0700", "Réunion: the plan ✓")
    assert email.body_text == ""
    assert email.body_html == (
        '<p>Hi <b>Grace</b>,</p><p>The plan.   <img src="https://example.org/photo.jpg" width="120"></p>'
        '<p><a href="https://example.org/plan">Open the plan</a></p>\n'
    )
    # An unnamed attachment is called by its place and type.
    assert [(attachment.name, attachment.content_type, attachment.size_bytes) for attachment in email.attachments] == [
        ("plan.pdf", "application/pdf", 13), ("attachment-2.pdf", "application/pdf", 16),
    ]


def test_a_plain_email_reads_as_its_text() -> None:
    email = read_email(_email(html=None, text="Line one\nLine two", attachments=[]))

    assert (email.body_html, email.body_text) == ("", "Line one\nLine two\n")


def test_a_file_with_nothing_of_an_email_says_so() -> None:
    assert read_email(b"").is_readable is False
    plain = read_email(b"just some text")
    assert (plain.is_readable, plain.body_text) == (True, "just some text")


def test_an_attachment_is_its_bytes_and_name() -> None:
    attachment, payload = email_attachment(PLAN, 1)

    assert (attachment.name, payload) == ("attachment-2.pdf", b"%PDF-1.4 unnamed")
    with pytest.raises(IndexError, match="no attachment 2"):
        email_attachment(PLAN, 2)


@pytest.mark.parametrize(
    ("mime_type", "original_filename", "expected"),
    [("message/rfc822", "x.bin", True), ("application/octet-stream", "Mail.EML", True), ("text/plain", "notes.txt", False)],
)
def test_an_email_is_known_by_its_type_or_name(mime_type: str, original_filename: str, expected: bool) -> None:
    assert is_email_file(mime_type=mime_type, original_filename=original_filename) is expected


class _Registry:
    """The registry search text reads: one email, one other file, one picture."""

    def __init__(self) -> None:
        self.read: list[str] = []

    def referenced_file_names(self, text: str) -> list[tuple[str, str]]:
        return [(file_id, f"{file_id} name") for file_id in ("email", "other", "picture") if file_id in text]

    def thumbnail_kind_of(self, file_id: str) -> str:
        return {"email": "other", "other": "other", "picture": "image"}[file_id]

    def read_stored_file(self, file_id: str) -> object:
        self.read.append(file_id)
        names = {"email": ("message/rfc822", "plan.eml", PLAN), "other": ("application/zip", "x.zip", b"PK")}
        mime_type, original_filename, content = names[file_id]
        return SimpleNamespace(record=SimpleNamespace(mime_type=mime_type, original_filename=original_filename), content_bytes=content)


def test_a_note_is_found_by_the_words_of_an_email_it_references(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = _Registry()
    monkeypatch.setattr(search_text_module, "file_registry", registry)
    monkeypatch.setattr(email_search_module, "file_registry", registry)
    email_search_module.email_search_words.cache_clear()

    text = search_text_module.build_searchable_base_text_casefold("see ![[email]] ![[other]] ![[picture]]", "")

    for words in ("réunion: the plan ✓", "ada lovelace", "grace hopper", "linus", "open the plan", "plan.pdf", "attachment-2.pdf"):
        assert words in text, words
    assert "alert(1)" not in text
    # A picture is never read; a file of another kind is read once and adds nothing.
    assert registry.read == ["email", "other"]
    search_text_module.build_searchable_base_text_casefold("again ![[email]] ![[other]]", "")
    assert registry.read == ["email", "other"]
    email_search_module.email_search_words.cache_clear()


def test_http_routes_read_an_email_and_its_attachments(tmp_path: Path) -> None:
    eml_path = tmp_path / "plan.eml"
    eml_path.write_bytes(PLAN)
    script = f'''
from fastapi.testclient import TestClient
from app.main import app
from app.config import API_PREFIX
from app.services.tokens import token_service

token = token_service.create_token(client_info="fixture", owner_tab_id="tab", dek=None)
headers = {{"Authorization": "Bearer " + token, "X-Metalist-Tab-Id": "tab", "Origin": "http://localhost"}}
with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
    with open({str(eml_path)!r}, "rb") as eml:
        email_id = client.post(API_PREFIX + "/files/upload", headers=headers, files={{"file": ("plan.eml", eml.read(), "message/rfc822")}}).json()["file_id"]
    pdf_id = client.post(API_PREFIX + "/files/upload", headers=headers, files={{"file": ("lease.pdf", b"%PDF lease", "application/pdf")}}).json()["file_id"]
    read = client.get(API_PREFIX + f"/files/{{email_id}}/email", headers=headers)
    assert read.status_code == 200, read.text
    body = read.json()
    assert (body["isReadable"], body["fromName"], body["subject"], body["text"]) == (True, "Ada Lovelace", "Réunion: the plan ✓", ""), body
    assert [attachment["name"] for attachment in body["attachments"]] == ["plan.pdf", "attachment-2.pdf"], body
    attachment = client.get(API_PREFIX + f"/files/{{email_id}}/email/attachments/1", headers=headers)
    assert attachment.status_code == 200, attachment.text
    assert attachment.content == b"%PDF-1.4 unnamed"
    assert attachment.headers["content-disposition"] == "attachment; filename*=UTF-8''attachment-2.pdf"
    assert client.get(API_PREFIX + f"/files/{{email_id}}/email/attachments/2", headers=headers).status_code == 404
    assert client.get(API_PREFIX + f"/files/{{pdf_id}}/email", headers=headers).status_code == 404
    assert client.get(API_PREFIX + f"/files/{{email_id}}/email", headers={{"Origin": "http://localhost"}}).status_code == 401
print("ROUTES OK")
'''
    environment = dict(os.environ, METALIST_DATA_DIRECTORY=str(tmp_path), METALIST_ENVIRONMENT="production")
    result = subprocess.run([sys.executable, "-c", script], env=environment, capture_output=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, (result.stdout[-2000:], result.stderr[-3000:])
    assert "ROUTES OK" in result.stdout


# A web page saved whole (.mht, "Saved by Microsoft Internet Explorer 5") is read as an email:
# its pictures pointed at their old addresses, so opening it fetched some 200 from sites long
# gone, 16 seconds each, holding up every request of the page behind them; and its saved
# copies were listed as attachments (the maintainer, 2026-11-03). Its own copies show in
# place; a picture it didn't save shows nothing, and nothing is fetched.
LOGO = b"GIF89a-logo-bytes"
PHOTO = b"\xff\xd8\xff-photo-bytes"
SAVED_PAGE = (
    b"From: <Saved by Microsoft Internet Explorer 5>\r\n"
    b"Subject: ConsumerLab.com - Multivitamin review\r\n"
    b"Date: Mon, 30 Jan 2006 09:14:41 -0800\r\n"
    b"MIME-Version: 1.0\r\n"
    b'Content-Type: multipart/related; boundary="----=_NextPart"; type="text/html"\r\n'
    b"\r\n"
    b"------=_NextPart\r\n"
    b"Content-Type: text/html; charset=\"Windows-1252\"\r\n"
    b"Content-Transfer-Encoding: 7bit\r\n"
    b"Content-Location: http://www.consumerlab.com/results/multi.asp\r\n"
    b"\r\n"
    b'<html><body><p>Multivitamin review</p><img src="../images/logo.gif" alt="Logo">'
    b'<img src="http://www.consumerlab.com/images/photo.jpg"><img src="http://ads.example.com/banner.gif">'
    # A description holding a ">" (an old page's broken HTML): the picture is still found.
    b'<img alt="Fitness, Inc.</h1>" src="http://www.consumerlab.com/images/logo.gif">'
    b"</body></html>\r\n"
    b"------=_NextPart\r\n"
    b"Content-Type: image/gif\r\n"
    b"Content-Transfer-Encoding: base64\r\n"
    b"Content-Location: http://www.consumerlab.com/images/logo.gif\r\n"
    b"\r\n" + base64.b64encode(LOGO) + b"\r\n"
    b"------=_NextPart\r\n"
    b"Content-Type: image/jpeg\r\n"
    b"Content-Transfer-Encoding: base64\r\n"
    b"Content-Location: http://www.consumerlab.com/images/photo.jpg\r\n"
    b"\r\n" + base64.b64encode(PHOTO) + b"\r\n"
    b"------=_NextPart--\r\n"
)


def test_a_saved_web_pages_pictures_are_its_own_copies_and_nothing_is_fetched() -> None:
    page = read_email(SAVED_PAGE)
    assert "data:image/gif;base64," + base64.b64encode(LOGO).decode() in page.body_html
    assert "data:image/jpeg;base64," + base64.b64encode(PHOTO).decode() in page.body_html
    assert "http://" not in page.body_html, "no picture of the page is left to fetch from the web"
    assert "Multivitamin review" in page.body_html


def test_a_saved_web_pages_own_pictures_are_no_attachments() -> None:
    assert read_email(SAVED_PAGE).attachments == ()
    # An email's attachments are listed as before.
    assert [attachment.name for attachment in read_email(PLAN).attachments] == ["plan.pdf", "attachment-2.pdf"]


def test_an_emails_card_is_named_by_its_subject_and_sender_and_a_saved_page_by_its_title(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {"mail": ("plan.eml", PLAN), "page": ("review.mht", SAVED_PAGE)}
    monkeypatch.setattr(
        email_cards_module.file_registry, "read_stored_file",
        lambda file_id: SimpleNamespace(record=SimpleNamespace(original_filename=pages[file_id][0]), content_bytes=pages[file_id][1]),
    )
    email_cards_module.email_card_name.cache_clear()
    assert email_cards_module.email_card_name("mail") == "Réunion: the plan ✓ · Ada Lovelace"
    assert email_cards_module.email_card_name("page") == "ConsumerLab.com - Multivitamin review"
    email_cards_module.email_card_name.cache_clear()


def test_the_viewer_shows_an_email_its_headers_body_and_attachments() -> None:
    view, email = build_email_view(PLAN)
    assert view.status == "ready" and "The plan." in view.content_html
    assert (email.subject, email.sender_name) == ("Réunion: the plan ✓", "Ada Lovelace")
    assert [attachment.name for attachment in email.attachments] == ["plan.pdf", "attachment-2.pdf"]
