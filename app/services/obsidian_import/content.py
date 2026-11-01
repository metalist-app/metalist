"""Turning an imported file's Markdown into note content (PLAN.md, slice 4;
obsidian-mapping.md rows H1-H19): rich text, MetaList's own HTML drawn by MetaList's
Markdown renderer, a formula as a LaTeX region and a footnote as a MetaList footnote; or
Markdown kept as written in an @markdown note, with the footnotes it refers to."""

from __future__ import annotations

import html
import re
from typing import FrozenSet, List, NamedTuple

from app.services.code_rendering import is_highlighted_fence_language
from app.services.file_text_preview import plain_text_to_note_html
from app.services.markdown_rendering import render_note_markdown

LATEX_REGION_TAG = "(((@LaTeX)))"
FOOTNOTE_TAG = "{{@footnote}}"
_LATEX_REGION_FORMAT = "((({source})))"
_FOOTNOTE_SCOPE_FORMAT = "{{{{{body}}}}}"
_LATEX_SPAN_START_RE = re.compile(r'<span class="meta-latex[^"]*" data-latex-source="(?P<source>[^"]*)"[^>]*>')
_SPAN_OPEN = "<span"
_SPAN_CLOSE = "</span>"
_PARAGRAPH_OPEN = "<p>"
_PARAGRAPH_CLOSE = "</p>"
_TASK_BOX_RE = re.compile(r'<span class="meta-markdown-task-toggle"[^>]*aria-checked="(?P<state>true|false)"[^>]*>.*?</span>', re.DOTALL)
_TASK_BOX_TEXT = {"false": "☐ ", "true": "☑ "}
_CODE_LANGUAGE_LABEL_RE = re.compile(r'<span class="meta-code-language">.*?</span>', re.DOTALL)
_FOOTNOTE_REFERENCE_RE = re.compile(r"\[\^(?P<label>[^\]\s]+)\]")
_FOOTNOTE_DEFINITION_LABEL_RE = re.compile(r"^\[\^(?P<label>[^\]\s]+)\]:")
_MERMAID_LANGUAGE = "mermaid"
_PLAIN_CODE_LANGUAGE = "text"
CODE_TAG_FORMAT = "@code={language}"
MERMAID_TAG = "@mermaid"
LATEX_NOTE_TAG = "@LaTeX"
# A quote (a callout too) is MetaList's @quote: a note of its own tagged @quote, or in a
# note holding more, a ((…)) region (PLAN.md, @quote; the maintainer, 2026-10-31).
QUOTE_TAG = "@quote"
QUOTE_REGION_TAG = "((@quote))"
_QUOTE_REGION_OPEN = "(("
_QUOTE_REGION_CLOSE = "))"
_QUOTE_RE = re.compile(r"^<blockquote[^>]*>(?P<inner>.*)</blockquote>$", re.DOTALL)
# What a quote region may hold: paragraphs of text, no other block (a list, a fold).
_PARAGRAPHS_ONLY_RE = re.compile(r"^(?:<p>(?:(?!<p>|</p>|<(?:ul|ol|li|div|details|summary|blockquote|pre|table)\b).)*</p>)+$", re.DOTALL)


class Content(NamedTuple):
    """A note's stored HTML and the tags its content needs (a LaTeX region, footnotes)."""

    html: str
    tags: FrozenSet[str]


def rich_inline(markdown: str, footnote_definitions: List[str]) -> Content:
    """A paragraph's (or heading's, list item's) Markdown as the HTML of a rich text note."""
    rendered = rich_block(markdown, footnote_definitions)
    inner = rendered.html
    if inner.startswith(_PARAGRAPH_OPEN) and inner.endswith(_PARAGRAPH_CLOSE) and inner.count(_PARAGRAPH_OPEN) == 1:
        inner = inner[len(_PARAGRAPH_OPEN):-len(_PARAGRAPH_CLOSE)]
    return Content(html=inner, tags=rendered.tags)


def rich_block(markdown: str, footnote_definitions: List[str]) -> Content:
    """Any block's Markdown (a table, a quote, a callout, HTML, a whole file) as rich text
    HTML: drawn by MetaList's own renderer, formulas then as LaTeX regions, footnotes as
    MetaList's footnotes, task boxes as ☐ and ☑. The writer sanitizes it as pasted HTML."""
    text = markdown
    if len(footnote_definitions) > 0:
        text = markdown + "\n\n" + "\n".join(footnote_definitions)
    note = render_note_markdown(text, takes_footnotes=True)
    rendered = _CODE_LANGUAGE_LABEL_RE.sub("", note.html)
    rendered = _TASK_BOX_RE.sub(lambda box: _TASK_BOX_TEXT[box.group("state")], rendered)
    rendered, has_formulas = _formulas_as_regions(rendered)
    tags = set()
    if has_formulas:
        tags.add(LATEX_REGION_TAG)
    for token, body in note.footnotes:
        body_html, body_has_formulas = _formulas_as_regions(body)
        if body_has_formulas:
            tags.add(LATEX_REGION_TAG)
        rendered = rendered.replace(token, _FOOTNOTE_SCOPE_FORMAT.format(body=body_html))
        tags.add(FOOTNOTE_TAG)
    return Content(html=rendered, tags=frozenset(tags))


def quote_note(markdown: str, footnote_definitions: List[str]) -> Content:
    """A quote or callout as a note of its own: what it says, tagged @quote (a callout's
    first line its type and title in bold, as the renderer draws it)."""
    rendered = rich_block(markdown, footnote_definitions)
    quote = _QUOTE_RE.match(rendered.html)
    assert quote is not None, "a quote block renders as one blockquote"
    inner = quote.group("inner")
    if inner.startswith(_PARAGRAPH_OPEN) and inner.endswith(_PARAGRAPH_CLOSE) and inner.count(_PARAGRAPH_OPEN) == 1:
        inner = inner[len(_PARAGRAPH_OPEN):-len(_PARAGRAPH_CLOSE)]
    return Content(html=inner, tags=rendered.tags | {QUOTE_TAG})


def quote_region(markdown: str, footnote_definitions: List[str]) -> Content:
    """A quote inside a note holding more: its paragraphs as a ((…)) region tagged
    ((@quote)). One holding a list or a fold, or (( or )) of its own, stays a quote as
    HTML: a region could not hold it whole."""
    rendered = rich_block(markdown, footnote_definitions)
    quote = _QUOTE_RE.match(rendered.html)
    assert quote is not None, "a quote block renders as one blockquote"
    inner = quote.group("inner")
    if _PARAGRAPHS_ONLY_RE.match(inner) is None or _QUOTE_REGION_OPEN in inner or _QUOTE_REGION_CLOSE in inner:
        return rendered
    region = (
        _PARAGRAPH_OPEN + _QUOTE_REGION_OPEN + inner[len(_PARAGRAPH_OPEN):-len(_PARAGRAPH_CLOSE)]
        + _QUOTE_REGION_CLOSE + _PARAGRAPH_CLOSE
    )
    return Content(html=region, tags=rendered.tags | {QUOTE_REGION_TAG})


def markdown_note(markdown: str, footnote_definitions: List[str]) -> Content:
    """Markdown kept as written, with the footnote definitions it refers to after it."""
    referenced = {match.group("label").casefold() for match in _FOOTNOTE_REFERENCE_RE.finditer(markdown)}
    kept: List[str] = []
    is_kept = False
    for line in footnote_definitions:
        definition = _FOOTNOTE_DEFINITION_LABEL_RE.match(line)
        if definition is not None:
            is_kept = definition.group("label").casefold() in referenced
        if is_kept:
            kept.append(line)
    text = markdown
    if len(kept) > 0:
        text = markdown + "\n\n" + "\n".join(kept)
    return Content(html=plain_text_to_note_html(text), tags=frozenset())


def code_note(code: str, language: str) -> Content:
    """A fenced code block as a note of its own: highlighted when MetaList knows its
    language, Mermaid as a diagram, plain otherwise (mapping H8, H16)."""
    if language.casefold() == _MERMAID_LANGUAGE:
        return Content(html=plain_text_to_note_html(code), tags=frozenset({MERMAID_TAG}))
    tag_language = _PLAIN_CODE_LANGUAGE
    if language != "" and is_highlighted_fence_language(language):
        tag_language = language
    return Content(html=plain_text_to_note_html(code), tags=frozenset({CODE_TAG_FORMAT.format(language=tag_language)}))


def math_note(source: str) -> Content:
    """A $$ block as an @LaTeX note of its own (mapping H15)."""
    return Content(html=plain_text_to_note_html(source), tags=frozenset({LATEX_NOTE_TAG}))


def rich_code(code: str) -> str:
    """A fenced code block inside a rich text note (a file kept whole): its text as written."""
    return f"<pre><code>{html.escape(code, quote=False)}</code></pre>"


def rich_math(source: str) -> Content:
    """A $$ block inside a rich text note: a LaTeX region of its own line."""
    return Content(
        html=f"<div>{html.escape(_LATEX_REGION_FORMAT.format(source=source), quote=False)}</div>",
        tags=frozenset({LATEX_REGION_TAG}),
    )


def _formulas_as_regions(rendered: str) -> tuple[str, bool]:
    """Each formula the renderer drew (a span holding MathML) as its TeX in a LaTeX region,
    `(((x^2)))`, which MetaList draws in rich text and keeps editable."""
    parts: List[str] = []
    cursor = 0
    found = False
    for start in _LATEX_SPAN_START_RE.finditer(rendered):
        if start.start() < cursor:
            continue
        end = _matching_span_end(rendered, start.end())
        parts.append(rendered[cursor:start.start()])
        source = start.group("source")
        parts.append(_LATEX_REGION_FORMAT.format(source=source))
        cursor = end
        found = True
    parts.append(rendered[cursor:])
    return "".join(parts), found


def _matching_span_end(rendered: str, position: int) -> int:
    """Where the span opened just before position closes, nested spans counted."""
    depth = 1
    while depth > 0:
        next_open = rendered.find(_SPAN_OPEN, position)
        next_close = rendered.find(_SPAN_CLOSE, position)
        assert next_close != -1, "a rendered formula's span is closed"
        if next_open != -1 and next_open < next_close:
            depth += 1
            position = next_open + len(_SPAN_OPEN)
            continue
        depth -= 1
        position = next_close + len(_SPAN_CLOSE)
    return position
