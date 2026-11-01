"""Importing an Obsidian vault into the vault in use (PLAN.md, slice 1;
docs/ready-to-build/import-export-launch.md §2, §5): every file planned first, then all of
it written at once, as new root notes at the top of the list with the report note first.
The vault's folder is only read."""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List

from app.services.file_text_preview import plain_text_to_note_html
from app.services.input_errors import InputRejected
from app.services.obsidian_import.notes import MARKDOWN_TAG, PlannedNote, plan_file_note, source_tag_for
from app.services.obsidian_import.vault import VaultContents, read_vault
from app.services.store import store
from app.services.structured_note_renderers import extract_plain_text_from_note_html
from app.usecases.base import QueryCommand
from app.usecases.delete_subtree import apply_restore_records

REPORT_TITLE_FORMAT = "Import report — Obsidian — {vault} — {at}"
_REPORT_TIME_FORMAT = "%Y-%m-%d %H:%M"
_REPORT_TITLE_END = " — "
_DIRECTION_LABEL = (
    "**One-way.** MetaList exports standard Markdown, so your notes, text, links and files come "
    "back out, but features only Obsidian has may not. Your vault's folder was only read, never changed."
)
# The root notes' parent: the top of the list.
_TOP_LEVEL = None


@dataclass(frozen=True)
class _NoteToWrite:
    text: str
    tags: str
    created_at: datetime
    updated_at: datetime


@dataclass
class CmdImportObsidianVault(QueryCommand):
    """Import the Obsidian vault at folder_path (the developer version, PLAN.md)."""

    folder_path: str
    token: str
    imported_at: datetime

    def execute(self) -> Dict[str, object]:
        folder = Path(self.folder_path)
        if not folder.is_absolute():
            raise InputRejected("Choose the vault's folder with Choose Folder.")
        if not folder.is_dir():
            raise InputRejected(f"There is no folder at {folder}. Choose the vault's folder again.")
        vault = read_vault(folder)
        if len(vault.markdown_files) == 0:
            raise InputRejected(f"{folder} holds no Markdown files. Choose an Obsidian vault's folder.")
        source_tag = source_tag_for(self.imported_at)
        planned = [
            plan_file_note(vault_file, uses_strict_line_breaks=vault.uses_strict_line_breaks, source_tag=source_tag)
            for vault_file in vault.markdown_files
        ]
        report = _NoteToWrite(
            text=_report_text(vault, planned, imported_at=self.imported_at, earlier_imports=_earlier_imports(vault)),
            tags=f"{MARKDOWN_TAG} {source_tag}",
            created_at=self.imported_at,
            updated_at=self.imported_at,
        )
        files = [_NoteToWrite(text=note.text, tags=note.tags, created_at=note.created_at, updated_at=note.updated_at) for note in planned]
        records = _root_records([report, *files])
        apply_restore_records(records, self.token)
        return {"status": "success", "reportNoteId": records[-1].id, "noteCount": len(planned)}


def _root_records(notes: List[_NoteToWrite]) -> List[SimpleNamespace]:
    """The notes as root notes, in this order, ahead of the list's first root note. Written
    last first: each goes in at the top, just ahead of the one after it, so its neighbours are
    always next to each other when it is inserted."""
    ids = [str(uuid.uuid4()) for _note in notes]
    existing_roots = store.children(_TOP_LEVEL)
    records: List[SimpleNamespace] = []
    for index in reversed(range(len(notes))):
        note = notes[index]
        next_id = None
        if index < len(notes) - 1:
            next_id = ids[index + 1]
        elif len(existing_roots) > 0:
            next_id = existing_roots[0]
        records.append(SimpleNamespace(
            id=ids[index],
            parent_id=_TOP_LEVEL,
            prev_id=None,
            next_id=next_id,
            is_collapsed=False,
            content=plain_text_to_note_html(note.text),
            tags=note.tags,
            proposed_tags="",
            created_at=note.created_at,
            updated_at=note.updated_at,
        ))
    return records


def _earlier_imports(vault: VaultContents) -> int:
    """How many earlier import reports of this vault are root notes in the list."""
    prefix = REPORT_TITLE_FORMAT.format(vault=vault.name, at="").removesuffix(_REPORT_TITLE_END) + _REPORT_TITLE_END
    first_lines = [
        extract_plain_text_from_note_html(store.get(note_id).content).split("\n")[0]
        for note_id in store.children(_TOP_LEVEL)
    ]
    return sum(1 for first_line in first_lines if first_line.startswith(prefix))


def _report_text(vault: VaultContents, planned: List[PlannedNote], *, imported_at: datetime, earlier_imports: int) -> str:
    """The import report as Markdown (§5): counts, what was left out or changed, and every
    imported file."""
    at = imported_at.astimezone().strftime(_REPORT_TIME_FORMAT)
    lines = [REPORT_TITLE_FORMAT.format(vault=vault.name, at=at), "", _DIRECTION_LABEL, ""]
    if earlier_imports > 0:
        lines += [f"**This vault was imported before:** {earlier_imports} earlier import report(s) are in your list.", ""]
    folder_tags = {note.folder_tag for note in planned if note.folder_tag != ""}
    lines += [
        "## Imported", "",
        f"- {len(planned)} notes, one per Markdown file, each at the top of the list.",
        f"- {len(folder_tags)} folder tags.",
        "", "## Left out", "",
    ]
    if len(vault.skipped) == 0 and vault.settings_problem == "":
        lines.append("Nothing.")
    lines += [f"- `{entry.path}`: {entry.reason}" for entry in vault.skipped]
    if vault.settings_problem != "":
        lines.append(f"- Obsidian's settings: {vault.settings_problem}; its default line breaks were used.")
    unread = Counter(key for note in planned for key in note.findings.unread_keys)
    if len(unread) > 0:
        lines += ["", "## Frontmatter properties not imported yet", ""]
        lines += [f"- `{key}`: in {count} file(s)" for key, count in sorted(unread.items())]
    problems = [note for note in planned if note.findings.frontmatter_problem != ""]
    renamed = sorted({pair for note in planned for pair in note.findings.renamed_tags})
    dropped = sorted({name for note in planned for name in note.findings.dropped_tags})
    if len(problems) + len(renamed) + len(dropped) > 0:
        lines += ["", "## Changed", ""]
        lines += [f"- `{note.source_path}`: {note.findings.frontmatter_problem}" for note in problems]
        lines += [f"- Tag `{original}` became `{tag}`." for original, tag in renamed]
        lines += [f"- Tag `{name}` has no characters a tag can hold, so it was left out." for name in dropped]
    commented = [note for note in planned if note.findings.has_comments]
    block_ids = sum(note.findings.block_id_count for note in planned)
    if len(commented) > 0 or block_ids > 0:
        lines += ["", "## Approximated", ""]
        if len(commented) > 0:
            lines.append(f"- `%%comments%%` stay as visible text, in {len(commented)} file(s).")
        if block_ids > 0:
            lines.append(f"- {block_ids} block IDs (`^abc123`) were removed.")
    lines += ["", "## Files", ""]
    lines += [f"- `{note.source_path}`" for note in planned]
    return "\n".join(lines)
