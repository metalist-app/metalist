"""Links that open a search: `[[search:work -archive]]`, `[[search:work -archive|Current work]]`
(docs/ready-to-build/search-links.md). A click opens a search context with the search, or the one
that already has it. A search link is never a reference to a note: every reference scanner takes only
a note ID, and search: is never one.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Callable, FrozenSet, List, Optional, Tuple

from app.services.input_errors import InputRejected
from app.services.search_query import SearchClause, parse_search_query

SEARCH_LINK_PREFIX = "search:"
_LINK_TEXT_SEPARATOR = "|"
# A search link or an embedded search in a note's stored HTML (the ! of an embed, then the text
# between [[ and ]]; brackets can't be in it).
_ANY_SEARCH_LINK_TOKEN_RE = re.compile(r"(!?)\[\[search:([^\[\]\n]*)\]\]")
_OR_KEYWORD = "OR"
# A search's pieces: quoted text (kept as typed, even unclosed), a term, or space
# (as meta_tag_renames.rename_meta_tags_in_search reads one).
_SEARCH_PIECE_RE = re.compile(r"\"(?:[^\"\\]|\\.)*\"?|'(?:[^'\\]|\\.)*'?|[^\s\"']+|\s+")
_SEARCH_TERM_PREFIXES = ("+", "-")
# A tag term's tag ends where its value (work=high) or a property (work:hours>2) starts.
_TAG_TERM_END_RE = re.compile(r"[=:]")


@dataclass(frozen=True, slots=True)
class SearchLink:
    """The search as typed in the search box, and the link's text ("" for none: it reads its search)."""

    search: str
    link_text: str

    @property
    def shown_text(self) -> str:
        if self.link_text != "":
            return self.link_text
        return self.search


def parse_search_link(inner: str) -> Optional[SearchLink]:
    """The search link written between [[ and ]], or None: not search:, or a blank search or
    a blank text after |, which stay text as typed (as a blank note link does)."""
    if not isinstance(inner, str):
        raise TypeError(f"inner must be a string, got {type(inner)}")
    if not inner.startswith(SEARCH_LINK_PREFIX):
        return None
    rest = inner[len(SEARCH_LINK_PREFIX):]
    search, separator, link_text = rest.partition(_LINK_TEXT_SEPARATOR)
    if search.strip() == "":
        return None
    if separator != "" and link_text.strip() == "":
        return None
    return SearchLink(search=search.strip(), link_text=link_text.strip())


def render_search_link(link: SearchLink, *, static_export: bool) -> str:
    """A magnifier and the link's text; its search is the tooltip when it has text of its own. An
    export keeps the markup as written (search-links.md §6)."""
    if static_export:
        written = SEARCH_LINK_PREFIX + link.search
        if link.link_text != "":
            written += _LINK_TEXT_SEPARATOR + link.link_text
        return f"[[{written}]]"
    search_attribute = html.escape(html.unescape(link.search), quote=True)
    tooltip = ""
    if link.link_text != "":
        tooltip = f' title="{search_attribute}"'
    return (
        f'<a class="note-search-link" data-search-query="{search_attribute}"{tooltip}>'
        '<span class="note-search-link-icon" aria-hidden="true"></span>'
        f'<span class="note-search-link-title">{html.escape(html.unescape(link.shown_text))}</span></a>'
    )


def rewrite_search_terms(search: str, rewrite: Callable[[str], str]) -> str:
    """A search with each term (`work`, `-work`, `+work`, `work=high`) rewritten by `rewrite`, given
    the term without its sign: "" drops the term, sign and all, and an `OR` part left with nothing
    goes with its `OR` (`Projects/ OR Archive/ @todo` without its folders is `@todo`). Quoted text,
    `OR` and spacing are otherwise left as typed."""
    if not isinstance(search, str):
        raise TypeError(f"search must be a string, got {type(search)}")
    pieces = [match.group(0) for match in _SEARCH_PIECE_RE.finditer(search)]
    assert "".join(pieces) == search, "the pieces cover the whole search"
    rewritten: List[str] = []
    for piece in pieces:
        if piece.isspace() or piece[:1] in "\"'" or piece == _OR_KEYWORD:
            rewritten.append(piece)
            continue
        sign = ""
        term = piece
        if term[:1] in _SEARCH_TERM_PREFIXES:
            sign = term[:1]
            term = term[1:]
        new_term = rewrite(term)
        if new_term != "":
            rewritten.append(sign + new_term)
    if len(rewritten) == len(pieces):
        return "".join(rewritten)
    return _without_empty_clauses(rewritten)


def _without_empty_clauses(pieces: List[str]) -> str:
    """The pieces joined, each `OR` part with nothing left in it dropped with its `OR`."""
    clauses: List[List[str]] = [[]]
    for piece in pieces:
        if piece == _OR_KEYWORD:
            clauses.append([])
            continue
        clauses[-1].append(piece)
    kept = ["".join(clause).strip() for clause in clauses if "".join(clause).strip() != ""]
    return f" {_OR_KEYWORD} ".join(kept)


def rewrite_searches_in_search_links(content_html: str, rewrite: Callable[[str], str]) -> str:
    """A note's stored HTML with the search of each search link (and embedded search) rewritten by
    `rewrite`; the links' text and the rest of the note are left as written."""
    if not isinstance(content_html, str):
        raise TypeError(f"content_html must be a string, got {type(content_html)}")

    def rewritten(match: re.Match[str]) -> str:
        search, separator, link_text = match.group(2).partition(_LINK_TEXT_SEPARATOR)
        written = html.escape(rewrite(html.unescape(search)), quote=False)
        return f"{match.group(1)}[[{SEARCH_LINK_PREFIX}{written}{separator}{link_text}]]"

    return _ANY_SEARCH_LINK_TOKEN_RE.sub(rewritten, content_html)


def _renamed_term(piece: str, *, old: str, new: str) -> str:
    prefix = ""
    term = piece
    if term[:1] in _SEARCH_TERM_PREFIXES:
        prefix = term[:1]
        term = term[1:]
    end = _TAG_TERM_END_RE.search(term)
    tag = term
    rest = ""
    if end is not None:
        tag = term[:end.start()]
        rest = term[end.start():]
    if tag.casefold() != old.casefold():
        return piece
    return prefix + new + rest


def rename_tag_in_search(search: str, *, old: str, new: str) -> str:
    """A search with the tag renamed where it is a term (work, -work, work=high, work:hours>2), in
    any case, as search reads tags; quoted text and every other term are left as typed."""
    if not isinstance(search, str):
        raise TypeError(f"search must be a string, got {type(search)}")
    if not isinstance(old, str) or old == "" or not isinstance(new, str) or new == "":
        raise TypeError("old and new must be non-empty strings")
    pieces = [match.group(0) for match in _SEARCH_PIECE_RE.finditer(search)]
    assert "".join(pieces) == search, "the pieces cover the whole search"
    return "".join(
        piece if piece.isspace() or piece[:1] in "\"'" else _renamed_term(piece, old=old, new=new)
        for piece in pieces
    )


def rename_tag_in_search_links(content_html: str, *, old: str, new: str) -> str:
    """A note's stored HTML with the tag renamed in the search of each of its search links and
    embedded searches; their text and the rest of the note are left as written."""
    return rewrite_searches_in_search_links(content_html, lambda search: rename_tag_in_search(search, old=old, new=new))


def has_search_links(content_html: str) -> bool:
    return _ANY_SEARCH_LINK_TOKEN_RE.search(content_html) is not None


def _clause_terms(clause: SearchClause) -> Tuple[FrozenSet[object], ...]:
    """A clause's terms in no order and any case, as search reads them; a quoted phrase keeps
    its words' order."""
    return (
        frozenset(tag.casefold() for tag in clause.required_tags),
        frozenset(tag.casefold() for tag in clause.forbidden_tags),
        frozenset(text.casefold() for text in clause.required_text),
        frozenset(text.casefold() for text in clause.forbidden_text),
        frozenset(clause.required_properties),
        frozenset(clause.forbidden_properties),
    )


def search_terms(search: str) -> Optional[FrozenSet[Tuple[FrozenSet[object], ...]]]:
    """A search's terms, the same for searches that find the same notes by them (spaces, order and
    capitals aside, search-links.md §3); None for one that doesn't parse."""
    try:
        parsed = parse_search_query(search)
    except InputRejected:
        return None
    return frozenset(_clause_terms(clause) for clause in parsed.clauses)


def same_search(first: str, second: str) -> bool:
    first_terms = search_terms(first)
    if first_terms is None:
        return False
    return first_terms == search_terms(second)
