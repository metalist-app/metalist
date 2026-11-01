"""Finding what a link or embed of an imported vault points at (PLAN.md, slice 2; mapping
rows D1-D9, E1-E12): a note (its file, then the heading or block in it) or another file of
the vault, as Obsidian finds it: the path as written, from the vault's top or from the
linking file's folder, then the file whose path ends with it, the shortest such path first;
then a file's frontmatter alias."""

from __future__ import annotations

import posixpath
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, List, TypeVar

from app.services.obsidian_import.links import LinkReference
from app.services.obsidian_import.notes import PlannedNote
from app.services.obsidian_import.tree import NoteNode, block_anchor, find_anchor, heading_anchor

_MARKDOWN_SUFFIX = ".md"
_SEPARATOR = "/"
_CURRENT_FOLDER = "."
_Target = TypeVar("_Target")


@dataclass(frozen=True)
class NoteTarget:
    """The note a link reaches, and whether it is the whole note in place of the heading or
    block the link named (No splitting, or no such heading)."""

    note: NoteNode
    is_whole_note_for_part: bool


class VaultIndex:
    """The vault's notes and other files by path, and its notes by alias."""

    def __init__(self, planned: List[PlannedNote], other_files: List[PurePosixPath]):
        self._notes: Dict[str, PlannedNote] = {_key(_without_markdown_suffix(note.source_path)): note for note in planned}
        self._files: Dict[str, PurePosixPath] = {_key(str(path)): path for path in other_files}
        self._aliases: Dict[str, PlannedNote] = {}
        for note in planned:
            for alias in note.aliases:
                # Two files with one alias: the first in the file list has it, as a link finds one.
                if _key(alias) not in self._aliases:
                    self._aliases[_key(alias)] = note

    def note(self, reference: LinkReference, *, from_path: str) -> NoteTarget | None:
        """The note reference points at, from the file at from_path; None when no note."""
        planned = self._planned_note(reference, from_path=from_path)
        if planned is None:
            return None
        anchor = ""
        if reference.heading != "":
            anchor = heading_anchor(reference.heading)
        if reference.block_id != "":
            anchor = block_anchor(reference.block_id)
        if anchor == "":
            return NoteTarget(note=planned.root, is_whole_note_for_part=False)
        found = find_anchor(planned.root, anchor)
        if found is None:
            return NoteTarget(note=planned.root, is_whole_note_for_part=True)
        # A file kept whole is one note: a link to a block in it reaches all of it, not the
        # block alone (a link to its title heading is to all of it anyway).
        is_kept_whole = len(planned.root.children) == 0
        is_title = reference.heading != "" and len(planned.root.anchors) > 0 and planned.root.anchors[0] == anchor
        return NoteTarget(note=found, is_whole_note_for_part=is_kept_whole and not is_title)

    def file(self, reference: LinkReference, *, from_path: str) -> PurePosixPath | None:
        """The other file reference points at; None when there is none."""
        if reference.target == "":
            return None
        found = _lookup(self._files, reference.target, from_path=from_path, is_markdown_link=reference.is_markdown_link)
        if found is None:
            # An Excalidraw drawing is linked to without its .md.
            found = _lookup(
                self._files, reference.target + _MARKDOWN_SUFFIX, from_path=from_path,
                is_markdown_link=reference.is_markdown_link,
            )
        return found

    def _planned_note(self, reference: LinkReference, *, from_path: str) -> PlannedNote | None:
        if reference.target == "":
            return self._notes[_key(_without_markdown_suffix(from_path))]
        target = _without_markdown_suffix(reference.target)
        found = _lookup(self._notes, target, from_path=from_path, is_markdown_link=reference.is_markdown_link)
        if found is None and not reference.is_markdown_link and _key(target) in self._aliases:
            return self._aliases[_key(target)]
        return found


def _lookup(table: Dict[str, _Target], target: str, *, from_path: str, is_markdown_link: bool) -> _Target | None:
    """The entry of table at target: as written from the vault's top or the linking file's
    folder (a Markdown link or a ./ path tries the folder first), else the shortest path
    ending with it."""
    from_vault_top = posixpath.normpath(target.lstrip(_SEPARATOR))
    from_folder = posixpath.normpath(posixpath.join(posixpath.dirname(from_path), target))
    tries = [from_vault_top, from_folder]
    if is_markdown_link or target.startswith(_CURRENT_FOLDER):
        tries = [from_folder, from_vault_top]
    for path in tries:
        if _key(path) in table:
            return table[_key(path)]
    ending = _SEPARATOR + _key(from_vault_top)
    matches = sorted((key for key in table if key.endswith(ending)), key=lambda key: (key.count(_SEPARATOR), key))
    if len(matches) == 0:
        return None
    return table[matches[0]]


def _without_markdown_suffix(path: str) -> str:
    if path.casefold().endswith(_MARKDOWN_SUFFIX):
        return path[:-len(_MARKDOWN_SUFFIX)]
    return path


def _key(path: str) -> str:
    """How paths are compared: Obsidian ignores case, and file systems differ in composing accents."""
    return unicodedata.normalize("NFC", path).casefold()
