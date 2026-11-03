"""An email's card (docs/ui/references.md, "Email files"; the maintainer, 2026-11-03): an email
file is a card as any file is, named by its subject and sender (a saved web page by its title
alone: its sender is the browser that saved it), with Open showing it in the viewer and Download.
Nothing of it is drawn in the note. Each email is read once and its name kept in a sensitive
cache, emptied when the vault locks; an email's content never changes in place."""

from __future__ import annotations

from app.security.sensitive_cache import sensitive_lru_cache
from app.services.email_files import is_saved_page_name, read_email
from app.services.file_registry import file_registry
from app.utils.byte_sizes import MIB

_CARD_NAME_MEMO_ENTRIES = 1024
_CARD_NAME_MEMO_MIB = 1
_NAME_SEPARATOR = " · "


@sensitive_lru_cache(maxsize=_CARD_NAME_MEMO_ENTRIES, max_bytes=_CARD_NAME_MEMO_MIB * MIB)
def email_card_name(file_id: str) -> str:
    """The email's subject and sender's name ("" for one with neither: its card shows the
    file's name)."""
    if not isinstance(file_id, str) or file_id == "":
        raise TypeError("file_id must be a non-empty string")
    stored = file_registry.read_stored_file(file_id)
    record = getattr(stored, "record")
    email = read_email(getattr(stored, "content_bytes"))
    parts = [email.subject]
    if not is_saved_page_name(getattr(record, "original_filename")):
        parts.append(email.sender_name)
    return _NAME_SEPARATOR.join(part for part in parts if part != "")
