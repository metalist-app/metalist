"""Notes with Links (docs/ui/command-palette.md, Notes with Links; agreed with the maintainer,
2026-11-21): which notes a tab keeps when its filter is about links. A note is judged by its own
text, as Notes with Files judges it: a [[note]] link or ![[note]] embed in it.

- linked: the notes another note links to or embeds (the ones with backlinks);
- links: the notes that link to or embed a note that exists;
- broken-links: the notes with a link or embed that leads nowhere, to no note and no file.

A file is no note: Notes with Files finds the notes holding one."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from typing import Set

from app.services.file_kinds import FILE_FILTER_ANY, LINK_FILTER_BROKEN, LINK_FILTER_LINKED, LINK_FILTER_LINKS, is_link_filter_kind
from app.services.file_registry import file_registry
from app.services.note_store import store as note_store


def notes_kept_by_link_filter(
    kind: str, *, targets_by_note: Mapping[str, AbstractSet[str]], note_ids: AbstractSet[str], file_ids: AbstractSet[str],
) -> Set[str]:
    """The notes of note_ids the filter keeps. targets_by_note: what each note's own text
    references (never itself); a note that is gone, in it or not, is kept by none."""
    assert is_link_filter_kind(kind), f"not a Notes with Links filter: {kind!r}"
    linking = {note_id: targets for note_id, targets in targets_by_note.items() if note_id in note_ids}
    if kind == LINK_FILTER_LINKED:
        return {target for targets in linking.values() for target in targets if target in note_ids}
    if kind == LINK_FILTER_LINKS:
        return {note_id for note_id, targets in linking.items() if not targets.isdisjoint(note_ids)}
    assert kind == LINK_FILTER_BROKEN
    return {
        note_id for note_id, targets in linking.items()
        if any(target not in note_ids and target not in file_ids for target in targets)
    }


def link_filter_note_ids(kind: str) -> Set[str]:
    """The notes the vault's filter of that kind keeps, as it stands now."""
    targets_by_note = note_store.link_targets_by_note()
    return notes_kept_by_link_filter(
        kind, targets_by_note=targets_by_note, note_ids=set(note_store.snapshot()),
        file_ids=file_registry.file_ids_of_kind(FILE_FILTER_ANY),
    )
