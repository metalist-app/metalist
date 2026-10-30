"""Email files (.eml): a dropped or attached email shows as a card (docs/ui/references.md,
"Email files"; agreed 2026-10-29).

The file is stored as it came. Drawing it, the browser asks for it read here: its
From, To, Cc, Date and Subject decoded, its body (the HTML version sanitized as a
note's stored HTML is, else the plain text), and its attachments by name, type and
size, each downloadable. Nothing in the email runs or loads unasked: scripts,
styles and inline (cid:) pictures are dropped, as are 1-pixel tracking pictures.
"""

from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import PurePath

from app.security.note_html import sanitize_note_html

EMAIL_MIME_TYPE = "message/rfc822"
EMAIL_EXTENSION = ".eml"
EMAIL_BADGE = "EML"
# The parts a body is read from, best first.
_BODY_PREFERENCE = ("html", "plain")
_HTML_SUBTYPE = "html"
# A picture this small or smaller on either side shows nothing: it only tells the sender
# the email was opened.
_TRACKING_PIXEL_MAX = 1
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_SRC_RE = re.compile(r'\ssrc="[^"]+"', re.IGNORECASE)
_SIZE_RE = re.compile(r'\s(?:width|height)="(?P<size>\d+)"', re.IGNORECASE)


def is_email_file(*, mime_type: str, original_filename: str) -> bool:
    """An email by its type or its name: emails uploaded before cards existed count too."""
    if not isinstance(mime_type, str) or not isinstance(original_filename, str):
        raise TypeError("is_email_file requires mime_type and original_filename strings")
    if mime_type.strip().lower() == EMAIL_MIME_TYPE:
        return True
    return PurePath(original_filename).suffix.lower() == EMAIL_EXTENSION


@dataclass(frozen=True, slots=True)
class EmailAttachment:
    name: str
    content_type: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ReadEmail:
    """An email as its card shows it. `body_html` is sanitized and set for an HTML email;
    `body_text` for a plain one; both are "" for an email with no body. `is_readable` is
    False for a file with none of an email's headers or a body: its card says so."""

    is_readable: bool
    sender: str
    # The sender's name, or the address when the email gives no name: a folded card's line.
    sender_name: str
    to: str
    cc: str
    date: str
    subject: str
    body_html: str
    body_text: str
    attachments: tuple[EmailAttachment, ...]


def read_email(content_bytes: bytes) -> ReadEmail:
    if not isinstance(content_bytes, bytes):
        raise TypeError("content_bytes must be bytes")
    message = _parse(content_bytes)
    headers = {name: _header(message, name) for name in ("From", "To", "Cc", "Date", "Subject")}
    body_html, body_text = _body(message)
    attachments = tuple(
        EmailAttachment(name=_attachment_name(part, index), content_type=part.get_content_type(), size_bytes=len(_payload(part)))
        for index, part in enumerate(message.iter_attachments())
    )
    # Readable when it has any of an email's headers, or a body.
    is_readable = any(value != "" for value in [*headers.values(), body_html, body_text])
    return ReadEmail(
        is_readable=is_readable,
        sender=headers["From"], sender_name=_name_of(headers["From"]), to=headers["To"], cc=headers["Cc"], date=headers["Date"], subject=headers["Subject"],
        body_html=body_html, body_text=body_text, attachments=attachments,
    )


def email_attachment(content_bytes: bytes, index: int) -> tuple[EmailAttachment, bytes]:
    """The attachment at `index` (counted from 0, as read_email lists them) and its bytes."""
    if not isinstance(content_bytes, bytes):
        raise TypeError("content_bytes must be bytes")
    parts = list(_parse(content_bytes).iter_attachments())
    if not isinstance(index, int) or not 0 <= index < len(parts):
        raise IndexError(f"The email has no attachment {index}")
    part = parts[index]
    payload = _payload(part)
    return EmailAttachment(name=_attachment_name(part, index), content_type=part.get_content_type(), size_bytes=len(payload)), payload


def _parse(content_bytes: bytes) -> EmailMessage:
    message = BytesParser(policy=policy.default).parsebytes(content_bytes)
    assert isinstance(message, EmailMessage), "the default policy reads an EmailMessage"
    return message


# A header decoded (=?UTF-8?B?...?= read as text), or "" when the email has none.
def _header(message: EmailMessage, name: str) -> str:
    if name not in message:
        return ""
    return str(message[name]).strip()


def _name_of(sender: str) -> str:
    name, address = parseaddr(sender)
    if name.strip() != "":
        return name.strip()
    return address


def _body(message: EmailMessage) -> tuple[str, str]:
    part = message.get_body(preferencelist=_BODY_PREFERENCE)
    if part is None:
        return "", ""
    content = part.get_content()
    assert isinstance(content, str), "a text part's content is text"
    if part.get_content_subtype() == _HTML_SUBTYPE:
        return _without_hidden_pictures(sanitize_note_html(content)), ""
    return "", content


# Pictures with no source left (an inline cid: picture the sanitizer emptied) or a
# tracking pixel's size show nothing: they are dropped.
def _without_hidden_pictures(body_html: str) -> str:
    def kept(match: re.Match[str]) -> str:
        tag = match.group(0)
        if _SRC_RE.search(tag) is None:
            return ""
        if any(int(size.group("size")) <= _TRACKING_PIXEL_MAX for size in _SIZE_RE.finditer(tag)):
            return ""
        return tag

    return _IMG_TAG_RE.sub(kept, body_html)


# An attachment's name as the email gives it. An email may leave one unnamed: it is
# called by its place and type (attachment-2.pdf), to show and to save.
def _attachment_name(part: EmailMessage, index: int) -> str:
    name = part.get_filename()
    if name is not None and name.strip() != "":
        return name
    extension = mimetypes.guess_extension(part.get_content_type())
    if extension is None:
        return f"attachment-{index + 1}"
    return f"attachment-{index + 1}{extension}"


def _payload(part: EmailMessage) -> bytes:
    payload = part.get_payload(decode=True)
    if payload is None:
        # A message attached whole (message/rfc822) is its own bytes.
        return part.as_bytes()
    assert isinstance(payload, bytes), "a decoded payload is bytes"
    return payload
