"""What the importer can import (PLAN.md, slices 1 and 1c): an Obsidian vault, or a plain
folder of Markdown files from any app. Both go through the same importer; they differ in
their source tag, their report's words and whether Obsidian's own line breaks apply."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ImportSource:
    # The source tag's value (`imported:source=<key>`) and the API's name for it.
    key: str
    # Its name in the report's title and in messages: "Obsidian", "Markdown".
    label: str
    # What the folder is called: "vault", "folder".
    folder_word: str
    # Whether .obsidian/app.json is read: an Obsidian vault shows a single Return as a line
    # break unless "Strict line breaks" is on; plain Markdown never does.
    follows_obsidian_line_breaks: bool
    # What the folder dialog asks for.
    folder_prompt: str
    # The import report's first words: what comes back out of MetaList, and that the folder
    # was only read.
    one_way_text: str


OBSIDIAN = ImportSource(
    key="obsidian", label="Obsidian", folder_word="vault", follows_obsidian_line_breaks=True,
    folder_prompt="Choose an Obsidian vault to import into MetaList",
    one_way_text=(
        "**One-way.** MetaList exports standard Markdown, so your notes, text, links and files come "
        "back out, but features only Obsidian has may not. Your vault's folder was only read, never changed."
    ),
)
MARKDOWN = ImportSource(
    key="markdown", label="Markdown", folder_word="folder", follows_obsidian_line_breaks=False,
    folder_prompt="Choose a folder of Markdown files to import into MetaList",
    one_way_text=(
        "**One-way.** MetaList exports standard Markdown, so your notes, text, links and files come "
        "back out. Your folder was only read, never changed."
    ),
)
IMPORT_SOURCES: Dict[str, ImportSource] = {source.key: source for source in (OBSIDIAN, MARKDOWN)}
