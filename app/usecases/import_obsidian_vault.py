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

from app.services.input_errors import InputRejected
from app.services.obsidian_import.notes import PlannedNote, plan_file_note, source_tag_for
from app.services.obsidian_import.tree import (
    CONTENT_FORMATS,
    CONTENT_MARKDOWN,
    CONTENT_RICH,
    SPLIT_HEADINGS_AND_LISTS,
    SPLIT_MODES,
    SPLIT_NONE,
    SPLIT_PARAGRAPHS,
    NoteNode,
    build_file_tree,
    count_notes,
)
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
_SPLIT_DESCRIPTIONS = {
    SPLIT_NONE: ", kept whole",
    SPLIT_HEADINGS_AND_LISTS: " with its headings and list items as notes under it",
    SPLIT_PARAGRAPHS: " with its headings, list items and paragraphs as notes under it",
}
_CONTENT_DESCRIPTIONS = {CONTENT_RICH: "rich text", CONTENT_MARKDOWN: "Markdown"}


@dataclass
class CmdImportObsidianVault(QueryCommand):
    """Import the Obsidian vault at folder_path (the developer version, PLAN.md), each file
    split and written as split_mode and content_format say."""

    folder_path: str
    split_mode: str
    content_format: str
    token: str
    imported_at: datetime

    def execute(self) -> Dict[str, object]:
        if self.split_mode not in SPLIT_MODES or self.content_format not in CONTENT_FORMATS:
            raise InputRejected("Choose how to split the notes and what to write them in.")
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
            plan_file_note(
                vault_file, uses_strict_line_breaks=vault.uses_strict_line_breaks, source_tag=source_tag,
                split_mode=self.split_mode, content_format=self.content_format,
            )
            for vault_file in vault.markdown_files
        ]
        note_count = sum(count_notes(note.root) for note in planned)
        report_text = _report_text(
            vault, planned, imported_at=self.imported_at, earlier_imports=_earlier_imports(vault),
            note_count=note_count, split_mode=self.split_mode, content_format=self.content_format,
        )
        # The report comes in as the vault does: split and written as chosen.
        report_title, report_body = report_text.split("\n", 1)
        report_root = build_file_tree(
            title_line=report_title, body=report_body.strip("\n"), split_mode=self.split_mode,
            content_format=self.content_format,
        )
        report = _Written(
            node=NoteNode(content_html=report_root.content_html, tags=(*report_root.tags, source_tag), children=report_root.children),
            created_at=self.imported_at, updated_at=self.imported_at,
        )
        files = [_Written(node=note.root, created_at=note.created_at, updated_at=note.updated_at) for note in planned]
        records = _records([report, *files])
        apply_restore_records(records, self.token)
        return {"status": "success", "reportNoteId": report.node_id, "noteCount": note_count}


class _Written:
    """A root note to write with its subtree, under ids given now."""

    def __init__(self, *, node: NoteNode, created_at: datetime, updated_at: datetime):
        self.node = node
        self.created_at = created_at
        self.updated_at = updated_at
        self.node_id = str(uuid.uuid4())


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
            next_id = roots[index + 1].node_id
        elif len(existing_roots) > 0:
            next_id = existing_roots[0]
        records.append(_record(written.node, written, note_id=written.node_id, parent_id=_TOP_LEVEL, prev_id=None, next_id=next_id))
        _append_children(records, written.node, written, parent_id=written.node_id)
    return records


def _append_children(records: List[SimpleNamespace], node: NoteNode, written: _Written, *, parent_id: str) -> None:
    prev_id = None
    for child in node.children:
        child_id = str(uuid.uuid4())
        records.append(_record(child, written, note_id=child_id, parent_id=parent_id, prev_id=prev_id, next_id=None))
        _append_children(records, child, written, parent_id=child_id)
        prev_id = child_id


def _record(
    node: NoteNode, written: _Written, *, note_id: str, parent_id: str | None, prev_id: str | None, next_id: str | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=note_id,
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


def _earlier_imports(vault: VaultContents) -> int:
    """How many earlier import reports of this vault are root notes in the list."""
    prefix = REPORT_TITLE_FORMAT.format(vault=vault.name, at="").removesuffix(_REPORT_TITLE_END) + _REPORT_TITLE_END
    first_lines = [
        extract_plain_text_from_note_html(store.get(note_id).content).split("\n")[0]
        for note_id in store.children(_TOP_LEVEL)
    ]
    return sum(1 for first_line in first_lines if first_line.startswith(prefix))


def _report_text(
    vault: VaultContents, planned: List[PlannedNote], *, imported_at: datetime, earlier_imports: int, note_count: int,
    split_mode: str, content_format: str,
) -> str:
    """The import report as Markdown (§5): counts, what was left out or changed, and every
    imported file."""
    at = imported_at.astimezone().strftime(_REPORT_TIME_FORMAT)
    lines = [REPORT_TITLE_FORMAT.format(vault=vault.name, at=at), "", _DIRECTION_LABEL, ""]
    if earlier_imports > 0:
        lines += [f"**This vault was imported before:** {earlier_imports} earlier import report(s) are in your list.", ""]
    folder_tags = {note.folder_tag for note in planned if note.folder_tag != ""}
    lines += [
        "## Imported", "",
        f"- {len(planned)} Markdown files, as {note_count} notes: each file a note at the top of the list"
        f"{_SPLIT_DESCRIPTIONS[split_mode]}, in {_CONTENT_DESCRIPTIONS[content_format]}.",
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
