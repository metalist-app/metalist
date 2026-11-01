"""Links and embeds in an imported file (PLAN.md, slice 2; obsidian-mapping.md rows D1-D9,
E1-E8): each `[[Note]]`, `[[Note#Heading|text]]`, `![[photo.png|300]]` and Markdown link to a
file of the vault is set aside as a token while the file is planned, and becomes MetaList's
own reference (`[[UUID]]`, `![[UUID]]`) once every note and file has its id. Links in code
stay as written."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple
from urllib.parse import unquote

# A token: letters and digits only, so no Markdown pass reads it as syntax.
LINK_TOKEN_FORMAT = "MLOBSIDIANLINK{index}END"
LINK_TOKEN_RE = re.compile(r"MLOBSIDIANLINK(?P<index>\d+)END")
_WIKI_LINK_RE = re.compile(r"(?P<embed>!?)\[\[(?P<target>[^\[\]|#^]*)(?:#(?P<subpath>[^\[\]|]*))?(?:\|(?P<text>[^\[\]]*))?\]\]")
_MARKDOWN_LINK_RE = re.compile(r"(?P<embed>!?)\[(?P<text>[^\[\]]*)\]\((?P<href><[^>]+>|[^)\s]+)(?:\s+\"[^\"]*\")?\)")
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_FENCE_RE = re.compile(r"^ {0,3}(?:```|~~~)")
_CODE_SPAN_RE = re.compile(r"(`+)(.+?)\1")
_BLOCK_SUBPATH_MARK = "^"
_SUBPATH_MARK = "#"
_ANGLE_OPEN = "<"
_ANGLE_CLOSE = ">"
_TABLE_PIPE_ESCAPE = "\\"


@dataclass(frozen=True)
class LinkReference:
    """A link or embed as written: its target (a note's or file's name or path, "" for this
    note), the heading or block it points into, its own text, and the text written."""

    target: str
    heading: str
    block_id: str
    text: str
    is_embed: bool
    is_markdown_link: bool
    written: str


def tokenize_links(lines: List[str], references: List[LinkReference]) -> List[str]:
    """The lines with each link or embed outside code replaced by a token; its reference
    appended to references, the token holding its index there."""
    tokenized: List[str] = []
    fence = ""
    for line in lines:
        if fence == "":
            opened = _FENCE_RE.match(line)
            if opened is not None:
                fence = line.strip()[:len("```")]
                tokenized.append(line)
                continue
            tokenized.append(_tokenize_outside_code_spans(line, references))
            continue
        if line.strip().startswith(fence):
            fence = ""
        tokenized.append(line)
    return tokenized


def _tokenize_outside_code_spans(line: str, references: List[LinkReference]) -> str:
    parts: List[str] = []
    cursor = 0
    for code in _CODE_SPAN_RE.finditer(line):
        parts.append(_tokenize(line[cursor:code.start()], references))
        parts.append(code.group(0))
        cursor = code.end()
    parts.append(_tokenize(line[cursor:], references))
    return "".join(parts)


def _tokenize(text: str, references: List[LinkReference]) -> str:
    text = _WIKI_LINK_RE.sub(lambda link: _wiki_token(link, references), text)
    return _MARKDOWN_LINK_RE.sub(lambda link: _markdown_token(link, references), text)


def _wiki_token(link: re.Match[str], references: List[LinkReference]) -> str:
    heading, block_id = _subpath_parts(link.group("subpath"))
    text = link.group("text")
    if text is None:
        text = ""
    # In a table, Obsidian writes the | before a link's text as \|.
    target = link.group("target").removesuffix(_TABLE_PIPE_ESCAPE).strip()
    heading = heading.removesuffix(_TABLE_PIPE_ESCAPE).strip()
    block_id = block_id.removesuffix(_TABLE_PIPE_ESCAPE).strip()
    return _token(references, LinkReference(
        target=target, heading=heading, block_id=block_id, text=text.strip(),
        is_embed=link.group("embed") != "", is_markdown_link=False, written=link.group(0),
    ))


def _markdown_token(link: re.Match[str], references: List[LinkReference]) -> str:
    href = link.group("href")
    if href.startswith(_ANGLE_OPEN) and href.endswith(_ANGLE_CLOSE):
        href = href[len(_ANGLE_OPEN):-len(_ANGLE_CLOSE)]
    # A web address, an e-mail, a link within the page: not a file of the vault.
    if _SCHEME_RE.match(href) is not None or href.startswith(_SUBPATH_MARK):
        return link.group(0)
    path, _mark, subpath = unquote(href).partition(_SUBPATH_MARK)
    heading, block_id = _subpath_parts(subpath)
    return _token(references, LinkReference(
        target=path.strip(), heading=heading, block_id=block_id, text=link.group("text").strip(),
        is_embed=link.group("embed") != "", is_markdown_link=True, written=link.group(0),
    ))


def _subpath_parts(subpath: str | None) -> Tuple[str, str]:
    """A subpath's heading (`#Budget`, the last of `#H1#H2`) or block (`#^abc`)."""
    if subpath is None or subpath.strip() == "":
        return "", ""
    if subpath.startswith(_BLOCK_SUBPATH_MARK):
        return "", subpath[len(_BLOCK_SUBPATH_MARK):].strip()
    return subpath.split(_SUBPATH_MARK)[-1].strip(), ""


def _token(references: List[LinkReference], reference: LinkReference) -> str:
    references.append(reference)
    return LINK_TOKEN_FORMAT.format(index=len(references) - 1)


def with_tokens_replaced(html: str, replacements: Dict[int, str]) -> str:
    """html with each link token replaced by its replacement, already HTML."""
    return LINK_TOKEN_RE.sub(lambda token: replacements[int(token.group("index"))], html)
