"""Importing an Obsidian vault, or a plain folder of Markdown files, into the vault in use (PLAN.md, slices 1 and 1c;
docs/ready-to-build/import-export-launch.md §2, §5): every file planned first, then all of
it written at once, as new root notes at the top of the list, in the order of Obsidian's file list.
The vault's folder is only read."""

from __future__ import annotations

import html
import mimetypes
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Dict, List, Tuple

from app.services.file_storage import create_file
from app.services.file_text_preview import plain_text_to_note_html
from app.services.input_errors import InputRejected
from app.services.obsidian_import.links import LinkReference, with_tokens_replaced
from app.services.obsidian_import.notes import PlannedNote, folder_tag_for, plan_file_note, source_tag_for
from app.services.obsidian_import.resolve import VaultIndex
from app.services.obsidian_import.sources import IMPORT_SOURCES, ImportSource
from app.services.obsidian_import.tree import CONTENT_FORMATS, SPLIT_MODES, NoteNode, count_notes
from app.services.obsidian_import.vault import NOT_UTF8_REASON, VaultContents, read_vault
from app.services.store import store
from app.upload_limits import MAX_ATTACHMENT_BYTES
from app.usecases.base import QueryCommand
from app.usecases.delete_subtree import apply_restore_records

# The root notes' parent: the top of the list.
_TOP_LEVEL = None
# Files that are content of their own, not attachments: each comes in as a file in a note
# of its own, linked to or not (mapping E11, E12, J4).
_KEPT_FILE_SUFFIXES = (".canvas", ".base", ".excalidraw.md")
# A file whose type the name doesn't tell is stored as bytes, as a browser would send it.
_UNKNOWN_MIME_TYPE = "application/octet-stream"
# How Obsidian shows a link to a heading without text of its own: "Note > Heading".
_HEADING_LINK_TEXT_FORMAT = "{note} > {heading}"
_EMBED_MARK = "!"


@dataclass(frozen=True)
class _Resolved:
    """What one link or embed of a file reaches: a note, or another file of the vault, or
    neither (a missing note: it stays as written)."""

    reference: LinkReference
    source_path: str
    note: NoteNode | None
    file_path: PurePosixPath | None
    is_whole_note_for_part: bool


@dataclass
class CmdImportObsidianVault(QueryCommand):
    """Import the folder at folder_path, an Obsidian vault or a plain Markdown folder as source
    says (the developer version, PLAN.md, slices 1 and 1c), each file split and written as
    split_mode and content_format say."""

    source: str
    folder_path: str
    split_mode: str
    content_format: str
    token: str
    imported_at: datetime

    def execute(self) -> Dict[str, object]:
        plan = _plan_import(
            source_key=self.source, folder_path=self.folder_path, split_mode=self.split_mode,
            content_format=self.content_format, imported_at=self.imported_at,
        )
        folder, vault, planned, source_tag = plan.folder, plan.vault, plan.planned, plan.source_tag
        linked = _linked(folder, vault, planned, source_tag=source_tag, token=self.token)
        planned = linked.planned
        note_count = sum(count_notes(note.root) for note in planned) + len(linked.kept)
        roots = [
            *((note.source_path, _Written(node=note.root, created_at=note.created_at, updated_at=note.updated_at)) for note in planned),
            *linked.kept,
        ]
        roots.sort(key=lambda pair: _file_list_key(PurePosixPath(pair[0])))
        # The files at the top of the list as Obsidian's file list orders them (no import
        # report: the maintainer, 2026-11-01).
        records = _records([written for _path, written in roots])
        apply_restore_records(records, self.token)
        return {
            "status": "success", "noteCount": note_count,
            # Every note of this import has it: the wizard opens a search context on it.
            "sourceTag": source_tag,
        }


@dataclass(frozen=True)
class _ImportPlan:
    """A folder read and every file planned as notes, nothing stored or written yet."""

    source: ImportSource
    folder: Path
    vault: VaultContents
    planned: List[PlannedNote]
    source_tag: str


def _plan_import(*, source_key: str, folder_path: str, split_mode: str, content_format: str, imported_at: datetime) -> _ImportPlan:
    if split_mode not in SPLIT_MODES or content_format not in CONTENT_FORMATS:
        raise InputRejected("Choose how to split the notes and what to write them in.")
    assert source_key in IMPORT_SOURCES, f"unknown import source {source_key!r}"
    source = IMPORT_SOURCES[source_key]
    folder = Path(folder_path)
    if not folder.is_absolute():
        raise InputRejected(f"Choose the {source.folder_word}'s folder with Choose Folder.")
    if not folder.is_dir():
        raise InputRejected(f"There is no folder at {folder}. Choose the {source.folder_word}'s folder again.")
    vault = read_vault(folder, reads_line_break_setting=source.follows_obsidian_line_breaks)
    if len(vault.markdown_files) == 0:
        raise InputRejected(f"{folder} holds no Markdown files. Choose a folder that does.")
    source_tag = source_tag_for(imported_at, source.key)
    planned = [
        plan_file_note(
            vault_file, uses_strict_line_breaks=vault.uses_strict_line_breaks, source_tag=source_tag,
            split_mode=split_mode, content_format=content_format,
        )
        for vault_file in vault.markdown_files
    ]
    return _ImportPlan(source=source, folder=folder, vault=vault, planned=planned, source_tag=source_tag)


@dataclass
class CmdPreviewImport(QueryCommand):
    """What importing the folder would do, as the import wizard's summary shows it before
    anything is written (PLAN.md, phase 2): counts, and what would appear differently. Reads
    the folder and plans every file; stores and writes nothing."""

    source: str
    folder_path: str
    split_mode: str
    content_format: str
    imported_at: datetime

    def execute(self) -> Dict[str, object]:
        plan = _plan_import(
            source_key=self.source, folder_path=self.folder_path, split_mode=self.split_mode,
            content_format=self.content_format, imported_at=self.imported_at,
        )
        index = VaultIndex(plan.planned, plan.vault.other_files)
        resolved = [
            _resolve(index, reference, from_path=note.source_path) for note in plan.planned for reference in note.links
        ]
        kept_paths = [path for path in plan.vault.other_files if _is_kept_file(path)]
        linked_paths = {item.file_path for item in resolved if item.file_path is not None}
        storable = {path for path in {*linked_paths, *kept_paths} if (plan.folder / Path(path)).stat().st_size <= MAX_ATTACHMENT_BYTES}
        findings = [note.findings for note in plan.planned]
        kept_note_count = sum(1 for path in kept_paths if path in storable)
        return {
            "fileCount": len(plan.planned),
            "noteCount": sum(count_notes(note.root) for note in plan.planned) + kept_note_count,
            # The notes at the top of the list (each file's, and each kept file's), the report aside.
            "rootNoteCount": len(plan.planned) + kept_note_count,
            "attachmentCount": sum(1 for path in linked_paths if path in storable and not _is_kept_file(path)),
            "folderTagCount": len({note.folder_tag for note in plan.planned if note.folder_tag != ""}),
            "filesWithCommentsCount": sum(1 for finding in findings if finding.has_comments),
            "blockIdCount": sum(finding.block_id_count for finding in findings),
            "calloutCount": sum(finding.callout_count for finding in findings),
            "missingLinkCount": sum(1 for item in resolved if item.note is None and item.file_path is None),
            "unreadableFileCount": sum(1 for entry in plan.vault.skipped if entry.reason == NOT_UTF8_REASON),
            "unusedAttachmentCount": sum(
                1 for path in plan.vault.other_files if path not in linked_paths and not _is_kept_file(path)
            ),
        }


@dataclass(frozen=True)
class _Written:
    """A root note to write with its subtree, and its times."""

    node: NoteNode
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class _Linked:
    """The files' notes with their links made MetaList's, and the notes of Canvas, Base and
    Excalidraw files (with their paths)."""

    planned: List[PlannedNote]
    kept: List[Tuple[str, _Written]]


def _linked(folder: Path, vault: VaultContents, planned: List[PlannedNote], *, source_tag: str, token: str) -> _Linked:
    """Every link and embed resolved, and the files they reach stored (with the Canvas, Base
    and Excalidraw files, which come in linked to or not)."""
    index = VaultIndex(planned, vault.other_files)
    resolved = {note.source_path: [_resolve(index, reference, from_path=note.source_path) for reference in note.links] for note in planned}
    kept_paths = [path for path in vault.other_files if _is_kept_file(path)]
    linked_paths = {item.file_path for items in resolved.values() for item in items if item.file_path is not None}
    file_ids, _too_large = _store_files(folder, sorted({*linked_paths, *kept_paths}, key=_path_key), token=token)
    return _Linked(
        planned=[
            replace(note, root=_with_links(note.root, _replacements(resolved[note.source_path], file_ids)))
            for note in planned
        ],
        kept=[_kept_file_note(folder, path, file_ids[path], source_tag=source_tag) for path in kept_paths if path in file_ids],
    )


def _resolve(index: VaultIndex, reference: LinkReference, *, from_path: str) -> _Resolved:
    target = index.note(reference, from_path=from_path)
    if target is not None:
        return _Resolved(
            reference=reference, source_path=from_path, note=target.note, file_path=None,
            is_whole_note_for_part=target.is_whole_note_for_part,
        )
    return _Resolved(
        reference=reference, source_path=from_path, note=None, file_path=index.file(reference, from_path=from_path),
        is_whole_note_for_part=False,
    )


def _reaches(item: _Resolved, file_ids: Dict[PurePosixPath, str]) -> bool:
    """Whether item reaches a note, or a file that was stored."""
    if item.note is not None:
        return True
    return item.file_path is not None and item.file_path in file_ids


def _replacements(items: List[_Resolved], file_ids: Dict[PurePosixPath, str]) -> Dict[int, str]:
    """Each link token's HTML: MetaList's reference (`[[UUID]]`, `[[UUID|text]]`, `![[UUID]]`),
    or the link as written when it reaches nothing."""
    replacements: Dict[int, str] = {}
    for token_index, item in enumerate(items):
        reference = item.reference
        if not _reaches(item, file_ids):
            replacements[token_index] = html.escape(reference.written, quote=False)
            continue
        text = reference.text
        if item.note is not None:
            target_id = item.note.note_id
            if reference.is_embed:
                # A note's embed shows the note; text there is unused (docs/ui/references.md).
                text = ""
            elif text == "" and item.is_whole_note_for_part and reference.heading != "":
                text = _HEADING_LINK_TEXT_FORMAT.format(note=reference.target, heading=reference.heading).strip(" >")
        else:
            assert item.file_path is not None
            target_id = file_ids[item.file_path]
            if reference.is_embed and reference.is_markdown_link:
                # `![alt](photo.png)`: the alt text is no size.
                text = ""
        mark = ""
        if reference.is_embed:
            mark = _EMBED_MARK
        shown = ""
        if text != "":
            shown = f"|{text}"
        replacements[token_index] = html.escape(f"{mark}[[{target_id}{shown}]]", quote=False)
    return replacements


def _with_links(node: NoteNode, replacements: Dict[int, str]) -> NoteNode:
    return replace(
        node, content_html=with_tokens_replaced(node.content_html, replacements),
        children=tuple(_with_links(child, replacements) for child in node.children),
    )


def _store_files(folder: Path, paths: List[PurePosixPath], *, token: str) -> Tuple[Dict[PurePosixPath, str], List[PurePosixPath]]:
    """Each file at paths stored in MetaList (its id by path), except those over the size
    limit for a file, returned second."""
    file_ids: Dict[PurePosixPath, str] = {}
    too_large: List[PurePosixPath] = []
    for path in paths:
        file_path = folder / Path(path)
        if file_path.stat().st_size > MAX_ATTACHMENT_BYTES:
            too_large.append(path)
            continue
        mime_type, _encoding = mimetypes.guess_type(path.name)
        if mime_type is None:
            mime_type = _UNKNOWN_MIME_TYPE
        record = create_file(original_filename=path.name, mime_type=mime_type, content_bytes=file_path.read_bytes(), token=token)
        file_ids[path] = record.id
    return file_ids, too_large


def _kept_file_note(folder: Path, path: PurePosixPath, file_id: str, *, source_tag: str) -> Tuple[str, _Written]:
    """A Canvas, Base or Excalidraw file's own note: the file embedded, tagged as a note of its folder."""
    tags = [tag for tag in (folder_tag_for(path), source_tag) if tag != ""]
    modified_at = datetime.fromtimestamp((folder / Path(path)).stat().st_mtime, tz=timezone.utc)
    node = NoteNode(
        note_id=str(uuid.uuid4()), content_html=plain_text_to_note_html(f"{_EMBED_MARK}[[{file_id}]]"),
        tags=tuple(tags), anchors=(), children=(),
    )
    return str(path), _Written(node=node, created_at=modified_at, updated_at=modified_at)


def _is_kept_file(path: PurePosixPath) -> bool:
    return path.name.casefold().endswith(_KEPT_FILE_SUFFIXES)


def _path_key(path: PurePosixPath) -> str:
    return str(path).casefold()


# A folder's part of a path sorts before a file's: in each folder, its subfolders come first.
_FOLDER_RANK = 0
_FILE_RANK = 1


def _file_list_key(path: PurePosixPath) -> Tuple[Tuple[int, str], ...]:
    """Where a file comes in Obsidian's file list (the maintainer, 2026-11-01): in each folder
    its subfolders first, then its files, each A to Z whatever the case."""
    folders = tuple((_FOLDER_RANK, part.casefold()) for part in path.parts[:-1])
    return (*folders, (_FILE_RANK, path.name.casefold()))


def _records(roots: List[_Written]) -> List[SimpleNamespace]:
    """The notes as records for apply_restore_records: the root notes, in this order, ahead of
    the list's first root note, each followed by its subtree. Roots go in last first: each
    at the top, just ahead of the one after it; children are appended under their parent;
    so a note's neighbours are always next to each other when it is inserted."""
    existing_roots = store.children(_TOP_LEVEL)
    records: List[SimpleNamespace] = []
    for index in reversed(range(len(roots))):
        written = roots[index]
        next_id = None
        if index < len(roots) - 1:
            next_id = roots[index + 1].node.note_id
        elif len(existing_roots) > 0:
            next_id = existing_roots[0]
        records.append(_record(written.node, written, parent_id=_TOP_LEVEL, prev_id=None, next_id=next_id))
        _append_children(records, written.node, written, parent_id=written.node.note_id)
    return records


def _append_children(records: List[SimpleNamespace], node: NoteNode, written: _Written, *, parent_id: str) -> None:
    prev_id = None
    for child in node.children:
        records.append(_record(child, written, parent_id=parent_id, prev_id=prev_id, next_id=None))
        _append_children(records, child, written, parent_id=child.note_id)
        prev_id = child.note_id


def _record(
    node: NoteNode, written: _Written, *, parent_id: str | None, prev_id: str | None, next_id: str | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=node.note_id,
        parent_id=parent_id,
        prev_id=prev_id,
        next_id=next_id,
        is_collapsed=False,
        content=node.content_html,
        tags=" ".join(node.tags),
        proposed_tags="",
        created_at=written.created_at,
        updated_at=written.updated_at,
    )
