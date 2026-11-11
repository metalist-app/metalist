"""An email file's words for the search index (docs/ui/search-semantics.md): a note
that embeds or links an email is found by the email's subject, sender, recipients,
body and attachment names, as it is by the file's name (search_text.py).

Each email is read once and its words kept in a sensitive cache, emptied when the
vault locks. An email's content never changes in place (only diagrams are edited),
so a file's words stay right for as long as the file exists.
"""

from __future__ import annotations

from app.security.sensitive_cache import sensitive_lru_cache
from app.services.email_files import is_email_file, read_email
from app.services.file_registry import file_registry
from app.utils.byte_sizes import MIB
from app.utils.text_utils import strip_html

# What an email can be stored as (file_storage._derive_thumbnail_kind): a file of any
# other kind is no email and is not read.
EMAIL_THUMBNAIL_KINDS = frozenset({"other", "text"})
_EMAIL_WORDS_MEMO_ENTRIES = 1024
_EMAIL_WORDS_MEMO_MIB = 16


@sensitive_lru_cache(maxsize=_EMAIL_WORDS_MEMO_ENTRIES, max_bytes=_EMAIL_WORDS_MEMO_MIB * MIB)
def email_search_words(file_id: str) -> str:
    """The email's searchable words, or "" for a file that is no email."""
    if not isinstance(file_id, str) or file_id == "":
        raise TypeError("file_id must be a non-empty string")
    stored = file_registry.read_stored_file(file_id)
    # Too large to hold in memory: found and shown by its file name alone.
    if stored is None:
        return ""
    record = getattr(stored, "record")
    if not is_email_file(mime_type=getattr(record, "mime_type"), original_filename=getattr(record, "original_filename")):
        return ""
    email = read_email(getattr(stored, "content_bytes"))
    body = email.body_text
    if email.body_html != "":
        body = strip_html(email.body_html)
    parts = [email.subject, email.sender, email.to, email.cc, body, *(attachment.name for attachment in email.attachments)]
    return " ".join(part for part in parts if part != "")
