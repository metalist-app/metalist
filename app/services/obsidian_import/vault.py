"""Reading an Obsidian vault (docs/ready-to-build/import-export-launch.md §2; PLAN.md): its
Markdown files in the order Obsidian's file list shows them, with their times, and what is
left out and why. Only reads: the vault is never written to."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import List

from app.services.exception_capture import CapturedExceptionContext
from app.services.image_compression import COMPRESSIBLE_SUFFIXES
from app.services.obsidian_import.import_folder import ROOT, ImportFolder

# Obsidian's own settings, and its trash: never notes.
_SETTINGS_FOLDER = ".obsidian"
_APP_SETTINGS_FILE = "app.json"
_STRICT_LINE_BREAKS_SETTING = "strictLineBreaks"
_HIDDEN_PREFIX = "."
_MARKDOWN_SUFFIX = ".md"
# An Excalidraw drawing is Markdown on disk but no note: it comes in as a file (mapping J4).
_DRAWING_SUFFIX = ".excalidraw.md"
_UTF8 = "utf-8"
# Why a Markdown file is left out when it isn't UTF-8 text (the wizard's summary counts these).
NOT_UTF8_REASON = "not UTF-8 text"
_UTF8_BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True)
class VaultFile:
    """A Markdown file of the vault: its path inside the vault (folders with /), its text,
    and the times the file system gives it."""

    path: PurePosixPath
    text: str
    created_at: datetime
    modified_at: datetime


@dataclass(frozen=True)
class SkippedEntry:
    """A file or folder the import leaves out, and why, for the report."""

    path: str
    reason: str


@dataclass(frozen=True)
class VaultContents:
    name: str
    markdown_files: List[VaultFile]
    # Every other file outside hidden folders: an attachment if a note refers to it.
    other_files: List[PurePosixPath]
    skipped: List[SkippedEntry]
    # Obsidian's "Strict line breaks": a single Return is then no line break.
    uses_strict_line_breaks: bool
    # Why .obsidian/app.json could not be read ("" when it could, or there is none).
    settings_problem: str


def read_vault(folder: ImportFolder, *, reads_line_break_setting: bool) -> VaultContents:
    """The vault at folder: every .md file outside hidden folders, sorted by path as
    Obsidian sorts names (case ignored); hidden folders and other files are skipped."""
    markdown_files: List[VaultFile] = []
    other_files: List[PurePosixPath] = []
    skipped: List[SkippedEntry] = []
    for here, folder_names, file_names in folder.walk():
        for hidden in sorted(name for name in folder_names if name.startswith(_HIDDEN_PREFIX)):
            skipped.append(SkippedEntry(path=_vault_path(here / hidden) + "/", reason="hidden folder"))
        folder_names[:] = sorted(name for name in folder_names if not name.startswith(_HIDDEN_PREFIX))
        for file_name in sorted(file_names):
            file_path = here / file_name
            relative = _vault_path(file_path)
            if file_name.startswith(_HIDDEN_PREFIX):
                skipped.append(SkippedEntry(path=relative, reason="hidden file"))
                continue
            if not file_name.lower().endswith(_MARKDOWN_SUFFIX) or file_name.lower().endswith(_DRAWING_SUFFIX):
                other_files.append(PurePosixPath(relative))
                continue
            text = _utf8_text(folder.read_bytes(file_path))
            if text is None:
                skipped.append(SkippedEntry(path=relative, reason=NOT_UTF8_REASON))
                continue
            created_at, modified_at = folder.file_times(file_path)
            markdown_files.append(VaultFile(
                path=PurePosixPath(relative), text=text, created_at=created_at, modified_at=modified_at,
            ))
    markdown_files.sort(key=lambda vault_file: _sort_key(str(vault_file.path)))
    other_files.sort(key=lambda path: _sort_key(str(path)))
    skipped.sort(key=lambda entry: _sort_key(entry.path))
    # A plain Markdown folder (slice 1c) keeps its line breaks as written: as strict ones.
    uses_strict_line_breaks, settings_problem = True, ""
    if reads_line_break_setting:
        uses_strict_line_breaks, settings_problem = _read_line_break_setting(folder)
    return VaultContents(
        name=unicodedata.normalize("NFC", folder.name),
        markdown_files=markdown_files,
        other_files=other_files,
        skipped=skipped,
        uses_strict_line_breaks=uses_strict_line_breaks,
        settings_problem=settings_problem,
    )


def read_text_file(folder: ImportFolder, relative: PurePosixPath) -> VaultFile | None:
    """The text file at relative in folder as a vault's Markdown file is read (a folder of
    files: folder-import-and-file-previews.md §2), or None when it isn't UTF-8 text."""
    text = _utf8_text(folder.read_bytes(relative))
    if text is None:
        return None
    created_at, modified_at = folder.file_times(relative)
    return VaultFile(path=relative, text=text, created_at=created_at, modified_at=modified_at)


def count_markdown_files(folder: ImportFolder) -> int:
    """How many Markdown files read_vault would read in folder (before reading any)."""
    count = 0
    for _here, folder_names, file_names in folder.walk():
        folder_names[:] = [name for name in folder_names if not name.startswith(_HIDDEN_PREFIX)]
        count += sum(
            1 for name in file_names
            if not name.startswith(_HIDDEN_PREFIX) and name.lower().endswith(_MARKDOWN_SUFFIX)
            and not name.lower().endswith(_DRAWING_SUFFIX)
        )
    return count


def count_compressible_images(folder: ImportFolder) -> int:
    """How many images compression would shrink in folder, outside hidden folders: whether
    the import's Images screen shows (an estimate then counts only the ones notes show)."""
    count = 0
    for _here, folder_names, file_names in folder.walk():
        folder_names[:] = [name for name in folder_names if not name.startswith(_HIDDEN_PREFIX)]
        count += sum(
            1 for name in file_names
            if not name.startswith(_HIDDEN_PREFIX) and Path(name).suffix.casefold() in COMPRESSIBLE_SUFFIXES
        )
    return count


def _utf8_text(content: bytes) -> str | None:
    """content as UTF-8 text (a leading byte-order mark dropped), or None when it is in
    another encoding, as file_text_preview tells."""
    text_bytes = content.removeprefix(_UTF8_BOM)
    text = text_bytes.decode(_UTF8, errors="replace")
    if text.encode(_UTF8) != text_bytes:
        return None
    return text


def _vault_path(path: PurePosixPath) -> str:
    return unicodedata.normalize("NFC", path.as_posix())


def _sort_key(path: str) -> str:
    return path.casefold()


def _read_line_break_setting(folder: ImportFolder) -> tuple[bool, str]:
    """Whether the vault turns on Obsidian's "Strict line breaks", and why its settings
    file could not be read ("" when it could, or there is none: Obsidian's default, off)."""
    settings_path = ROOT / _SETTINGS_FOLDER / _APP_SETTINGS_FILE
    if not folder.is_plain_file(settings_path):
        return False, ""
    text = _utf8_text(folder.read_bytes(settings_path))
    if text is None:
        return False, f"{_SETTINGS_FOLDER}/{_APP_SETTINGS_FILE} is not UTF-8 text"
    settings_capture = CapturedExceptionContext(
        json.JSONDecodeError, boundary="app/services/obsidian_import/vault.py:_read_line_break_setting:settings_capture",
    )
    settings: object = None
    with settings_capture:
        settings = json.loads(text)
    if settings_capture.captured_exception is not None:
        return False, f"{_SETTINGS_FOLDER}/{_APP_SETTINGS_FILE} is not valid JSON"
    if not isinstance(settings, dict):
        return False, f"{_SETTINGS_FOLDER}/{_APP_SETTINGS_FILE} holds no settings"
    return _STRICT_LINE_BREAKS_SETTING in settings and settings[_STRICT_LINE_BREAKS_SETTING] is True, ""
