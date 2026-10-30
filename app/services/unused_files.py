"""Files no note uses (docs/ui/command-palette.md, `Trim Unused Files…` and `Trim Reminder`).

A file is unused when no live note's text references it and nothing could bring such a
reference back: no tab's undo or redo history names it (a deleted note restored by ⌘Z),
and no tab's copied note does (a paste). Trim deletes exactly these, and the trim reminder
totals them, so the card and the confirmation always agree (agreed 2026-10-27)."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass

from app.services.file_registry import referenced_file_ids
from app.services.file_storage import (
    TrimUnusedFilesResult,
    stored_size_of_files,
    trim_unused_files,
    unused_file_ids,
)
from app.services.sync import all_clipboards
from app.services.undo_state import undo_history_operations


@dataclass(frozen=True)
class UnusedFiles:
    count: int
    size_bytes: int


def _texts_in(value: object) -> list[str]:
    """Every string inside an undo operation or copied note: note text, and file ids
    (a file's earlier content kept for undo names its file)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _texts_in(item)]
    if isinstance(value, (list, tuple, frozenset, set)):
        return [text for item in value for text in _texts_in(item)]
    if is_dataclass(value) and not isinstance(value, type):
        return [text for field in fields(value) for text in _texts_in(getattr(value, field.name))]
    return []


def files_undo_or_paste_could_restore() -> frozenset[str]:
    """Ids named by any tab's undo or redo history or copied note: referenced in a text,
    or a text that is itself an id."""
    texts = _texts_in([undo_history_operations(), all_clipboards()])
    return frozenset(texts) | frozenset(file_id for text in texts for file_id in referenced_file_ids(text))


def unused_files() -> UnusedFiles:
    file_ids = unused_file_ids(kept_file_ids=files_undo_or_paste_could_restore())
    return UnusedFiles(count=len(file_ids), size_bytes=stored_size_of_files(file_ids))


def trim() -> TrimUnusedFilesResult:
    return trim_unused_files(kept_file_ids=files_undo_or_paste_could_restore())
