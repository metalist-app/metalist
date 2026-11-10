"""Files filter: a tab shows only the notes that reference an attached file, or one of
a kind (an image, a PDF, a Markdown file, or any other file by its extension), with the notes above them
(docs/ui/command-palette.md, Notes With Files).

A note matches by its own text: a [[file]] link or ![[file]] embed in it. Each
file's kind comes from what the file registry already holds: its thumbnail kind
and its name.
"""

from __future__ import annotations

from pathlib import PurePosixPath
import re

from app.services.input_errors import InputRejected

FILE_KIND_IMAGE = "image"
FILE_KIND_PDF = "pdf"
FILE_KIND_MARKDOWN = "markdown"
# A file whose name has no extension. Any other file's kind is its extension: ".zip".
FILE_KIND_NO_EXTENSION = "no-extension"
# The filter for every attached file, whatever its kind.
FILE_FILTER_ANY = "any"
# What a request sends to show every note again (no filter).
FILE_FILTER_NONE = "none"
# In the order the menus list them with equally many files.
STANDARD_FILE_KINDS = (FILE_KIND_IMAGE, FILE_KIND_PDF, FILE_KIND_MARKDOWN)
_NAMED_FILTER_KINDS = frozenset({FILE_FILTER_ANY, FILE_KIND_NO_EXTENSION, *STANDARD_FILE_KINDS})
# Longer, or with other characters, it is the end of a sentence in a name ("v1.final draft").
_EXTENSION_KIND = re.compile(r"\.[a-z0-9_+-]{1,12}")

# A file's thumbnail kind (file_storage._derive_thumbnail_kind) already marks
# images and PDFs; Markdown files are known by their name.
_THUMBNAIL_KINDS_FILTERED = {"image": FILE_KIND_IMAGE, "pdf": FILE_KIND_PDF}
_MARKDOWN_EXTENSIONS = (".md", ".markdown")


def file_kind_of(*, thumbnail_kind: str, file_name: str) -> str:
    """The kind a file is filtered by: image, pdf, markdown, its extension, or no-extension."""
    if not isinstance(thumbnail_kind, str) or not isinstance(file_name, str):
        raise TypeError("file_kind_of requires thumbnail_kind and file_name strings")
    if thumbnail_kind in _THUMBNAIL_KINDS_FILTERED:
        return _THUMBNAIL_KINDS_FILTERED[thumbnail_kind]
    name = file_name.strip().lower()
    if name.endswith(_MARKDOWN_EXTENSIONS):
        return FILE_KIND_MARKDOWN
    extension = PurePosixPath(name).suffix
    if _EXTENSION_KIND.fullmatch(extension) is None:
        return FILE_KIND_NO_EXTENSION
    return extension


def is_file_filter_kind(kind: str) -> bool:
    if kind in _NAMED_FILTER_KINDS:
        return True
    return _EXTENSION_KIND.fullmatch(kind) is not None


def make_file_filter(kind: str) -> str:
    """A validated filter kind; a request or saved tab state with another is rejected."""
    if not is_file_filter_kind(kind):
        raise InputRejected(f"Unknown file type to filter on: {kind!r}")
    return kind
