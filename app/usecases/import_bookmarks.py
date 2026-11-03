"""Importing a browser's bookmarks export (docs/ready-to-build/bookmark-import.md): each
website bookmark one root note at the top of the list, in the file's order, one line, its
title linked to its address; its folders as folder tags under the import's folder; created
when it was bookmarked. An import only adds (import-export-launch.md §5)."""

from __future__ import annotations

import html
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple

from app.services.bookmark_import import Bookmark, BookmarksFile, read_bookmarks
from app.services.input_errors import InputRejected
from app.services.obsidian_import.notes import folder_tag_of_names, import_folder_prefix, source_tag_for, tag_of_name
from app.services.obsidian_import.tree import NoteNode
from app.usecases.base import QueryCommand
from app.usecases.delete_subtree import apply_restore_records
from app.usecases.import_obsidian_vault import WrittenRoot, import_folder_exists, root_records

# The source tag's value: `imported:source=bookmarks:at=…`.
BOOKMARKS_SOURCE = "bookmarks"
_LINK_FORMAT = '<a href="{address}">{title}</a>'


@dataclass(frozen=True)
class _BookmarkPlan:
    bookmarks_file: BookmarksFile
    folder_prefix: str
    source_tag: str


def _plan(*, file_text: str, folder_prefix: str, imported_at: datetime) -> _BookmarkPlan:
    bookmarks_file = read_bookmarks(file_text)
    if len(bookmarks_file.bookmarks) == 0:
        raise InputRejected("That file holds no website bookmarks. Choose another export.")
    return _BookmarkPlan(
        bookmarks_file=bookmarks_file, folder_prefix=import_folder_prefix(folder_prefix),
        source_tag=source_tag_for(imported_at, BOOKMARKS_SOURCE),
    )


def _folder_tags(bookmark: Bookmark, folder_prefix: str) -> List[str]:
    """The folder tags of every folder holding the bookmark ('' left out: the top without a prefix)."""
    return [tag for tag in (folder_tag_of_names(folder, folder_prefix) for folder in bookmark.folders) if tag != ""]


def _tags(bookmark: Bookmark, *, folder_prefix: str, source_tag: str) -> Tuple[str, ...]:
    """Its folders' tags, its own tags (Firefox's), and the import's tag, each once."""
    own = [tag for tag in (tag_of_name(name) for name in bookmark.tags) if tag != ""]
    unique: Dict[str, str] = {}
    for tag in [*_folder_tags(bookmark, folder_prefix), *own, source_tag]:
        if tag.casefold() not in unique:
            unique[tag.casefold()] = tag
    return tuple(unique.values())


def _content(bookmark: Bookmark) -> str:
    """One line: the title linked to the address, which keeps the title as written and fetches
    none (docs/ui/content-formatting.md, Links In View Mode); without a title, the bare
    address, shown with its fetched title."""
    if bookmark.title == "":
        return html.escape(bookmark.address, quote=False)
    return _LINK_FORMAT.format(address=html.escape(bookmark.address), title=html.escape(bookmark.title, quote=False))


def _written(bookmark: Bookmark, *, plan: _BookmarkPlan, imported_at: datetime) -> WrittenRoot:
    """The bookmark's note, created when it was bookmarked (the import's time when the file
    doesn't say), updated when the browser last changed it."""
    created_at = imported_at
    if bookmark.added_at is not None:
        created_at = bookmark.added_at
    updated_at = created_at
    if bookmark.modified_at is not None and bookmark.modified_at > created_at:
        updated_at = bookmark.modified_at
    node = NoteNode(
        note_id=str(uuid.uuid4()), content_html=_content(bookmark),
        tags=_tags(bookmark, folder_prefix=plan.folder_prefix, source_tag=plan.source_tag), anchors=(), children=(),
    )
    return WrittenRoot(node=node, created_at=created_at, updated_at=updated_at)


@dataclass
class CmdPreviewBookmarkImport(QueryCommand):
    """What importing the bookmarks would do, for the walkthrough's File and Summary screens;
    writes nothing."""

    file_text: str
    folder_prefix: str
    imported_at: datetime

    def execute(self) -> Dict[str, object]:
        plan = _plan(file_text=self.file_text, folder_prefix=self.folder_prefix, imported_at=self.imported_at)
        bookmarks = plan.bookmarks_file.bookmarks
        # Folders as the browser has them (the top, and its own folders, are none).
        folders = {folder for bookmark in bookmarks for folder in bookmark.folders if len(folder) > 0}
        folder_tags = {tag for bookmark in bookmarks for tag in _folder_tags(bookmark, plan.folder_prefix)}
        return {
            "prefixFolder": plan.folder_prefix,
            "bookmarkCount": len(bookmarks),
            "folderCount": len(folders),
            "folderTagCount": len(folder_tags - {plan.folder_prefix}),
            # The ones that aren't website addresses, in the file's order: [title, why].
            "leftOut": [[left_out.title, left_out.kind] for left_out in plan.bookmarks_file.left_out],
        }


@dataclass
class CmdImportBookmarks(QueryCommand):
    """Import the bookmarks: every website bookmark a note at the top of the list, in the
    file's order."""

    file_text: str
    folder_prefix: str
    add_to_existing: bool
    token: str
    imported_at: datetime
    # The tags of the search context the file was dropped in (drop_context_tags), on each
    # bookmark's note; '' for an import from the menu.
    context_tags: str

    def execute(self) -> Dict[str, object]:
        plan = _plan(file_text=self.file_text, folder_prefix=self.folder_prefix, imported_at=self.imported_at)
        if import_folder_exists(plan.folder_prefix) and not self.add_to_existing:
            raise InputRejected(f"{plan.folder_prefix} already exists. Tick Add to it, or choose another name.")
        roots = [_written(bookmark, plan=plan, imported_at=self.imported_at) for bookmark in plan.bookmarks_file.bookmarks]
        apply_restore_records(root_records(roots, context_tags=self.context_tags), self.token)
        return {"status": "success", "noteCount": len(roots), "sourceTag": plan.source_tag}
