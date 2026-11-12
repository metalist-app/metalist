"""Importing an Obsidian vault, or a plain folder of Markdown files, into the vault in use (PLAN.md, slices 1 and 1c;
docs/ready-to-build/import-export-launch.md §2, §5): every file planned first, then all of
it written at once, as new root notes after the list's last one, in the
order of Obsidian's file list.
The vault's folder is only read."""

from __future__ import annotations

import html
import mimetypes
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Dict, List, Tuple

from app.services.background_work import IMPORT_KEY, WorkProgress, background_work
from app.services.file_storage import create_file, create_file_from_pieces
from app.services.import_uploads import open_import_folder
from app.services.obsidian_import.import_folder import ImportFolder
from app.services.image_compression import COMPRESSIBLE_SUFFIXES, CompressedImage, ImageChoice, compressed_image, estimated_compressed_bytes
from app.services.file_view import plain_text_to_note_html
from app.services.input_errors import InputRejected
from app.services.obsidian_import.file_groups import (
    FILE_GROUP_KINDS,
    IMAGES,
    MARKDOWN_SUFFIXES,
    TEXT_SUFFIXES,
    FolderFile,
    folder_files,
    group_of,
)
from app.services.obsidian_import.links import LinkReference, with_tokens_replaced
from app.services.obsidian_import.notes import (
    PlannedNote,
    folder_tag_for,
    import_folder_prefix,
    plan_file_note,
    source_tag_for,
)
from app.services.obsidian_import.resolve import VaultIndex
from app.services.obsidian_import.sources import FILES, IMPORT_SOURCES, ImportSource
from app.services.obsidian_import.tree import CONTENT_FORMATS, SPLIT_MODES, NoteNode, count_notes
from app.services.obsidian_import.vault import NOT_UTF8_REASON, VaultContents, VaultFile, read_text_file, read_vault
from app.services.store import store
from app.services.virtual_folders import all_folder_tags
from app.services.disk_space import full_disk_is_rejected, require_room_for_files
from app.upload_limits import MAX_IN_MEMORY_FILE_BYTES
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
# Images compressed at once while importing (each holds a decoded picture in memory), and
# how many files are read ahead of the one being stored.
_COMPRESSING_THREADS = 4
_READ_AHEAD_FILES = 8
# An import's progress: a part per file stored (as many as the files it says it imports).
IMPORTING_LABEL = "Importing files"


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
    # The folder everything goes under, as typed ('' for none), and whether to add to it when
    # it exists already (docs/ready-to-build/import-prefix-folder.md).
    folder_prefix: str
    add_to_existing: bool
    # Images compressed as they come in, or not (folder-import-and-file-previews.md, Images compressed).
    images: ImageChoice
    token: str
    imported_at: datetime

    def execute(self) -> Dict[str, object]:
        # Shown as it goes: the walkthrough's bar (the maintainer, 2026-11-02).
        with background_work.track(IMPORT_KEY, IMPORTING_LABEL, total=0) as progress:
            return self._import(progress)

    def _import(self, progress: WorkProgress) -> Dict[str, object]:
        plan = _plan_import(
            source_key=self.source, folder_path=self.folder_path, split_mode=self.split_mode,
            content_format=self.content_format, folder_prefix=self.folder_prefix, imported_at=self.imported_at,
        )
        if import_folder_exists(plan.folder_prefix) and not self.add_to_existing:
            raise InputRejected(f"{plan.folder_prefix} already exists. Tick Add to it, or choose another name.")
        is_new_folder = is_new_import_folder(plan.folder_prefix)
        folder, vault, planned, source_tag = plan.folder, plan.vault, plan.planned, plan.source_tag
        linked = _linked(
            folder, vault, planned, source_tag=source_tag, folder_prefix=plan.folder_prefix,
            images=self.images, token=self.token, progress=progress,
        )
        planned = linked.planned
        note_count = sum(count_notes(note.root) for note in planned) + len(linked.kept)
        roots = [
            *((note.source_path, WrittenRoot(node=note.root, created_at=note.created_at, updated_at=note.updated_at)) for note in planned),
            *linked.kept,
        ]
        roots.sort(key=lambda pair: _file_list_key(PurePosixPath(pair[0])))
        # The files after the list's last note, as Obsidian's file list
        # orders them (no import report: the maintainer, 2026-11-01).
        written_roots = [written for _path, written in roots]
        records = root_records(written_roots)
        apply_restore_records(records, self.token)
        return {
            "status": "success", "noteCount": note_count,
            # Every note of this import has it: the wizard opens a search context on it.
            "sourceTag": source_tag,
            "firstRootId": first_root_id(written_roots),
            "prefixFolder": plan.folder_prefix,
            "isNewFolder": is_new_folder,
        }


@dataclass(frozen=True)
class _ImportPlan:
    """A folder read and every file planned as notes, nothing stored or written yet."""

    source: ImportSource
    folder: ImportFolder
    vault: VaultContents
    planned: List[PlannedNote]
    source_tag: str
    # The folder everything goes under, cleaned ('' for none).
    folder_prefix: str


def import_folder_exists(folder_prefix: str) -> bool:
    """Whether some note is in that folder or below it already ('' is no folder)."""
    if folder_prefix == "":
        return False
    return any(tag.casefold().startswith(folder_prefix.casefold()) for tag in all_folder_tags())


def is_new_import_folder(folder_prefix: str) -> bool:
    """Whether an import into that folder makes it ('' is no folder): asked before its notes are written."""
    return folder_prefix != "" and not import_folder_exists(folder_prefix)


def _plan_import(
    *, source_key: str, folder_path: str, split_mode: str, content_format: str, folder_prefix: str, imported_at: datetime,
) -> _ImportPlan:
    if split_mode not in SPLIT_MODES or content_format not in CONTENT_FORMATS:
        raise InputRejected("Choose how to split the notes and what to write them in.")
    assert source_key in IMPORT_SOURCES, f"unknown import source {source_key!r}"
    source = IMPORT_SOURCES[source_key]
    folder = Path(folder_path)
    if not folder.is_absolute():
        raise InputRejected(f"Choose the {source.folder_word}'s folder with Choose Folder.")
    if not folder.is_dir():
        raise InputRejected(f"There is no folder at {folder}. Choose the {source.folder_word}'s folder again.")
    import_folder = open_import_folder(folder)
    vault = read_vault(import_folder, reads_line_break_setting=source.follows_obsidian_line_breaks)
    if len(vault.markdown_files) == 0:
        raise InputRejected(f"{folder} holds no Markdown files. Choose a folder that does.")
    source_tag = source_tag_for(imported_at, source.key)
    prefix = import_folder_prefix(folder_prefix)
    planned = [
        plan_file_note(
            vault_file, uses_strict_line_breaks=vault.uses_strict_line_breaks, source_tag=source_tag,
            split_mode=split_mode, content_format=content_format, folder_prefix=prefix,
        )
        for vault_file in vault.markdown_files
    ]
    return _ImportPlan(
        source=source, folder=import_folder, vault=vault, planned=planned, source_tag=source_tag, folder_prefix=prefix,
    )


@dataclass
class CmdPreviewImport(QueryCommand):
    """What importing the folder would do, as the import wizard's summary shows it before
    anything is written (PLAN.md, phase 2): counts, and what would appear differently. Reads
    the folder and plans every file; stores and writes nothing."""

    source: str
    folder_path: str
    split_mode: str
    content_format: str
    folder_prefix: str
    imported_at: datetime

    def execute(self) -> Dict[str, object]:
        plan = _plan_import(
            source_key=self.source, folder_path=self.folder_path, split_mode=self.split_mode,
            content_format=self.content_format, folder_prefix=self.folder_prefix, imported_at=self.imported_at,
        )
        index = VaultIndex(plan.planned, plan.vault.other_files)
        resolved = [
            _resolve(index, reference, from_path=note.source_path) for note in plan.planned for reference in note.links
        ]
        kept_paths = [path for path in plan.vault.other_files if _is_kept_file(path)]
        linked_paths = {item.file_path for item in resolved if item.file_path is not None}
        findings = [note.findings for note in plan.planned]
        kept_note_count = len(kept_paths)
        return {
            # The folder the notes go into ('' for none), as the summary shows it.
            "prefixFolder": plan.folder_prefix,
            "fileCount": len(plan.planned),
            "noteCount": sum(count_notes(note.root) for note in plan.planned) + kept_note_count,
            # The notes at the top level of the list (each file's, and each kept file's), the report aside.
            "rootNoteCount": len(plan.planned) + kept_note_count,
            # The summary says what each becomes: Markdown files notes, the rest a file in a note of its own.
            "textFileCount": len(plan.planned),
            "keptFileCount": kept_note_count,
            "attachmentCount": sum(1 for path in linked_paths if not _is_kept_file(path)),
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
class WrittenRoot:
    """A root note to write with its subtree, and its times."""

    node: NoteNode
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class _Linked:
    """The files' notes with their links made MetaList's, and the notes of Canvas, Base and
    Excalidraw files (with their paths)."""

    planned: List[PlannedNote]
    kept: List[Tuple[str, WrittenRoot]]


def _linked(
    folder: ImportFolder, vault: VaultContents, planned: List[PlannedNote], *, source_tag: str, folder_prefix: str,
    images: ImageChoice, token: str, progress: WorkProgress,
) -> _Linked:
    """Every link and embed resolved, and the files they reach stored (with the Canvas, Base
    and Excalidraw files, which come in linked to or not)."""
    index = VaultIndex(planned, vault.other_files)
    resolved = {note.source_path: [_resolve(index, reference, from_path=note.source_path) for reference in note.links] for note in planned}
    kept_paths = [path for path in vault.other_files if _is_kept_file(path)]
    linked_paths = {item.file_path for items in resolved.values() for item in items if item.file_path is not None}
    file_ids = _store_files(
        folder, sorted({*linked_paths, *kept_paths}, key=_path_key), images=images, token=token, progress=progress,
    )
    return _Linked(
        planned=[
            replace(note, root=_with_links(note.root, _replacements(resolved[note.source_path], file_ids)))
            for note in planned
        ],
        kept=[
            _kept_file_note(folder, path, file_ids[path], source_tag=source_tag, folder_prefix=folder_prefix)
            for path in kept_paths if path in file_ids
        ],
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


def _store_files(
    folder: ImportFolder, paths: List[PurePosixPath], *, images: ImageChoice, token: str, progress: WorkProgress,
) -> Dict[PurePosixPath, str]:
    """Each file at paths stored in MetaList (its id by path), images compressed when images say.
    progress counts each file stored."""
    require_room_for_files([folder.size(path) for path in paths])
    progress.set_total(len(paths))
    file_ids: Dict[PurePosixPath, str] = {}
    # A few at a time: compressing runs on threads, never far ahead of the storing.
    with full_disk_is_rejected(), ThreadPoolExecutor(max_workers=_COMPRESSING_THREADS) as executor:
        for start in range(0, len(paths), _READ_AHEAD_FILES):
            batch = paths[start:start + _READ_AHEAD_FILES]
            compressed_files = executor.map(lambda path: _compressed_if_asked(folder, path, images=images), batch)
            for path, compressed in zip(batch, compressed_files):
                file_ids[path] = _store_one_file(folder, path, compressed=compressed, token=token)
                progress.advance()
    return file_ids


def _store_one_file(folder: ImportFolder, path: PurePosixPath, *, compressed: CompressedImage | None, token: str) -> str:
    """A compressed image as it was made, every other file streamed from the folder."""
    if compressed is not None:
        return create_file(
            original_filename=compressed.filename, mime_type=compressed.mime_type, content_bytes=compressed.content, token=token,
        ).id
    mime_type, _encoding = mimetypes.guess_type(path.name)
    if mime_type is None:
        mime_type = _UNKNOWN_MIME_TYPE
    return create_file_from_pieces(pieces=folder.pieces(path), original_filename=path.name, mime_type=mime_type, token=token).id


def _compressed_if_asked(folder: ImportFolder, path: PurePosixPath, *, images: ImageChoice) -> CompressedImage | None:
    """The image compressed when asked and it comes out smaller; None for anything else, which
    is stored as it is. Compressing holds the image in memory, so a huge one is left whole."""
    if not images.compresses or folder.size(path) > MAX_IN_MEMORY_FILE_BYTES:
        return None
    return compressed_image(folder.read_bytes(path), path.name, longest_side_px=images.longest_side_px)


def _kept_file_note(
    folder: ImportFolder, path: PurePosixPath, file_id: str, *, source_tag: str, folder_prefix: str,
) -> Tuple[str, WrittenRoot]:
    """A Canvas, Base or Excalidraw file's own note: the file embedded, tagged as a note of its folder."""
    tags = [tag for tag in (folder_tag_for(path, folder_prefix), source_tag) if tag != ""]
    _created_at, modified_at = folder.file_times(path)
    node = NoteNode(
        note_id=str(uuid.uuid4()), content_html=plain_text_to_note_html(f"{_EMBED_MARK}[[{file_id}]]"),
        tags=tuple(tags), anchors=(), children=(),
    )
    return str(path), WrittenRoot(node=node, created_at=modified_at, updated_at=modified_at)


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


def first_root_id(roots: List[WrittenRoot]) -> str:
    """The import's first root note: a drop's view shows it (import-wizard-steps.js)."""
    assert roots, "An import writes at least one root note"
    return roots[0].node.note_id


def root_records(roots: List[WrittenRoot]) -> List[SimpleNamespace]:
    """The notes as records for apply_restore_records: the root notes, in this order, each
    followed by its subtree. Anything imported, a single note too, goes after the list's last
    root note (the maintainer, 2026-11-08: one rule to reason about): imported at the top, notes
    looked as if they had replaced everything to someone who works without a search. Each root is
    linked to the note before it, already in place, and children are appended under their parent,
    so a note's neighbours are always next to each other when it is inserted. An import's notes
    take none of the tags of the search showing when it began, a drop's either (the maintainer,
    2026-11-11: bookmarks dropped in the journal search came in as journal entries)."""
    existing_roots = store.children(_TOP_LEVEL)
    records: List[SimpleNamespace] = []
    prev_id = None
    if len(existing_roots) > 0:
        prev_id = existing_roots[-1]
    for written in roots:
        records.append(_record(written.node, written, parent_id=_TOP_LEVEL, prev_id=prev_id, next_id=None))
        _append_children(records, written.node, written, parent_id=written.node.note_id)
        prev_id = written.node.note_id
    return records


def _append_children(records: List[SimpleNamespace], node: NoteNode, written: WrittenRoot, *, parent_id: str) -> None:
    prev_id = None
    for child in node.children:
        records.append(_record(child, written, parent_id=parent_id, prev_id=prev_id, next_id=None))
        _append_children(records, child, written, parent_id=child.note_id)
        prev_id = child.note_id


def _record(
    node: NoteNode, written: WrittenRoot, *, parent_id: str | None, prev_id: str | None, next_id: str | None,
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


# --- A folder of any files (docs/ready-to-build/folder-import-and-file-previews.md) --------


@dataclass(frozen=True)
class FileSelection:
    """What the checklist ticked (folder-import-and-file-previews.md §3): the kinds left out,
    and the files ticked against their kind (the maintainer, 2026-11-01): left out of a
    ticked kind, or brought in from an unticked one, by their paths in the folder."""

    excluded_groups: Tuple[str, ...]
    excluded_files: Tuple[str, ...]
    included_files: Tuple[str, ...]
    # Markdown files kept as files, each in a note of its own as a PDF is, instead of turned
    # into notes (the maintainer, 2026-11-01: one choice for all of them; READMEs and docs).
    keeps_markdown_as_files: bool

    def includes(self, folder_file: FolderFile) -> bool:
        path = str(folder_file.path)
        if folder_file.group.key in self.excluded_groups:
            return path in self.included_files
        return path not in self.excluded_files


@dataclass(frozen=True)
class _FilesPlan:
    """A folder of files read and planned: its text files as notes, every other file (and a
    text file that isn't UTF-8) to be attached in a note of its own; nothing stored yet."""

    folder: ImportFolder
    planned: List[PlannedNote]
    attached: List[PurePosixPath]
    source_tag: str
    folder_prefix: str


def _plan_folder_of_files(
    *, folder_path: str, selection: FileSelection, split_mode: str, content_format: str, folder_prefix: str,
    imported_at: datetime,
) -> _FilesPlan:
    if split_mode not in SPLIT_MODES or content_format not in CONTENT_FORMATS:
        raise InputRejected("Choose how to split the notes and what to write them in.")
    unknown = sorted(set(selection.excluded_groups) - set(FILE_GROUP_KINDS))
    if unknown:
        raise InputRejected(f"Unknown kinds of file: {', '.join(unknown)}.")
    folder = Path(folder_path)
    if not folder.is_absolute():
        raise InputRejected("Choose the folder with Choose Folder.")
    if not folder.is_dir():
        raise InputRejected(f"There is no folder at {folder}. Choose the folder again.")
    import_folder = open_import_folder(folder)
    found = folder_files(import_folder)
    named = {*selection.excluded_files, *selection.included_files}
    missing = named - {str(folder_file.path) for folder_file in found}
    if missing:
        raise InputRejected(f"{len(missing)} of the files you ticked or unticked are no longer in the folder. Choose the folder again.")
    chosen = [folder_file for folder_file in found if selection.includes(folder_file)]
    if not chosen:
        raise InputRejected("Nothing to import: tick at least one kind of file.")
    source_tag = source_tag_for(imported_at, FILES.key)
    prefix = import_folder_prefix(folder_prefix)
    text_files: List[VaultFile] = []
    attached: List[PurePosixPath] = []
    for folder_file in chosen:
        text_file = None
        suffix = folder_file.path.suffix.casefold()
        is_kept_as_file = selection.keeps_markdown_as_files and suffix in MARKDOWN_SUFFIXES
        # A text file too large to hold in memory comes in as a file, like one that isn't UTF-8.
        if suffix in TEXT_SUFFIXES and not is_kept_as_file and folder_file.size <= MAX_IN_MEMORY_FILE_BYTES:
            text_file = read_text_file(import_folder, folder_file.path)
        if text_file is None:
            attached.append(folder_file.path)
            continue
        text_files.append(text_file)
    planned = [
        plan_file_note(
            text_file, uses_strict_line_breaks=True, source_tag=source_tag, split_mode=split_mode,
            content_format=content_format, folder_prefix=prefix,
        )
        for text_file in text_files
    ]
    return _FilesPlan(
        folder=import_folder, planned=planned, attached=attached,
        source_tag=source_tag, folder_prefix=prefix,
    )


@dataclass
class CmdPreviewFolderOfFiles(QueryCommand):
    """What importing a folder of files would do, for the wizard's summary; writes nothing."""

    folder_path: str
    selection: FileSelection
    split_mode: str
    content_format: str
    folder_prefix: str
    imported_at: datetime

    def execute(self) -> Dict[str, object]:
        plan = _plan_folder_of_files(
            folder_path=self.folder_path, selection=self.selection, split_mode=self.split_mode,
            content_format=self.content_format, folder_prefix=self.folder_prefix, imported_at=self.imported_at,
        )
        index = VaultIndex(plan.planned, plan.attached)
        resolved = [
            _resolve(index, reference, from_path=note.source_path) for note in plan.planned for reference in note.links
        ]
        findings = [note.findings for note in plan.planned]
        folder_tags = {note.folder_tag for note in plan.planned} | {
            folder_tag_for(path, plan.folder_prefix) for path in plan.attached
        }
        return {
            "prefixFolder": plan.folder_prefix,
            "fileCount": len(plan.planned) + len(plan.attached),
            "noteCount": sum(count_notes(note.root) for note in plan.planned) + len(plan.attached),
            "rootNoteCount": len(plan.planned) + len(plan.attached),
            "textFileCount": len(plan.planned),
            "keptFileCount": len(plan.attached),
            # Of those, images: each shown as its picture in its note (the maintainer, 2026-11-01:
            # say whether they come in inside notes or as files). By name, wherever they sit.
            "keptImageCount": sum(1 for path in plan.attached if group_of(PurePosixPath(path.name)) == IMAGES),
            "attachmentCount": len(plan.attached),
            "folderTagCount": len(folder_tags - {""}),
            "filesWithCommentsCount": sum(1 for finding in findings if finding.has_comments),
            "blockIdCount": sum(finding.block_id_count for finding in findings),
            "calloutCount": sum(finding.callout_count for finding in findings),
            "missingLinkCount": sum(1 for item in resolved if item.note is None and item.file_path is None),
            # A text file that isn't UTF-8 is attached instead: nothing is left out for it.
            "unreadableFileCount": 0,
            "unusedAttachmentCount": 0,
        }


@dataclass
class CmdImportFolderOfFiles(QueryCommand):
    """Import a folder of any files (folder-import-and-file-previews.md §2): each text file a
    note with its text, every other file in a note of its own, each
    with its folder's tag under the import's folder; the groups unticked in the checklist and
    files over the per-file limit left out."""

    folder_path: str
    selection: FileSelection
    split_mode: str
    content_format: str
    folder_prefix: str
    add_to_existing: bool
    images: ImageChoice
    token: str
    imported_at: datetime

    def execute(self) -> Dict[str, object]:
        # Shown as it goes: the walkthrough's bar (the maintainer, 2026-11-02).
        with background_work.track(IMPORT_KEY, IMPORTING_LABEL, total=0) as progress:
            return self._import(progress)

    def _import(self, progress: WorkProgress) -> Dict[str, object]:
        plan = _plan_folder_of_files(
            folder_path=self.folder_path, selection=self.selection, split_mode=self.split_mode,
            content_format=self.content_format, folder_prefix=self.folder_prefix, imported_at=self.imported_at,
        )
        if import_folder_exists(plan.folder_prefix) and not self.add_to_existing:
            raise InputRejected(f"{plan.folder_prefix} already exists. Tick Add to it, or choose another name.")
        is_new_folder = is_new_import_folder(plan.folder_prefix)
        file_ids = _store_files(plan.folder, plan.attached, images=self.images, token=self.token, progress=progress)
        index = VaultIndex(plan.planned, plan.attached)
        planned = [
            replace(note, root=_with_links(note.root, _replacements(
                [_resolve(index, reference, from_path=note.source_path) for reference in note.links], file_ids,
            )))
            for note in plan.planned
        ]
        attached = [
            _attached_file_note(
                plan.folder, path, file_ids[path], source_tag=plan.source_tag, folder_prefix=plan.folder_prefix,
            )
            for path in plan.attached
        ]
        roots = [
            *((note.source_path, WrittenRoot(node=note.root, created_at=note.created_at, updated_at=note.updated_at)) for note in planned),
            *attached,
        ]
        roots.sort(key=lambda pair: _file_list_key(PurePosixPath(pair[0])))
        written_roots = [written for _path, written in roots]
        apply_restore_records(root_records(written_roots), self.token)
        note_count = sum(count_notes(note.root) for note in planned) + sum(count_notes(written.node) for _path, written in attached)
        return {"status": "success", "noteCount": note_count, "sourceTag": plan.source_tag,
                "firstRootId": first_root_id(written_roots), "prefixFolder": plan.folder_prefix, "isNewFolder": is_new_folder}


def _attached_file_note(
    folder: ImportFolder, path: PurePosixPath, file_id: str, *, source_tag: str, folder_prefix: str,
) -> Tuple[str, WrittenRoot]:
    """A file's own note: the file alone (its card shows its name; the maintainer, 2026-11-01:
    a name line over it said it twice), tagged as a note of its folder. Search finds it by the
    file's name, and by its words once its text is read (file_text_search.py)."""
    tags = [tag for tag in (folder_tag_for(path, folder_prefix), source_tag) if tag != ""]
    _created_at, modified_at = folder.file_times(path)
    node = NoteNode(
        note_id=str(uuid.uuid4()), content_html=plain_text_to_note_html(f"{_EMBED_MARK}[[{file_id}]]"),
        tags=tuple(tags), anchors=(), children=(),
    )
    return str(path), WrittenRoot(node=node, created_at=modified_at, updated_at=modified_at)


@dataclass
class CmdEstimateImportImages(QueryCommand):
    """The images an import would compress, for the wizard's Images screen
    (folder-import-and-file-previews.md, Images compressed): how many, their size, and about
    their size compressed. Writes nothing."""

    source: str
    folder_path: str
    selection: FileSelection
    split_mode: str
    content_format: str
    folder_prefix: str
    imported_at: datetime

    def execute(self) -> Dict[str, object]:
        if self.source == FILES.key:
            files_plan = _plan_folder_of_files(
                folder_path=self.folder_path, selection=self.selection, split_mode=self.split_mode,
                content_format=self.content_format, folder_prefix=self.folder_prefix, imported_at=self.imported_at,
            )
            folder, stored = files_plan.folder, files_plan.attached
        else:
            plan = _plan_import(
                source_key=self.source, folder_path=self.folder_path, split_mode=self.split_mode,
                content_format=self.content_format, folder_prefix=self.folder_prefix, imported_at=self.imported_at,
            )
            folder, stored = plan.folder, _linked_file_paths(plan)
        images = [
            (path, folder.size(path)) for path in stored if path.suffix.casefold() in COMPRESSIBLE_SUFFIXES
        ]
        images = [(image_path, size) for image_path, size in images if size <= MAX_IN_MEMORY_FILE_BYTES]
        return {
            "imageCount": len(images),
            "imageBytes": sum(size for _image_path, size in images),
            # About their size compressed at each longest side the screen offers.
            "compressedBytes": {str(side): size for side, size in estimated_compressed_bytes(images, folder.read_bytes).items()},
        }


def _linked_file_paths(plan: _ImportPlan) -> List[PurePosixPath]:
    """The vault's files its notes link to or show: the files it stores besides Canvas, Base
    and Excalidraw files (never images)."""
    index = VaultIndex(plan.planned, plan.vault.other_files)
    resolved = [_resolve(index, reference, from_path=note.source_path) for note in plan.planned for reference in note.links]
    return sorted({item.file_path for item in resolved if item.file_path is not None}, key=_path_key)


