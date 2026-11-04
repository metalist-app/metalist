"""A Markdown file's body as blocks, for splitting it into notes (PLAN.md, slice 4;
import-export-launch.md §2.2): headings, paragraphs, lists with their items, fenced code,
math, tables, quotes (callouts included), HTML and rules, by the same standard rules
MetaList's renderer follows. Footnote definitions are set apart: they belong to the notes
that refer to them, wherever those end up."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

HEADING = "heading"
PARAGRAPH = "paragraph"
LIST = "list"
CODE = "code"
MATH = "math"
TABLE = "table"
QUOTE = "quote"
HTML = "html"
RULE = "rule"

TASK_NONE = ""
TASK_TODO = "todo"
TASK_DONE = "done"

_ATX_HEADING_RE = re.compile(r"^ {0,3}(?P<marks>#{1,6})(?:\s+(?P<text>.*?))?(?:\s+#+)?\s*$")
_FENCE_OPEN_RE = re.compile(r"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})\s*(?P<info>[^`\s]*)")
_MATH_FENCE = "$$"
_ONE_LINE_MATH_RE = re.compile(r"^\s*\$\$(?P<source>.+)\$\$\s*$")
_HORIZONTAL_RULE_RE = re.compile(r"^ {0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$")
_TABLE_DELIMITER_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
_TABLE_CELL_MARK = "|"
_QUOTE_RE = re.compile(r"^ {0,3}>")
_HTML_BLOCK_RE = re.compile(r"^ {0,3}</?[A-Za-z][A-Za-z0-9-]*(?:\s|/?>|$)|^ {0,3}<!--")
_LIST_ITEM_RE = re.compile(r"^(?P<indent>\s*)(?P<marker>[-+*]|(?P<number>\d+)[.)])(?P<gap>\s+)(?P<content>.*)$")
_TASK_RE = re.compile(r"^\[(?P<mark>[ xX])\](?:\s+(?P<text>.*))?$")
_FOOTNOTE_DEFINITION_RE = re.compile(r"^\[\^[^\]\s]+\]:")
_TAB_WIDTH = 4
_CONTINUATION_INDENT = 2
# A table starts with its header row and its delimiter row.
_TABLE_HEAD_LINES = 2


@dataclass(frozen=True)
class ListItem:
    """A list item: its own text (the first paragraph), whether it is a task, and the blocks
    under it (further paragraphs, code, nested lists)."""

    text: str
    task: str
    blocks: Tuple["Block", ...]


@dataclass(frozen=True)
class Block:
    """A block of the body. text is its Markdown as written (a heading's text without its
    marks, code's and math's source without their fences); source its lines as written;
    level is a heading's level; language a code block's; items a list's, with is_ordered
    and its first number."""

    kind: str
    text: str
    source: str
    level: int
    language: str
    items: Tuple[ListItem, ...]
    is_ordered: bool
    start: int


def _block(kind: str, text: str, source: str) -> Block:
    return Block(kind=kind, text=text, source=source, level=0, language="", items=(), is_ordered=False, start=1)


def split_footnote_definitions(lines: List[str]) -> Tuple[List[str], List[str]]:
    """The lines without footnote definitions (`[^1]: text` and its indented lines), outside
    code, and the definitions' own lines, in order."""
    kept: List[str] = []
    definitions: List[str] = []
    fence = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        fence = _fence_after(line, fence)
        if fence != "" or _FOOTNOTE_DEFINITION_RE.match(line) is None:
            kept.append(line)
            index += 1
            continue
        definitions.append(line)
        index += 1
        while index < len(lines) and lines[index].strip() != "" and _indent(lines[index]) >= _CONTINUATION_INDENT:
            definitions.append(lines[index])
            index += 1
    return kept, definitions


def parse_blocks(lines: List[str]) -> List[Block]:
    """The blocks of lines, in order."""
    blocks: List[Block] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip() == "":
            index += 1
            continue
        block, index = _block_at(lines, index)
        blocks.append(block)
    return blocks


def _block_at(lines: List[str], index: int) -> Tuple[Block, int]:
    line = lines[index]
    fence = _FENCE_OPEN_RE.match(line)
    if fence is not None:
        return _code_block(lines, index, fence)
    if line.strip() == _MATH_FENCE:
        return _math_block(lines, index)
    one_line_math = _ONE_LINE_MATH_RE.match(line)
    if one_line_math is not None:
        return _block(MATH, one_line_math.group("source").strip(), line), index + 1
    heading = _ATX_HEADING_RE.match(line)
    if heading is not None:
        text = heading.group("text")
        if text is None:
            text = ""
        block = Block(
            kind=HEADING, text=text, source=line, level=len(heading.group("marks")), language="", items=(),
            is_ordered=False, start=1,
        )
        return block, index + 1
    if _HORIZONTAL_RULE_RE.match(line) is not None:
        return _block(RULE, line.strip(), line), index + 1
    if _is_table_start(lines, index):
        end = index + 1
        while end + 1 < len(lines) and lines[end + 1].strip() != "" and _TABLE_CELL_MARK in lines[end + 1]:
            end += 1
        table = "\n".join(lines[index:end + 1])
        return _block(TABLE, table, table), end + 1
    if _QUOTE_RE.match(line) is not None:
        return _run_block(lines, index, QUOTE)
    if _HTML_BLOCK_RE.match(line) is not None:
        return _run_block(lines, index, HTML)
    if _LIST_ITEM_RE.match(line) is not None:
        return _list_block(lines, index)
    return _paragraph_block(lines, index)


def _code_block(lines: List[str], index: int, fence: re.Match[str]) -> Tuple[Block, int]:
    marks = fence.group("fence")
    indent = len(fence.group("indent"))
    end = index + 1
    while end < len(lines):
        closing = lines[end].strip()
        if closing.startswith(marks) and closing.rstrip(marks[0]) == "":
            break
        end += 1
    code = "\n".join(line[min(indent, _indent(line)):] for line in lines[index + 1:end])
    end = min(end + 1, len(lines))
    block = Block(
        kind=CODE, text=code, source="\n".join(lines[index:end]), level=0, language=fence.group("info"), items=(),
        is_ordered=False, start=1,
    )
    return block, end


def _math_block(lines: List[str], index: int) -> Tuple[Block, int]:
    end = index + 1
    while end < len(lines) and lines[end].strip() != _MATH_FENCE:
        end += 1
    after = min(end + 1, len(lines))
    return _block(MATH, "\n".join(lines[index + 1:end]).strip(), "\n".join(lines[index:after])), after


def _is_table_start(lines: List[str], index: int) -> bool:
    return (
        index + 1 < len(lines)
        and _TABLE_CELL_MARK in lines[index]
        and _TABLE_DELIMITER_RE.match(lines[index + 1]) is not None
    )


def _run_block(lines: List[str], index: int, kind: str) -> Tuple[Block, int]:
    """A quote or an HTML block: its lines up to the next blank line."""
    end = index
    while end < len(lines) and lines[end].strip() != "":
        end += 1
    run = "\n".join(lines[index:end])
    return _block(kind, run, run), end


def _paragraph_block(lines: List[str], index: int) -> Tuple[Block, int]:
    end = index + 1
    while end < len(lines) and lines[end].strip() != "" and not _starts_block(lines, end):
        end += 1
    return _block(PARAGRAPH, "\n".join(line.strip() for line in lines[index:end]), "\n".join(lines[index:end])), end


def _starts_block(lines: List[str], index: int) -> bool:
    line = lines[index]
    starts = [
        _FENCE_OPEN_RE.match(line) is not None,
        line.strip() == _MATH_FENCE,
        _ATX_HEADING_RE.match(line) is not None,
        _HORIZONTAL_RULE_RE.match(line) is not None,
        _QUOTE_RE.match(line) is not None,
        _HTML_BLOCK_RE.match(line) is not None,
        _LIST_ITEM_RE.match(line) is not None,
        _is_table_start(lines, index),
    ]
    return any(starts)


def _list_block(lines: List[str], index: int) -> Tuple[Block, int]:
    """A list: items sharing a marker (CommonMark), each with what is indented under it."""
    first = _LIST_ITEM_RE.match(lines[index])
    assert first is not None
    list_start = index
    list_indent = _indent(lines[index])
    marker = _marker_kind(first)
    number = first.group("number")
    items: List[ListItem] = []
    while index < len(lines):
        item = _LIST_ITEM_RE.match(lines[index])
        if item is None or _indent(lines[index]) != list_indent or _marker_kind(item) != marker:
            break
        list_item, index = _list_item(lines, index, item)
        items.append(list_item)
        next_content = index
        while next_content < len(lines) and lines[next_content].strip() == "":
            next_content += 1
        if next_content < len(lines) and _is_sibling(lines[next_content], list_indent, marker):
            index = next_content
    start = 1
    if number is not None:
        start = int(number)
    source = "\n".join(lines[list_start:index]).rstrip("\n")
    block = Block(
        kind=LIST, text="", source=source, level=0, language="", items=tuple(items), is_ordered=number is not None,
        start=start,
    )
    return block, index


def _is_sibling(line: str, list_indent: int, marker: str) -> bool:
    item = _LIST_ITEM_RE.match(line)
    return item is not None and _indent(line) == list_indent and _marker_kind(item) == marker


def _marker_kind(item: re.Match[str]) -> str:
    marker = item.group("marker")
    if item.group("number") is not None:
        return marker[-1]
    return marker


def _list_item(lines: List[str], index: int, item: re.Match[str]) -> Tuple[ListItem, int]:
    """One item: its first line and lazy continuation lines are its text; lines indented as
    far as its text (after a blank line too) are its own blocks."""
    content_column = _indent(lines[index]) + len(item.group("marker")) + len(item.group("gap"))
    own = [item.group("content")]
    end = index + 1
    while end < len(lines) and lines[end].strip() != "" and not _is_block_start_under(lines, end, content_column):
        own.append(lines[end].strip())
        end += 1
    under: List[str] = []
    while end < len(lines):
        line = lines[end]
        if line.strip() == "":
            following = end
            while following < len(lines) and lines[following].strip() == "":
                following += 1
            if following < len(lines) and _indent(lines[following]) >= content_column:
                under.extend([""] * (following - end))
                end = following
                continue
            break
        if _indent(line) < content_column:
            break
        under.append(line.expandtabs(_TAB_WIDTH)[content_column:])
        end += 1
    text = "\n".join(own)
    task = TASK_NONE
    task_match = _TASK_RE.match(text)
    if task_match is not None:
        task = TASK_TODO
        if task_match.group("mark") != " ":
            task = TASK_DONE
        task_text = task_match.group("text")
        text = ""
        if task_text is not None:
            text = task_text
    return ListItem(text=text, task=task, blocks=tuple(parse_blocks(under))), end


def _is_block_start_under(lines: List[str], index: int, content_column: int) -> bool:
    """Whether a line right under an item's text starts something else: a block of the item
    (indented as far as its text) or a block after the list."""
    if _indent(lines[index]) < content_column:
        return _starts_block(lines, index)
    under = [line.expandtabs(_TAB_WIDTH)[content_column:] for line in lines[index:index + _TABLE_HEAD_LINES]]
    return _starts_block(under, 0)


def _fence_after(line: str, fence: str) -> str:
    """The code fence open after line, given the one open before it ("" for none)."""
    if fence == "":
        opened = _FENCE_OPEN_RE.match(line)
        if opened is None:
            return ""
        return opened.group("fence")
    closing = line.strip()
    if closing.startswith(fence) and closing.rstrip(fence[0]) == "":
        return ""
    return fence


def _indent(line: str) -> int:
    expanded = line.expandtabs(_TAB_WIDTH)
    return len(expanded) - len(expanded.lstrip())
