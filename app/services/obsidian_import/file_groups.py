"""A folder of any files, grouped by type for the import's checklist
(docs/ready-to-build/folder-import-and-file-previews.md §3): every file in the folder, each
in one group, with how many and how large, and which groups start unticked. Only reads."""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, List, Tuple



@dataclass(frozen=True)
class FileGroupKind:
    key: str
    label: str
    # Starts unticked: rarely wanted in notes (§9, the default unticked list).
    is_skipped_by_default: bool


# The junk groups, decided by where a file is or what it is called (checked first).
HIDDEN = FileGroupKind("hidden", "Hidden and system files", True)
DEPENDENCIES = FileGroupKind("dependencies", "Code dependencies", True)
BUILD = FileGroupKind("build", "Build output and compiled files", True)
# The rest, by the file's extension.
TEXT = FileGroupKind("text", "Markdown and text", False)
IMAGES = FileGroupKind("images", "Images", False)
PDF = FileGroupKind("pdf", "PDF", False)
DOCUMENTS = FileGroupKind("documents", "Documents", False)
SPREADSHEETS = FileGroupKind("spreadsheets", "Spreadsheets and data", False)
PRESENTATIONS = FileGroupKind("presentations", "Presentations", False)
AUDIO = FileGroupKind("audio", "Audio", False)
VIDEO = FileGroupKind("video", "Video", False)
ARCHIVES = FileGroupKind("archives", "Archives", False)
CODE = FileGroupKind("code", "Code", False)
OTHER = FileGroupKind("other", "Other files", False)
FILE_GROUP_KINDS: Dict[str, FileGroupKind] = {
    kind.key: kind for kind in (
        HIDDEN, DEPENDENCIES, BUILD, TEXT, IMAGES, PDF, DOCUMENTS, SPREADSHEETS, PRESENTATIONS, AUDIO, VIDEO,
        ARCHIVES, CODE, OTHER,
    )
}

_HIDDEN_PREFIX = "."
# Folders whose files are hidden or the system's (any folder named so, at any depth).
_SYSTEM_FOLDERS = frozenset({"$recycle.bin", "system volume information"})
_SYSTEM_FILES = frozenset({"thumbs.db", "desktop.ini", "icon\r"})
# Word's lock file while a document is open: `~$Report.docx`.
_OFFICE_LOCK_PREFIX = "~$"
_DEPENDENCY_FOLDERS = frozenset({"node_modules", "bower_components", "vendor", "venv", "__pycache__", "site-packages"})
_BUILD_FOLDERS = frozenset({"dist", "build", "target", "out"})
_COMPILED_SUFFIXES = frozenset({".pyc", ".o", ".class"})
# Text files: notes with their text. Markdown files may be kept as files instead.
MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})
TEXT_SUFFIXES = MARKDOWN_SUFFIXES | frozenset({".txt"})
_SUFFIX_GROUPS: Dict[str, FileGroupKind] = {
    **{suffix: TEXT for suffix in TEXT_SUFFIXES},
    **{suffix: IMAGES for suffix in (
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".svg", ".avif",
    )},
    ".pdf": PDF,
    **{suffix: DOCUMENTS for suffix in (".doc", ".docx", ".rtf", ".odt", ".pages", ".html", ".htm", ".eml")},
    **{suffix: SPREADSHEETS for suffix in (".xls", ".xlsx", ".csv", ".tsv", ".ods", ".numbers", ".json")},
    **{suffix: PRESENTATIONS for suffix in (".ppt", ".pptx", ".key", ".odp")},
    **{suffix: AUDIO for suffix in (".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".aiff")},
    **{suffix: VIDEO for suffix in (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm")},
    **{suffix: ARCHIVES for suffix in (".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".bz2", ".xz", ".dmg")},
    **{suffix: CODE for suffix in (
        ".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".sh", ".zsh", ".rb", ".go", ".rs", ".java", ".kt", ".swift",
        ".c", ".h", ".cpp", ".hpp", ".cs", ".php", ".sql", ".css", ".scss", ".yaml", ".yml", ".toml", ".xml",
    )},
}


@dataclass(frozen=True)
class FolderFile:
    """A file of the folder: its path inside it (folders with /), size and group."""

    path: PurePosixPath
    size: int
    group: FileGroupKind


@dataclass(frozen=True)
class FileGroup:
    """One row of the checklist."""

    kind: FileGroupKind
    file_count: int
    total_bytes: int
    # Its files, the largest first, for the row opened to show them.
    files: Tuple[FolderFile, ...]


def group_of(path: PurePosixPath) -> FileGroupKind:
    """The checklist group of a file at path in the folder: where it sits or what it is
    called first (hidden, dependencies, build), then its extension."""
    folders = [part.casefold() for part in path.parts[:-1]]
    name = path.name.casefold()
    if any(folder.startswith(_HIDDEN_PREFIX) or folder in _SYSTEM_FOLDERS for folder in folders):
        return HIDDEN
    if name.startswith(_HIDDEN_PREFIX) or name in _SYSTEM_FILES or name.startswith(_OFFICE_LOCK_PREFIX):
        return HIDDEN
    if any(folder in _DEPENDENCY_FOLDERS for folder in folders):
        return DEPENDENCIES
    suffix = PurePosixPath(name).suffix
    if any(folder in _BUILD_FOLDERS for folder in folders) or suffix in _COMPILED_SUFFIXES:
        return BUILD
    if suffix in _SUFFIX_GROUPS:  # shockharness: ignore[DEF002] reason="the groups list the endings they take; a file of any other ending is in OTHER, the checklist's 'Other files' row"
        return _SUFFIX_GROUPS[suffix]
    return OTHER


def folder_files(folder: Path) -> List[FolderFile]:
    """Every file in folder, at any depth, hidden ones too, in path order (case ignored).
    Links are not followed."""
    if not folder.is_dir():
        raise ValueError(f"import folder must be a folder: {folder}")
    found: List[FolderFile] = []
    for directory, folder_names, file_names in os.walk(folder):
        folder_names.sort()
        here = Path(directory)
        for file_name in file_names:
            file_path = here / file_name
            if file_path.is_symlink() or not file_path.is_file():
                continue
            relative = PurePosixPath(unicodedata.normalize("NFC", file_path.relative_to(folder).as_posix()))
            found.append(FolderFile(path=relative, size=file_path.stat().st_size, group=group_of(relative)))
    found.sort(key=lambda folder_file: str(folder_file.path).casefold())
    return found


def file_groups(files: List[FolderFile]) -> List[FileGroup]:
    """The checklist's rows: one per group that has files, the largest first (§3)."""
    files_by_group: Dict[str, List[FolderFile]] = {}
    for folder_file in files:
        key = folder_file.group.key
        if key not in files_by_group:
            files_by_group[key] = []
        files_by_group[key].append(folder_file)
    groups = [_group(FILE_GROUP_KINDS[key], grouped) for key, grouped in files_by_group.items()]
    return sorted(groups, key=lambda group: (-group.total_bytes, group.kind.label))


def _group(kind: FileGroupKind, files: List[FolderFile]) -> FileGroup:
    return FileGroup(
        kind=kind, file_count=len(files), total_bytes=sum(folder_file.size for folder_file in files),
        files=tuple(sorted(files, key=lambda folder_file: (-folder_file.size, str(folder_file.path).casefold()))),
    )
