from __future__ import annotations

from app.utils.not_found import NOT_FOUND
import hashlib
import html
import re
from dataclasses import dataclass
from typing import Dict, List, NamedTuple, Tuple
from urllib.parse import urlsplit

from app.services.code_rendering import is_highlighted_fence_language
from app.services.code_rendering import render_fenced_code
from app.services.latex_rendering import render_latex_math_to_html
from app.services.mermaid_note_rendering import found_diagram
from app.services.status_icons import EMPTY_BOX_ICON, TICKED_BOX_ICON


_ORDERED_LIST_RE = re.compile(r"^(\d+)\.\s+(?P<content>.*)$")
# A task: a list item starting [ ] or [x] (2026-10-31; GFM task lists, as Obsidian writes them).
_TASK_RE = re.compile(r"^\[(?P<mark>[ xX])\](?P<content>(?:\s.*)?)$")
_TASK_ICONS = {False: EMPTY_BOX_ICON, True: TICKED_BOX_ICON}
# Footnotes (2026-10-31, GFM and Obsidian): [^label] where [^label]: text is defined on a
# line of its own, and ^[inline text].
_FOOTNOTE_DEFINITION_RE = re.compile(r"^\[\^(?P<label>[^\]\s]+)\]:[ \t]?(?P<text>.*)$")
_FOOTNOTE_REFERENCE_RE = re.compile(r"\[\^(?P<label>[^\]\s]+)\]")
_INLINE_FOOTNOTE_RE = re.compile(r"\^\[(?P<text>[^\[\]\n]+)\]")
# The footnote tokens: plain letters and digits, so no later pass touches them.
_FOOTNOTE_TOKEN_PREFIX = "MLMDFOOTNOTE"
_FOOTNOTE_HASH_LENGTH = 16
_UNORDERED_LIST_RE = re.compile(r"^[-+*]\s+(?P<content>.*)$")
_ATX_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<content>.*)$")
_FENCE_RE = re.compile(r"^```([^\s`]*)\s*$")
_TABLE_DELIMITER_CELL_RE = re.compile(r"^\s*:?-{3,}:?\s*$")
_AUTO_LINK_RE = re.compile(r"(?<![\"'=])(https?://[^\s<]+)")
_CURRENCY_AMOUNT_RE = re.compile(
    r"\$(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\dA-Za-z_.$])"
)
_ALLOWED_MARKDOWN_LINK_SCHEMES = frozenset({"http", "https", "mailto"})
# ![alt](https://…) in a note: web images only.
_IMAGE_SCHEMES = frozenset({"http", "https"})
_IMAGE_MARK = "!"
# A table starts with a header row and a delimiter row.
_TABLE_HEAD_LINE_COUNT = 2
_HORIZONTAL_RULE_MIN_CHARS = 3
_LINK_TEXT_TO_HREF = "]("
# Backslashes pair up into escaped backslashes; an odd one out escapes what follows.
_BACKSLASHES_PER_ESCAPED_BACKSLASH = 2
_TABLE_CELL_SEPARATOR = "|"
# In a table row, `\|` is a pipe inside a cell, not a cell boundary (GFM tables).
_ESCAPED_TABLE_CELL_SEPARATOR = "\\|"
_MARKDOWN_ESCAPE = "\\"
# How many more columns than its list an item needs to sit inside the item above it: two
# spaces, as under "- ", or a tab (_TAB_WIDTH).
_NESTED_LIST_INDENT = 2
_TAB_WIDTH = 4
# A backslash and the one character it escapes.
_ESCAPE_SEQUENCE_LENGTH = 2
# The one raw HTML tag Markdown text may carry: a line break, the standard way to break
# a line in a table cell. Matched after HTML escaping, so code spans keep it as text.
_ESCAPED_LINE_BREAK_TAG_RE = re.compile(r"&lt;br\s*/?&gt;", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _InlinePlaceholder:
    token: str
    html_value: str


@dataclass(frozen=True, slots=True)
class _LatexDelimiter:
    opener: str
    closer: str
    display: str


_LATEX_DELIMITERS = (
    _LatexDelimiter(opener=r"\[", closer=r"\]", display="block"),
    _LatexDelimiter(opener=r"\(", closer=r"\)", display="inline"),
    _LatexDelimiter(opener="$$", closer="$$", display="block"),
    _LatexDelimiter(opener="$", closer="$", display="inline"),
)


_LATEX_SOURCE_ATTRIBUTE_RE = re.compile(r' data-latex-source="[^"]*"')


def strip_latex_source_attributes(html_text: str) -> str:
    """Remove the TeX source that rendered formulas carry for the live view.

    Copied and exported HTML show only the rendered math.
    """
    if not isinstance(html_text, str):
        raise TypeError(f"html_text must be a string, got {type(html_text)}")
    return _LATEX_SOURCE_ATTRIBUTE_RE.sub("", html_text)


def render_markdown_to_html(markdown_text: str) -> str:
    """Markdown as HTML, images and tasks left as written: the AI chat and footnotes draw
    neither (an image address in an AI reply could carry data out when the browser loads
    it; a reply's task is not the user's to tick)."""
    return _note_renderer(markdown_text, is_note_text=False, takes_footnotes=False).render()


class NoteMarkdown(NamedTuple):
    """A Markdown note drawn: its HTML, holding a token where each footnote's number goes,
    and each footnote's token and text as HTML, in order, for footnote_rendering's
    finish_footnotes to number and list as MetaList's own footnotes."""

    html: str
    footnotes: List[Tuple[str, str]]


def render_note_markdown(markdown_text: str, *, takes_footnotes: bool) -> NoteMarkdown:
    """A Markdown note's text as HTML (2026-10-31): ![alt](https://…) images drawn (the
    note's rendering loads them through the image proxy), - [ ] / - [x] tasks as boxes
    numbered in order (data-task-index), which a click ticks (toggle_markdown_task), and
    footnotes ([^1] with [^1]: text, ^[text]) collected when takes_footnotes (a whole
    Markdown note; a Markdown region inside another note leaves them as written)."""
    renderer = _note_renderer(markdown_text, is_note_text=True, takes_footnotes=takes_footnotes)
    return NoteMarkdown(html=renderer.render(), footnotes=list(renderer.footnotes.collected))


def markdown_task_lines(markdown_text: str) -> List[int]:
    """The line of each task in a Markdown note's text, in the order the boxes are
    numbered: the line a click on box N ticks."""
    renderer = _note_renderer(markdown_text, is_note_text=True, takes_footnotes=True)
    renderer.render()
    return list(renderer.task_lines)


def _note_renderer(markdown_text: str, *, is_note_text: bool, takes_footnotes: bool) -> "_MarkdownRenderer":
    if not isinstance(markdown_text, str):
        raise TypeError(f"markdown_text must be a string, got {type(markdown_text)}")
    normalized_text = markdown_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized_text.split("\n")
    footnotes = _DISABLED_FOOTNOTES
    if takes_footnotes:
        lines, definitions = _take_footnote_definitions(lines)
        prefix = _FOOTNOTE_TOKEN_PREFIX + hashlib.sha256(normalized_text.encode()).hexdigest()[:_FOOTNOTE_HASH_LENGTH]
        footnotes = _Footnotes(definitions=definitions, token_prefix=prefix, is_enabled=True)
    return _MarkdownRenderer(
        lines=lines, is_note_text=is_note_text, line_offset=0, task_lines=[], footnotes=footnotes,
    )


class _Footnotes:
    """A Markdown note's footnotes (2026-10-31): their definitions by label, and each
    reference met so far as its token and its text drawn. Disabled for the AI chat and
    footnote text itself: there [^1] and ^[text] stay as written."""

    def __init__(self, *, definitions: Dict[str, str], token_prefix: str, is_enabled: bool):
        self.definitions = definitions
        self.token_prefix = token_prefix
        self.is_enabled = is_enabled
        self.collected: List[Tuple[str, str]] = []

    def marker(self, body_markdown: str) -> str:
        """The token standing where this footnote's number goes; its text is drawn now."""
        assert self.is_enabled, "a disabled footnote list takes no footnotes"
        token = f"{self.token_prefix}N{len(self.collected) + 1}END"
        body_html = _render_inline_markdown(
            body_markdown, allow_links=True, allows_images=False, footnotes=_DISABLED_FOOTNOTES,
        ).replace("\n", "<br>")
        self.collected.append((token, body_html))
        return token


_DISABLED_FOOTNOTES = _Footnotes(definitions={}, token_prefix="", is_enabled=False)


def _take_footnote_definitions(lines: List[str]) -> Tuple[List[str], Dict[str, str]]:
    """The note's lines with each footnote definition blanked (its line stays, so task boxes
    keep their line numbers), and the definitions by casefolded label. A definition is
    [^label]: text on a line of its own, outside code fences, with any indented lines after
    it; the first definition of a label counts."""
    kept: List[str] = []
    definitions: Dict[str, str] = {}
    in_fence = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if _FENCE_RE.match(line.strip()) is not None:
            in_fence = not in_fence
        match = None
        if not in_fence:
            match = _FOOTNOTE_DEFINITION_RE.match(line)
        if match is None:
            kept.append(line)
            index += 1
            continue
        body_lines = [match.group("text")]
        kept.append("")
        index += 1
        while index < len(lines) and lines[index].strip() != "" and _indent_width(lines[index]) >= _NESTED_LIST_INDENT:
            body_lines.append(lines[index].strip())
            kept.append("")
            index += 1
        label = match.group("label").casefold()
        if label not in definitions:
            definitions[label] = "\n".join(body_lines)
    return kept, definitions


class _MarkdownRenderer:
    def __init__(
        self, *, lines: List[str], is_note_text: bool, line_offset: int, task_lines: List[int], footnotes: _Footnotes,
    ):
        if not isinstance(lines, list):
            raise TypeError(f"lines must be a list, got {type(lines)}")
        self._lines = lines
        self._index = 0
        # A note's own text draws web images and task boxes; the AI chat and footnotes don't.
        self._is_note_text = is_note_text
        # Where these lines start in the note's text (a quote's lines are its own renderer's),
        # and the task lines found so far, shared with the renderers of quotes.
        self._line_offset = line_offset
        self.task_lines = task_lines
        self.footnotes = footnotes

    def _inline(self, text: str) -> str:
        return _render_inline_markdown(
            text, allow_links=True, allows_images=self._is_note_text, footnotes=self.footnotes,
        )

    def render(self) -> str:
        if self._lines == [""]:
            return ""
        blocks: List[str] = []
        while self._index < len(self._lines):
            current_line = self._lines[self._index]
            if current_line.strip() == "":
                self._index += 1
                continue
            if self._is_fence_start(current_line):
                blocks.append(self._render_fence_block())
                continue
            if self._is_heading(current_line):
                blocks.append(self._render_heading_block())
                continue
            if self._is_table_start():
                blocks.append(self._render_table_block())
                continue
            if self._is_blockquote_start(current_line):
                blocks.append(self._render_blockquote_block())
                continue
            if self._is_list_start(current_line):
                blocks.append(self._render_list_block())
                continue
            if self._is_horizontal_rule(current_line):
                blocks.append("<hr>")
                self._index += 1
                continue
            blocks.append(self._render_paragraph_block())
        return "".join(blocks)

    def _render_fence_block(self) -> str:
        opening_line = self._lines[self._index]
        # A fence may be indented (under a list item); its code loses that indent.
        match = _FENCE_RE.match(opening_line.strip())
        assert match is not None
        language = match.group(1)
        fence_indent = opening_line[: len(opening_line) - len(opening_line.lstrip())]
        self._index += 1

        content_lines: List[str] = []
        is_closed = False
        while self._index < len(self._lines):
            line = self._lines[self._index]
            if line.strip() == "```":
                self._index += 1
                is_closed = True
                break
            if line.startswith(fence_indent):
                line = line[len(fence_indent):]
            content_lines.append(line)
            self._index += 1

        escaped_code = html.escape("\n".join(content_lines), quote=False)
        if language.casefold() == "mermaid":
            if found_diagram(source="\n".join(content_lines), is_closed=is_closed):
                return ""
            return (
                '<pre class="meta-mermaid-source">'
                f'<code class="language-mermaid">{escaped_code}</code>'
                "</pre>"
            )

        # A language Pygments knows is coloured as @code=<language>; others stay plain.
        if language != "" and is_highlighted_fence_language(language):
            return render_fenced_code(code="\n".join(content_lines), language=language)
        language_attr = ""
        if language != "":
            escaped_language = html.escape(language, quote=True)
            language_attr = f' class="language-{escaped_language}"'
        return f"<pre><code{language_attr}>{escaped_code}</code></pre>"

    def _render_heading_block(self) -> str:
        line = self._lines[self._index]
        match = _ATX_HEADING_RE.match(line.strip())
        assert match is not None
        level = len(match.group("marks"))
        content = match.group("content").strip()
        self._index += 1
        rendered = self._inline(content)
        return f"<h{level}>{rendered}</h{level}>"

    def _render_table_block(self) -> str:
        header_line = self._lines[self._index]
        delimiter_line = self._lines[self._index + 1]
        header_cells = _split_table_row(header_line)
        delimiter_cells = _split_table_row(delimiter_line)
        assert len(header_cells) == len(delimiter_cells)

        self._index += _TABLE_HEAD_LINE_COUNT
        body_rows: List[List[str]] = []
        while self._index < len(self._lines):
            line = self._lines[self._index]
            if line.strip() == "" or not _looks_like_table_row(line):
                break
            body_rows.append(
                _fit_row_to_columns(cells=_split_table_row(line), column_count=len(header_cells))
            )
            self._index += 1

        # The wrapper scrolls a table sideways when its words can't all fit side by side.
        parts: List[str] = ['<div class="meta-markdown-table-wrap">', "<table>", "<thead>", "<tr>"]
        for cell in header_cells:
            parts.append(f"<th>{self._inline(cell.strip())}</th>")
        parts.extend(["</tr>", "</thead>"])
        if body_rows:
            parts.append("<tbody>")
            for row in body_rows:
                parts.append("<tr>")
                for cell in row:
                    parts.append(f"<td>{self._inline(cell.strip())}</td>")
                parts.append("</tr>")
            parts.append("</tbody>")
        parts.extend(["</table>", "</div>"])
        return "".join(parts)

    def _render_blockquote_block(self) -> str:
        quote_start = self._index
        quote_lines: List[str] = []
        while self._index < len(self._lines):
            line = self._lines[self._index]
            if line.strip() == "":
                quote_lines.append("")
                self._index += 1
                continue
            if not self._is_blockquote_start(line):
                break
            stripped = line.lstrip()
            assert stripped.startswith(">")
            stripped = stripped[1:]
            if stripped.startswith(" "):
                stripped = stripped[1:]
            quote_lines.append(stripped)
            self._index += 1
        inner_html = _MarkdownRenderer(
            lines=quote_lines, is_note_text=self._is_note_text, line_offset=self._line_offset + quote_start,
            task_lines=self.task_lines, footnotes=self.footnotes,
        ).render()
        return f"<blockquote>{inner_html}</blockquote>"

    def _render_list_block(self) -> str:
        """A list and the lists nested in its items (2026-10-31): an item indented at least
        _NESTED_LIST_INDENT columns more than its list belongs inside the item above it."""
        first_line = self._lines[self._index]
        list_indent = _indent_width(first_line)
        ordered_match = _ORDERED_LIST_RE.match(first_line.strip())
        is_ordered = ordered_match is not None
        tag_name = "ul"
        opening_tag = "<ul>"
        if is_ordered:
            tag_name = "ol"
            assert ordered_match is not None
            start_number = int(ordered_match.group(1))
            opening_tag = "<ol>"
            if start_number != 1:
                opening_tag = f'<ol start="{start_number}">'
        items: List[str] = []

        while self._index < len(self._lines):
            line = self._lines[self._index]
            if line.strip() == "":
                next_content_index = self._next_content_index(self._index)
                if next_content_index < len(self._lines) and self._is_sibling_item(
                    line=self._lines[next_content_index], list_indent=list_indent, is_ordered=is_ordered,
                ):
                    self._index = next_content_index
                    continue
                break
            if not self._is_sibling_item(line=line, list_indent=list_indent, is_ordered=is_ordered):
                break
            items.append(self._render_list_item(is_ordered=is_ordered, list_indent=list_indent))

        return f"{opening_tag}{''.join(items)}</{tag_name}>"

    def _render_list_item(self, *, is_ordered: bool, list_indent: int) -> str:
        line = self._lines[self._index]
        stripped = line.strip()
        if is_ordered:
            match = _ORDERED_LIST_RE.match(stripped)
        else:
            match = _UNORDERED_LIST_RE.match(stripped)
        assert match is not None
        item_content = match.group("content")
        task_box = ""
        task_match = _TASK_RE.match(item_content)
        if self._is_note_text and task_match is not None:
            task_box = self._task_box(is_ticked=task_match.group("mark") != " ")
            item_content = task_match.group("content").lstrip()
        item_lines = [item_content]
        nested_lists: List[str] = []
        self._index += 1

        while self._index < len(self._lines):
            next_line = self._lines[self._index]
            if next_line.strip() == "":
                # A blank line before a nested list keeps it in this item.
                next_content_index = self._next_content_index(self._index)
                if next_content_index < len(self._lines) and self._is_nested_item(
                    line=self._lines[next_content_index], list_indent=list_indent,
                ):
                    self._index = next_content_index
                    continue
                break
            if self._is_nested_item(line=next_line, list_indent=list_indent):
                nested_lists.append(self._render_list_block())
                continue
            if self._is_list_start(next_line):
                break
            if self._is_block_start(next_line):
                break
            if nested_lists:
                break
            if next_line.startswith("  ") or next_line.startswith("\t"):
                item_lines.append(next_line.lstrip())
                self._index += 1
                continue
            break

        rendered = self._inline("\n".join(item_lines))
        rendered = rendered.replace("\n", "<br>\n")
        if task_box != "":
            return f'<li class="meta-markdown-task">{task_box}{rendered}{"".join(nested_lists)}</li>'
        return f"<li>{rendered}{''.join(nested_lists)}</li>"

    def _task_box(self, *, is_ticked: bool) -> str:
        """The box of the task on the current line, numbered in order through the note."""
        task_index = len(self.task_lines)
        self.task_lines.append(self._line_offset + self._index)
        icon = _TASK_ICONS[is_ticked]
        state = str(is_ticked).lower()
        return (
            f'<span class="meta-markdown-task-toggle" role="checkbox" aria-checked="{state}" '
            f'data-task-index="{task_index}">{icon}</span>'
        )

    def _next_content_index(self, index: int) -> int:
        """The first line at or after index that is not blank, or the number of lines."""
        while index < len(self._lines) and self._lines[index].strip() == "":
            index += 1
        return index

    def _is_nested_item(self, *, line: str, list_indent: int) -> bool:
        return self._is_list_start(line) and _indent_width(line) >= list_indent + _NESTED_LIST_INDENT

    def _is_sibling_item(self, *, line: str, list_indent: int, is_ordered: bool) -> bool:
        indent = _indent_width(line)
        if indent < list_indent or indent >= list_indent + _NESTED_LIST_INDENT:
            return False
        return self._is_matching_list_item(line=line, is_ordered=is_ordered)

    def _render_paragraph_block(self) -> str:
        paragraph_lines: List[str] = []
        while self._index < len(self._lines):
            line = self._lines[self._index]
            if line.strip() == "":
                break
            if paragraph_lines and self._is_block_start(line):
                break
            paragraph_lines.append(line)
            self._index += 1

        rendered = self._inline("\n".join(paragraph_lines))
        rendered = rendered.replace("\n", "<br>\n")
        return f"<p>{rendered}</p>"

    def _is_block_start(self, line: str) -> bool:
        if self._is_heading(line):
            return True
        if self._is_fence_start(line):
            return True
        if self._is_blockquote_start(line):
            return True
        if self._is_list_start(line):
            return True
        if self._is_horizontal_rule(line):
            return True
        if self._is_table_start():
            return True
        return False

    def _is_heading(self, line: str) -> bool:
        return _ATX_HEADING_RE.match(line.strip()) is not None

    def _is_fence_start(self, line: str) -> bool:
        return _FENCE_RE.match(line.strip()) is not None

    def _is_blockquote_start(self, line: str) -> bool:
        return line.lstrip().startswith(">")

    def _is_list_start(self, line: str) -> bool:
        stripped = line.strip()
        if _UNORDERED_LIST_RE.match(stripped) is not None:
            return True
        if _ORDERED_LIST_RE.match(stripped) is not None:
            return True
        return False

    def _is_matching_list_item(self, *, line: str, is_ordered: bool) -> bool:
        stripped = line.strip()
        if is_ordered:
            return _ORDERED_LIST_RE.match(stripped) is not None
        return _UNORDERED_LIST_RE.match(stripped) is not None

    def _is_horizontal_rule(self, line: str) -> bool:
        stripped = line.strip()
        if len(stripped) < _HORIZONTAL_RULE_MIN_CHARS:
            return False
        if any(ch not in {"-", "*", "_"} for ch in stripped):
            return False
        return len(set(stripped)) == 1

    def _is_table_start(self) -> bool:
        if self._index + 1 >= len(self._lines):
            return False
        header_line = self._lines[self._index]
        delimiter_line = self._lines[self._index + 1]
        if not _looks_like_table_row(header_line):
            return False
        if not _is_table_delimiter_row(delimiter_line):
            return False
        return len(_split_table_row(header_line)) == len(
            _split_table_row(delimiter_line)
        )


def _indent_width(line: str) -> int:
    """The columns of space before a line's text, a tab counting _TAB_WIDTH."""
    expanded = line.expandtabs(_TAB_WIDTH)
    return len(expanded) - len(expanded.lstrip())


def _split_table_row(line: str) -> list[str]:
    trimmed = line.strip()
    if trimmed.startswith(_TABLE_CELL_SEPARATOR):
        trimmed = trimmed[1:]
    cells = _split_on_unescaped_separators(trimmed)
    # A trailing separator closes the last cell; it does not open an empty one.
    if len(cells) > 1 and cells[-1] == "":
        cells.pop()
    return [
        cell.replace(_ESCAPED_TABLE_CELL_SEPARATOR, _TABLE_CELL_SEPARATOR).strip()
        for cell in cells
    ]


def _split_on_unescaped_separators(text: str) -> list[str]:
    """Split a row's text at each `|` that no backslash escapes."""
    cells: list[str] = []
    cell_start = 0
    cursor = 0
    while cursor < len(text):
        if text[cursor] == _MARKDOWN_ESCAPE:
            cursor += _ESCAPE_SEQUENCE_LENGTH
            continue
        if text[cursor] == _TABLE_CELL_SEPARATOR:
            cells.append(text[cell_start:cursor])
            cell_start = cursor + 1
        cursor += 1
    cells.append(text[cell_start:])
    return cells


def _fit_row_to_columns(*, cells: list[str], column_count: int) -> list[str]:
    """Give a body row the header's column count, as GFM does: pad with empty cells, drop extras."""
    assert column_count > 0
    missing_count = column_count - len(cells)
    return cells[:column_count] + [""] * max(missing_count, 0)


def _looks_like_table_row(line: str) -> bool:
    return "|" in line


def _is_table_delimiter_row(line: str) -> bool:
    if not _looks_like_table_row(line):
        return False
    cells = _split_table_row(line)
    if not cells:
        return False
    return all(_TABLE_DELIMITER_CELL_RE.match(cell) is not None for cell in cells)


def _render_inline_markdown(text: str, *, allow_links: bool, allows_images: bool, footnotes: _Footnotes) -> str:
    if not isinstance(text, str):
        raise TypeError(f"text must be a string, got {type(text)}")
    if text == "":
        return ""

    placeholders: List[_InlinePlaceholder] = []
    rendered = html.escape(text, quote=False)
    rendered = _extract_code_spans(rendered, placeholders)
    rendered = _ESCAPED_LINE_BREAK_TAG_RE.sub("<br>", rendered)
    if footnotes.is_enabled:
        rendered = _extract_footnote_references(rendered, placeholders, footnotes)
    if allow_links:
        rendered = _extract_markdown_links(rendered, placeholders, allows_images=allows_images)
        rendered = _extract_auto_links(rendered, placeholders)
    rendered = _extract_currency_amounts(rendered, placeholders)
    rendered = _extract_latex_math(rendered, placeholders)
    rendered = _replace_strong(rendered)
    rendered = _replace_emphasis(rendered)
    rendered = _replace_strikethrough(rendered)
    rendered = _replace_highlight(rendered)
    rendered = rendered.replace("\\\n", "\n")
    for placeholder in placeholders:
        rendered = rendered.replace(placeholder.token, placeholder.html_value)
    return rendered


def _extract_footnote_references(text: str, placeholders: List[_InlinePlaceholder], footnotes: _Footnotes) -> str:
    """[^label] of a defined footnote, and ^[inline text], as footnote tokens; [^label] with
    no definition stays as written. text is HTML-escaped; footnote text is unescaped to be
    drawn again as Markdown."""

    def reference(match: re.Match[str]) -> str:
        label = match.group("label").casefold()
        if label not in footnotes.definitions:
            return match.group(0)
        return _make_placeholder(placeholders=placeholders, html_value=footnotes.marker(footnotes.definitions[label]))

    def inline(match: re.Match[str]) -> str:
        return _make_placeholder(
            placeholders=placeholders, html_value=footnotes.marker(html.unescape(match.group("text"))),
        )

    return _INLINE_FOOTNOTE_RE.sub(inline, _FOOTNOTE_REFERENCE_RE.sub(reference, text))


def _extract_code_spans(text: str, placeholders: List[_InlinePlaceholder]) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    output: List[str] = []
    cursor = 0
    while cursor < len(text):
        start = text.find("`", cursor)
        if start == NOT_FOUND:
            output.append(text[cursor:])
            break
        fence_len = _count_repeated_char(text=text, start=start, char="`")
        end = text.find("`" * fence_len, start + fence_len)
        if end == NOT_FOUND:
            output.append(text[cursor:])
            break
        output.append(text[cursor:start])
        code_content = text[start + fence_len : end]
        code_content = code_content.replace("\n", " ")
        placeholder = _make_placeholder(
            placeholders=placeholders,
            html_value=f"<code>{code_content}</code>",
        )
        output.append(placeholder)
        cursor = end + fence_len
    return "".join(output)


def _extract_markdown_links(text: str, placeholders: List[_InlinePlaceholder], *, allows_images: bool) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    output: List[str] = []
    cursor = 0
    while cursor < len(text):
        start = text.find("[", cursor)
        if start == NOT_FOUND:
            output.append(text[cursor:])
            break
        open_paren = text.find(_LINK_TEXT_TO_HREF, start)
        if open_paren == NOT_FOUND:
            output.append(text[cursor:])
            break
        close_paren = _find_unescaped_char(text=text, start=open_paren + len(_LINK_TEXT_TO_HREF), target=")")
        if close_paren == NOT_FOUND:
            output.append(text[cursor:])
            break
        link_text = text[start + 1 : open_paren]
        href = text[open_paren + len(_LINK_TEXT_TO_HREF) : close_paren].strip()
        is_image = allows_images and start > cursor and text[start - len(_IMAGE_MARK)] == _IMAGE_MARK
        if is_image:
            image_html = _markdown_image_html(alt=link_text, src=href)
            if image_html is None:
                # A path or another scheme: no image to load, so the text stays as written.
                output.append(text[cursor : close_paren + 1])
            else:
                output.append(text[cursor : start - len(_IMAGE_MARK)])
                output.append(_make_placeholder(placeholders=placeholders, html_value=image_html))
            cursor = close_paren + 1
            continue
        output.append(text[cursor:start])
        if href == "":
            output.append(text[start : close_paren + 1])
            cursor = close_paren + 1
            continue
        parsed_href = urlsplit(html.unescape(href))
        if (
            parsed_href.scheme != ""
            and parsed_href.scheme.casefold() not in _ALLOWED_MARKDOWN_LINK_SCHEMES
        ):
            output.append(text[start : close_paren + 1])
            cursor = close_paren + 1
            continue
        link_html = (
            f'<a href="{html.escape(html.unescape(href), quote=True)}" '
            'target="_blank" rel="noopener noreferrer">'
            f"{_render_inline_markdown(html.unescape(link_text), allow_links=False, allows_images=False, footnotes=_DISABLED_FOOTNOTES)}"
            "</a>"
        )
        placeholder = _make_placeholder(placeholders=placeholders, html_value=link_html)
        output.append(placeholder)
        cursor = close_paren + 1
    return "".join(output)


def _markdown_image_html(*, alt: str, src: str) -> str | None:
    """![alt](https://…) as an image, or None for any other address (a path, another
    scheme): that stays as written. alt and src arrive HTML-escaped."""
    address = html.unescape(src)
    if urlsplit(address).scheme.casefold() not in _IMAGE_SCHEMES:
        return None
    return (
        f'<img src="{html.escape(address, quote=True)}" '
        f'alt="{html.escape(html.unescape(alt), quote=True)}" loading="lazy">'
    )


def _extract_auto_links(text: str, placeholders: List[_InlinePlaceholder]) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    output: List[str] = []
    cursor = 0
    for match in _AUTO_LINK_RE.finditer(text):
        output.append(text[cursor:match.start()])
        url = match.group(1)
        placeholder = _make_placeholder(
            placeholders=placeholders,
            html_value=(
                f'<a href="{html.escape(html.unescape(url), quote=True)}" '
                'target="_blank" rel="noopener noreferrer">'
                f"{url}"
                "</a>"
            ),
        )
        output.append(placeholder)
        cursor = match.end()
    output.append(text[cursor:])
    return "".join(output)


def _extract_latex_math(text: str, placeholders: List[_InlinePlaceholder]) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    output: List[str] = []
    cursor = 0
    while cursor < len(text):
        delimiter = _latex_delimiter_at(text=text, index=cursor)
        if delimiter is None:
            output.append(text[cursor])
            cursor += 1
            continue

        content_start = cursor + len(delimiter.opener)
        close_index = _find_latex_closing_delimiter(
            text=text,
            start=content_start,
            delimiter=delimiter,
        )
        if close_index == NOT_FOUND:
            output.append(text[cursor])
            cursor += 1
            continue

        escaped_source = text[content_start:close_index]
        latex_source = html.unescape(escaped_source)
        if latex_source.strip() == "":
            output.append(text[cursor : close_index + len(delimiter.closer)])
            cursor = close_index + len(delimiter.closer)
            continue

        rendered_math = render_latex_math_to_html(
            latex_source,
            display=delimiter.display,
        )
        class_names = ["meta-latex"]
        if rendered_math.has_error:
            class_names.append("meta-latex-error")
        elif delimiter.display == "inline":
            class_names.append("meta-latex-inline")
        else:
            class_names.append("meta-latex-display")
        placeholder = _make_placeholder(
            placeholders=placeholders,
            html_value=(
                # The TeX source lets the browser map a clicked formula back
                # to its source when entering edit mode (and back on leaving).
                f'<span class="{" ".join(class_names)}" data-latex-source="{html.escape(latex_source, quote=True)}">'
                f"{rendered_math.html}"
                "</span>"
            ),
        )
        output.append(placeholder)
        cursor = close_index + len(delimiter.closer)

    return "".join(output)


def _extract_currency_amounts(
    text: str,
    placeholders: List[_InlinePlaceholder],
) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    output: List[str] = []
    cursor = 0
    for match in _CURRENCY_AMOUNT_RE.finditer(text):
        output.append(text[cursor:match.start()])
        if _is_escaped_delimiter(text=text, index=match.start()):
            output.append(match.group(0))
        elif _is_currency_amount(text=text, match=match):
            output.append(
                _make_placeholder(
                    placeholders=placeholders,
                    html_value=match.group(0),
                )
            )
        else:
            output.append(match.group(0))
        cursor = match.end()
    output.append(text[cursor:])
    return "".join(output)


def _is_currency_amount(*, text: str, match: re.Match[str]) -> bool:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    amount_end = match.end()
    next_dollar = _find_unescaped_char(text=text, start=amount_end, target="$")
    if next_dollar == NOT_FOUND:
        return True
    if next_dollar + 1 < len(text) and text[next_dollar + 1].isdigit():
        return True
    between_amounts = text[amount_end:next_dollar]
    if "**" in between_amounts or "__" in between_amounts:
        return True
    return any(character.isalpha() for character in between_amounts)


def _latex_delimiter_at(*, text: str, index: int) -> _LatexDelimiter | None:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not isinstance(index, int):
        raise TypeError("index must be an int")

    for delimiter in _LATEX_DELIMITERS:
        if not text.startswith(delimiter.opener, index):
            continue
        if _is_escaped_delimiter(text=text, index=index):
            continue
        if delimiter.opener == "$" and not _is_valid_inline_dollar_opener(
            text=text,
            index=index,
        ):
            continue
        return delimiter
    return None


def _find_latex_closing_delimiter(
    *,
    text: str,
    start: int,
    delimiter: _LatexDelimiter,
) -> int:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not isinstance(start, int):
        raise TypeError("start must be an int")

    cursor = start
    while cursor < len(text):
        if not text.startswith(delimiter.closer, cursor):
            cursor += 1
            continue
        if _is_escaped_delimiter(text=text, index=cursor):
            cursor += 1
            continue
        if delimiter.closer == "$" and not _is_valid_inline_dollar_closer(
            text=text,
            index=cursor,
        ):
            cursor += 1
            continue
        return cursor
    return NOT_FOUND


def _is_escaped_delimiter(*, text: str, index: int) -> bool:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not isinstance(index, int):
        raise TypeError("index must be an int")

    backslash_count = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslash_count += 1
        cursor -= 1
    return backslash_count % _BACKSLASHES_PER_ESCAPED_BACKSLASH == 1


def _is_valid_inline_dollar_opener(*, text: str, index: int) -> bool:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not isinstance(index, int):
        raise TypeError("index must be an int")

    next_index = index + 1
    if next_index >= len(text):
        return False
    if text[next_index] == "$":
        return False
    return not text[next_index].isspace()


def _is_valid_inline_dollar_closer(*, text: str, index: int) -> bool:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not isinstance(index, int):
        raise TypeError("index must be an int")

    if index == 0 or text[index - 1].isspace():
        return False
    next_index = index + 1
    if next_index >= len(text):
        return True
    return text[next_index] != "$"


def _replace_strong(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)


def _replace_emphasis(text: str) -> str:
    text = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", text)
    return re.sub(r"(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)", r"<em>\1</em>", text)


def _replace_strikethrough(text: str) -> str:
    return re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)


# ==text== highlights (2026-10-31, as Obsidian writes them); the text starts and ends with
# something other than a space or =, so `a == b == c` and `====` stay as written.
_HIGHLIGHT_RE = re.compile(r"(?<!=)==(?=[^\s=])(.+?)(?<=[^\s=])==(?!=)")


def _replace_highlight(text: str) -> str:
    return _HIGHLIGHT_RE.sub(r"<mark>\1</mark>", text)


def _count_repeated_char(*, text: str, start: int, char: str) -> int:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not isinstance(start, int):
        raise TypeError("start must be an int")
    if not isinstance(char, str) or len(char) != 1:
        raise TypeError("char must be a single-character string")

    cursor = start
    while cursor < len(text) and text[cursor] == char:
        cursor += 1
    return cursor - start


def _find_unescaped_char(*, text: str, start: int, target: str) -> int:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not isinstance(start, int):
        raise TypeError("start must be an int")
    if not isinstance(target, str) or len(target) != 1:
        raise TypeError("target must be a single-character string")

    cursor = start
    while cursor < len(text):
        if text[cursor] == target and (cursor == 0 or text[cursor - 1] != "\\"):
            return cursor
        cursor += 1
    return NOT_FOUND


def _make_placeholder(*, placeholders: List[_InlinePlaceholder], html_value: str) -> str:
    if not isinstance(html_value, str):
        raise TypeError(f"html_value must be a string, got {type(html_value)}")
    token = f"@@MLMD[{len(placeholders)}]@@"
    placeholders.append(_InlinePlaceholder(token=token, html_value=html_value))
    return token
