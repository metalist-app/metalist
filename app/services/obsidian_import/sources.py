"""What the importer can import (PLAN.md, slices 1 and 1c): an Obsidian vault, a plain folder
of Markdown files from any app, or a folder of any files (folder-import-and-file-previews.md).
The first two go through the same importer, differing in their source tag, their words and
whether Obsidian's own line breaks apply; a folder of files has its own (every file a note)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ImportSource:
    # The source tag's value (`imported:source=<key>`) and the API's name for it.
    key: str
    # Its name in messages: "Obsidian", "Markdown".
    label: str
    # What the folder is called: "vault", "folder".
    folder_word: str
    # Whether .obsidian/app.json is read: an Obsidian vault shows a single Return as a line
    # break unless "Strict line breaks" is on; plain Markdown never does.
    follows_obsidian_line_breaks: bool
    # What the folder dialog asks for.
    folder_prompt: str


OBSIDIAN = ImportSource(
    key="obsidian", label="Obsidian", folder_word="vault", follows_obsidian_line_breaks=True,
    folder_prompt="Choose an Obsidian vault to import into MetaList",
)
MARKDOWN = ImportSource(
    key="markdown", label="Markdown", folder_word="folder", follows_obsidian_line_breaks=False,
    folder_prompt="Choose a folder of Markdown files to import into MetaList",
)
# Any folder: every file a note (docs/ready-to-build/folder-import-and-file-previews.md).
FILES = ImportSource(
    key="files", label="Any folder", folder_word="folder", follows_obsidian_line_breaks=False,
    folder_prompt="Choose a folder to import into MetaList",
)
IMPORT_SOURCES: Dict[str, ImportSource] = {source.key: source for source in (OBSIDIAN, MARKDOWN, FILES)}
