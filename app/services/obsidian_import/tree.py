"""A file's notes for the chosen split mode and content (PLAN.md, slice 4;
import-export-launch.md §2.2): the file is a root note; with splitting, each heading is a
note with its section under it, a list goes under the paragraph (or heading) before it,
which gets @bullets or @numbered, each item a note, a task @todo or @done; with
paragraphs too, every paragraph is a note, otherwise a run of them stays in one note. Code,
Mermaid and $$ math are notes of their own. Without splitting, the file is one note."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import List, Tuple

from app.services.file_view import plain_text_to_note_html
from app.services.obsidian_import import blocks as block_kinds
from app.services.obsidian_import.blocks import Block, ListItem, parse_blocks, split_footnote_definitions
from app.services.obsidian_import.content import (
    Content,
    code_note,
    markdown_note,
    math_note,
    quote_note,
    quote_region,
    rich_block,
    rich_code,
    rich_inline,
    rich_math,
)

SPLIT_NONE = "none"
SPLIT_HEADINGS_AND_LISTS = "headings-and-lists"
SPLIT_PARAGRAPHS = "paragraphs"
SPLIT_MODES = (SPLIT_NONE, SPLIT_HEADINGS_AND_LISTS, SPLIT_PARAGRAPHS)
CONTENT_RICH = "rich"
CONTENT_MARKDOWN = "markdown"
CONTENT_FORMATS = (CONTENT_RICH, CONTENT_MARKDOWN)
MARKDOWN_TAG = "@markdown"
BULLETS_TAG = "@bullets"
NUMBERED_TAG = "@numbered"
TASK_TAGS = {block_kinds.TASK_TODO: "@todo", block_kinds.TASK_DONE: "@done"}
# A heading that is a note of its own is its text with this tag, as MetaList writes headings,
# not an HTML heading (the maintainer, 2026-10-31: a cleaner export).
HEADING_TAG = "@heading"
_RICH_PARAGRAPH_BREAK = "<br><br>"
_MARKDOWN_PARAGRAPH_BREAK = "\n\n"
_RULE_HTML = "<hr>"
_HEADING_MARK = "#"
_TOP_LEVEL = 0
# Notes whose text a following paragraph may join (Headings and lists keeps a run of them).
_JOINABLE = frozenset({block_kinds.PARAGRAPH, "item"})


# Obsidian's block IDs (`^abc123`) travel through the Markdown as markers, letters and digits
# only, and become anchors of the note holding them (notes.py marks them, mapping F1).
BLOCK_MARKER_FORMAT = "MLOBSIDIANBLOCK{hex}END"
_BLOCK_MARKER_RE = re.compile(r"\s*MLOBSIDIANBLOCK(?P<hex>[0-9a-f]+)END")
HEADING_ANCHOR_PREFIX = "#"
BLOCK_ANCHOR_PREFIX = "^"
_HEADING_KEY_DROPPED = re.compile(r"[*_`=~]")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class NoteNode:
    """A note to write: its id (given now, so links can point at it), its stored HTML, its own
    tags, the headings and block IDs a link can point at in it, and its children in order."""

    note_id: str
    content_html: str
    tags: Tuple[str, ...]
    anchors: Tuple[str, ...]
    children: Tuple["NoteNode", ...]


def heading_anchor(heading: str) -> str:
    """How a heading is matched by a link to it: case, spacing and emphasis marks aside."""
    key = _WHITESPACE_RE.sub(" ", _HEADING_KEY_DROPPED.sub("", heading)).strip().casefold()
    return HEADING_ANCHOR_PREFIX + key


def block_anchor(block_id: str) -> str:
    return BLOCK_ANCHOR_PREFIX + block_id.casefold()


def whole_markdown_note(markdown: str) -> NoteNode:
    """A file kept whole as Markdown: its text as written, block markers aside."""
    text, anchors = _without_block_markers(markdown)
    return NoteNode(
        note_id=str(uuid.uuid4()), content_html=plain_text_to_note_html(text), tags=(MARKDOWN_TAG,),
        anchors=tuple(anchors), children=(),
    )


def _without_block_markers(text: str) -> Tuple[str, List[str]]:
    """text without its block markers, and their anchors."""
    anchors = [block_anchor(bytes.fromhex(marker.group("hex")).decode()) for marker in _BLOCK_MARKER_RE.finditer(text)]
    return _BLOCK_MARKER_RE.sub("", text), anchors


def count_notes(node: NoteNode) -> int:
    return 1 + sum(count_notes(child) for child in node.children)


class _Draft:
    """A note while it is built: rich HTML, or Markdown rendered when it is finished."""

    def __init__(self, *, kind: str, content_format: str, text: str, content: Content):
        self.kind = kind
        # A heading's level (1-6), 0 for every other note.
        self.level = 0
        self.content_format = content_format
        self.markdown = text
        self.html = content.html
        self.tags: List[str] = list(content.tags)
        self.anchors: List[str] = []
        self.children: List[_Draft] = []
        self.list_tag = ""
        self.listed_children = 0

    def add_tag(self, tag: str) -> None:
        if tag not in self.tags:
            self.tags.append(tag)

    def join_paragraph(self, text: str, footnote_definitions: List[str]) -> None:
        if self.content_format == CONTENT_MARKDOWN:
            self.markdown += _MARKDOWN_PARAGRAPH_BREAK + text
            return
        joined = rich_inline(text, footnote_definitions)
        self.html += _RICH_PARAGRAPH_BREAK + joined.html
        for tag in joined.tags:
            self.add_tag(tag)

    def finished(self, footnote_definitions: List[str]) -> NoteNode:
        content_html = self.html
        tags = list(self.tags)
        if self.content_format == CONTENT_MARKDOWN:
            content_html = markdown_note(self.markdown, footnote_definitions).html
            tags.insert(0, MARKDOWN_TAG)
        # A list's holder shows its children as that list only when they all came from lists.
        if self.list_tag != "" and self.listed_children == len(self.children):
            tags.append(self.list_tag)
        return NoteNode(
            note_id=str(uuid.uuid4()),
            content_html=content_html,
            tags=tuple(tags),
            anchors=tuple(self.anchors),
            children=tuple(child.finished(footnote_definitions) for child in self.children),
        )


def build_file_tree(*, title_line: str, body: str, split_mode: str, content_format: str) -> NoteNode:
    """The notes a file's body becomes, under a root note: title_line is its first line, the
    file's first heading when that repeats its name, else the name as Markdown text."""
    assert split_mode in SPLIT_MODES, f"unknown split mode {split_mode!r}"
    assert content_format in CONTENT_FORMATS, f"unknown content {content_format!r}"
    lines, footnote_definitions = split_footnote_definitions(body.split("\n"))
    file_blocks = parse_blocks(lines)
    builder = _Builder(split_mode=split_mode, content_format=content_format, footnote_definitions=footnote_definitions)
    root, root_level = builder.root(title_line)
    rest = file_blocks
    if split_mode == SPLIT_NONE:
        builder.keep_whole(root, rest)
    else:
        builder.place(rest, root, root_level=root_level, holder=None)
    return root.finished(footnote_definitions)


class _Builder:
    def __init__(self, *, split_mode: str, content_format: str, footnote_definitions: List[str]):
        self.split_mode = split_mode
        self.content_format = content_format
        self.footnote_definitions = footnote_definitions

    def root(self, title_line: str) -> Tuple[_Draft, int]:
        """The root note and the heading level its section is under (0 for a plain title)."""
        title_block, title_anchors = _block_without_markers(parse_blocks([title_line])[0])
        if title_block.kind == block_kinds.HEADING:
            root = self.draft(title_block)
            root.anchors.extend(title_anchors)
            return root, title_block.level
        return self.text_draft("title", self.content_format, title_line), _TOP_LEVEL

    def keep_whole(self, root: _Draft, rest: List[Block]) -> None:
        """No splitting: the file is one note, its blocks one after another."""
        if self.content_format == CONTENT_MARKDOWN:
            whole, anchors = _without_block_markers(_MARKDOWN_PARAGRAPH_BREAK.join([root.markdown, *(block.source for block in rest)]))
            root.markdown = whole
            root.anchors.extend(anchors)
            return
        pieces = [f"<div>{root.html}</div>"]
        if root.kind == block_kinds.HEADING and len(rest) > 0:
            # The heading is the top of a note holding more: an HTML heading, not @heading.
            pieces = [f"<h{root.level}>{root.html}</h{root.level}>"]
            root.tags.remove(HEADING_TAG)
        elif root.kind == block_kinds.HEADING:
            pieces = [root.html]
        for block in rest:
            block, anchors = _block_without_markers(block)
            root.anchors.extend(anchors)
            if block.kind == block_kinds.PARAGRAPH and block.text.strip() == "":
                continue
            content = self.whole_block(block)
            pieces.append(content.html)
            for tag in content.tags:
                root.add_tag(tag)
        root.html = "".join(pieces)

    def whole_block(self, block: Block) -> Content:
        if block.kind == block_kinds.CODE:
            return Content(rich_code(block.text), frozenset())
        if block.kind == block_kinds.MATH:
            return rich_math(block.text)
        if block.kind == block_kinds.QUOTE:
            return quote_region(block.source, self.footnote_definitions)
        return rich_block(block.source, self.footnote_definitions)

    def place(self, file_blocks: List[Block], container: _Draft, *, root_level: int, holder: _Draft | None) -> None:
        """file_blocks as notes under container: headings nest by level, lists go under the
        paragraph before them (holder), paragraphs join with Headings and lists."""
        sections: List[Tuple[int, _Draft]] = [(root_level, container)]
        for marked_block in file_blocks:
            block, anchors = _block_without_markers(marked_block)
            parent = sections[-1][1]
            if block.kind == block_kinds.PARAGRAPH and block.text.strip() == "":
                # A block ID on a line of its own names the block before it (a list, a table).
                named = parent
                if len(parent.children) > 0:
                    named = parent.children[-1]
                named.anchors.extend(anchors)
                continue
            if block.kind == block_kinds.HEADING:
                while len(sections) > 1 and sections[-1][0] >= block.level:
                    sections.pop()
                heading = self.draft(block)
                heading.anchors.extend(anchors)
                sections[-1][1].children.append(heading)
                sections.append((block.level, heading))
                holder = None
                continue
            if block.kind == block_kinds.LIST:
                list_holder = parent
                if holder is not None:
                    list_holder = holder
                self.add_list(block, list_holder)
                continue
            if (block.kind == block_kinds.PARAGRAPH and self.split_mode == SPLIT_HEADINGS_AND_LISTS
                    and holder is not None and holder.kind in _JOINABLE and len(holder.children) == 0):
                holder.join_paragraph(block.text, self.footnote_definitions)
                holder.anchors.extend(anchors)
                continue
            note = self.draft(block)
            note.anchors.extend(anchors)
            parent.children.append(note)
            holder = None
            if block.kind == block_kinds.PARAGRAPH:
                holder = note

    def add_list(self, block: Block, holder: _Draft) -> None:
        holder.list_tag = BULLETS_TAG
        if block.is_ordered:
            holder.list_tag = NUMBERED_TAG
        for item in block.items:
            holder.children.append(self.item_draft(item))
            holder.listed_children += 1

    def item_draft(self, item: ListItem) -> _Draft:
        """A list item's note: a task is a MetaList task (@todo, @done) in either content."""
        content_format = self.content_format
        if item.task != block_kinds.TASK_NONE:
            content_format = CONTENT_RICH
        item_text, anchors = _without_block_markers(item.text)
        draft = self.text_draft("item", content_format, item_text)
        draft.anchors.extend(anchors)
        if item.task != block_kinds.TASK_NONE:
            draft.add_tag(TASK_TAGS[item.task])
        self.place(list(item.blocks), draft, root_level=_TOP_LEVEL, holder=draft)
        return draft

    def text_draft(self, kind: str, content_format: str, text: str) -> _Draft:
        if content_format == CONTENT_MARKDOWN:
            return _Draft(kind=kind, content_format=CONTENT_MARKDOWN, text=text, content=Content("", frozenset()))
        return _Draft(kind=kind, content_format=CONTENT_RICH, text="", content=rich_inline(text, self.footnote_definitions))

    def draft(self, block: Block) -> _Draft:
        """A block's own note (a heading's is linked to by its text)."""
        draft = self._draft(block)
        if block.kind == block_kinds.HEADING:
            draft.level = block.level
            draft.anchors.append(heading_anchor(block.text))
        return draft

    def _draft(self, block: Block) -> _Draft:
        if block.kind == block_kinds.CODE:
            return _Draft(kind=block.kind, content_format=CONTENT_RICH, text="", content=code_note(block.text, block.language))
        if block.kind == block_kinds.MATH:
            return _Draft(kind=block.kind, content_format=CONTENT_RICH, text="", content=math_note(block.text))
        if block.kind == block_kinds.PARAGRAPH:
            return self.text_draft(block.kind, self.content_format, block.text)
        if self.content_format == CONTENT_MARKDOWN:
            return _Draft(kind=block.kind, content_format=CONTENT_MARKDOWN, text=block.source.strip(), content=Content("", frozenset()))
        if block.kind == block_kinds.HEADING:
            heading = rich_inline(block.text, self.footnote_definitions)
            return _Draft(
                kind=block.kind, content_format=CONTENT_RICH, text="",
                content=Content(heading.html, heading.tags | {HEADING_TAG}),
            )
        if block.kind == block_kinds.RULE:
            return _Draft(kind=block.kind, content_format=CONTENT_RICH, text="", content=Content(_RULE_HTML, frozenset()))
        if block.kind == block_kinds.QUOTE:
            return _Draft(kind=block.kind, content_format=CONTENT_RICH, text="", content=quote_note(block.source, self.footnote_definitions))
        return _Draft(kind=block.kind, content_format=CONTENT_RICH, text="", content=rich_block(block.source, self.footnote_definitions))


def _block_without_markers(block: Block) -> Tuple[Block, List[str]]:
    """block without block markers in its text and source, and the anchors they name."""
    text, anchors = _without_block_markers(block.text)
    source, _source_anchors = _without_block_markers(block.source)
    if len(anchors) == 0 and source == block.source:
        return block, []
    if len(anchors) == 0:
        _text, anchors = _without_block_markers(block.source)
    return Block(
        kind=block.kind, text=text, source=source, level=block.level, language=block.language, items=block.items,
        is_ordered=block.is_ordered, start=block.start,
    ), anchors


def find_anchor(node: NoteNode, anchor: str) -> NoteNode | None:
    """The note under node (node included) a heading or block anchor names, first in order."""
    if anchor in node.anchors:
        return node
    for child in node.children:
        found = find_anchor(child, anchor)
        if found is not None:
            return found
    return None
