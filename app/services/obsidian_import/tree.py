"""A file's notes for the chosen split mode and content (PLAN.md, slice 4;
import-export-launch.md §2.2): the file is a root note; with splitting, each heading is a
note with its section under it, a list goes under the paragraph (or heading) before it,
which gets @bullets or @numbered, each item a note, a task @todo or @done; with
paragraphs too, every paragraph is a note, otherwise a run of them stays in one note. Code,
Mermaid and $$ math are notes of their own. Without splitting, the file is one note."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from app.services.obsidian_import import blocks as block_kinds
from app.services.obsidian_import.blocks import Block, ListItem, parse_blocks, split_footnote_definitions
from app.services.obsidian_import.content import (
    Content,
    code_note,
    markdown_note,
    math_note,
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
_RICH_PARAGRAPH_BREAK = "<br><br>"
_MARKDOWN_PARAGRAPH_BREAK = "\n\n"
_RULE_HTML = "<hr>"
_HEADING_MARK = "#"
_TOP_LEVEL = 0
# Notes whose text a following paragraph may join (Headings and lists keeps a run of them).
_JOINABLE = frozenset({block_kinds.PARAGRAPH, "item"})


@dataclass(frozen=True)
class NoteNode:
    """A note to write: its stored HTML, its own tags, its children in order."""

    content_html: str
    tags: Tuple[str, ...]
    children: Tuple["NoteNode", ...]


def count_notes(node: NoteNode) -> int:
    return 1 + sum(count_notes(child) for child in node.children)


class _Draft:
    """A note while it is built: rich HTML, or Markdown rendered when it is finished."""

    def __init__(self, *, kind: str, content_format: str, text: str, content: Content):
        self.kind = kind
        self.content_format = content_format
        self.markdown = text
        self.html = content.html
        self.tags: List[str] = list(content.tags)
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
            content_html=content_html,
            tags=tuple(tags),
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
        title_block = parse_blocks([title_line])[0]
        if title_block.kind == block_kinds.HEADING:
            return self.draft(title_block), title_block.level
        return self.text_draft("title", self.content_format, title_line), _TOP_LEVEL

    def keep_whole(self, root: _Draft, rest: List[Block]) -> None:
        """No splitting: the file is one note, its blocks one after another."""
        if self.content_format == CONTENT_MARKDOWN:
            root.markdown = _MARKDOWN_PARAGRAPH_BREAK.join([root.markdown, *(block.source for block in rest)])
            return
        pieces = [root.html]
        if root.kind != block_kinds.HEADING:
            pieces = [f"<div>{root.html}</div>"]
        for block in rest:
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
        return rich_block(block.source, self.footnote_definitions)

    def place(self, file_blocks: List[Block], container: _Draft, *, root_level: int, holder: _Draft | None) -> None:
        """file_blocks as notes under container: headings nest by level, lists go under the
        paragraph before them (holder), paragraphs join with Headings and lists."""
        sections: List[Tuple[int, _Draft]] = [(root_level, container)]
        for block in file_blocks:
            parent = sections[-1][1]
            if block.kind == block_kinds.HEADING:
                while len(sections) > 1 and sections[-1][0] >= block.level:
                    sections.pop()
                heading = self.draft(block)
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
                continue
            note = self.draft(block)
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
        draft = self.text_draft("item", content_format, item.text)
        if item.task != block_kinds.TASK_NONE:
            draft.add_tag(TASK_TAGS[item.task])
        self.place(list(item.blocks), draft, root_level=_TOP_LEVEL, holder=draft)
        return draft

    def text_draft(self, kind: str, content_format: str, text: str) -> _Draft:
        if content_format == CONTENT_MARKDOWN:
            return _Draft(kind=kind, content_format=CONTENT_MARKDOWN, text=text, content=Content("", frozenset()))
        return _Draft(kind=kind, content_format=CONTENT_RICH, text="", content=rich_inline(text, self.footnote_definitions))

    def draft(self, block: Block) -> _Draft:
        """A block's own note."""
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
                content=Content(f"<h{block.level}>{heading.html}</h{block.level}>", heading.tags),
            )
        if block.kind == block_kinds.RULE:
            return _Draft(kind=block.kind, content_format=CONTENT_RICH, text="", content=Content(_RULE_HTML, frozenset()))
        return _Draft(kind=block.kind, content_format=CONTENT_RICH, text="", content=rich_block(block.source, self.footnote_definitions))

