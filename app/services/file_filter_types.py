"""Which kinds of file the Notes with Files menu lists (docs/ui/command-palette.md, Notes With
Files): the kinds notes use, most files first, and the standard kinds even with none."""

from __future__ import annotations

from collections import Counter

from app.services.file_kinds import STANDARD_FILE_KINDS
from app.services.file_registry import file_registry
from app.services.note_store import store as note_store


def list_file_filter_kinds() -> list[str]:
    """A file no note uses is not counted: choosing its kind would show an empty view."""
    counts: Counter[str] = Counter(
        kind for file_id, kind in file_registry.kinds_by_id().items() if note_store.note_ids_referencing({file_id})
    )
    other_kinds = sorted(kind for kind in counts if kind not in STANDARD_FILE_KINDS)
    # A stable sort: kinds with equally many files keep this order.
    return sorted([*STANDARD_FILE_KINDS, *other_kinds], key=lambda kind: -counts[kind])
