"""Four built-in `@` tags renamed before launch (agreed 2026-10-28): `@highlighter`,
`@llm`, `@list-bulleted` and `@list-numbered` became `@highlight`, `@ai`, `@bullets` and
`@numbered` (docs/ui/content-formatting.md). Each database is converted once when its
notes are read after unlock (content_cache.populate_cache_from_db): every note's tags and
proposed tags, and the searches of its search contexts. The pass is recorded in
namespace_content_migrations, so a restored older backup is converted again. Nothing else
keeps the old names: after the pass they are unknown `@` tags like any other."""

from __future__ import annotations

import re
from typing import Mapping

from app.services.tag_rename import rename_tag_in_tag_bar

META_TAG_RENAMES: Mapping[str, str] = {
    "@highlighter": "@highlight",
    "@llm": "@ai",
    "@list-bulleted": "@bullets",
    "@list-numbered": "@numbered",
}
META_TAG_RENAMES_PREFIX = "meta-tag-renames:"
META_TAG_RENAMES_MIGRATION_ID = META_TAG_RENAMES_PREFIX + "2026-10-28"

# A search's pieces: quoted text (kept as typed, even unclosed), a term, or space.
_SEARCH_PIECE_RE = re.compile(r"\"(?:[^\"\\]|\\.)*\"?|'(?:[^'\\]|\\.)*'?|[^\s\"']+|\s+")
_SEARCH_TERM_PREFIXES = ("+", "-")


def rename_meta_tags_in_tag_bar(tags: str) -> str:
    """A tag bar with the old names renamed, on their own or inside a scope
    (`((@list-numbered))`), as Edit Tag Relationships renames a tag; a meta tag is the
    same in any case (`@LLM`), so each spelling written is renamed."""
    if not isinstance(tags, str):
        raise TypeError(f"tags must be a string, got {type(tags)}")
    renamed = tags
    for old, new in META_TAG_RENAMES.items():
        for spelling in sorted(set(re.findall(re.escape(old), tags, flags=re.IGNORECASE))):
            renamed, _changed = rename_tag_in_tag_bar(tags=renamed, old=spelling, new=new)
    return renamed


def rename_meta_tags_in_search(query: str) -> str:
    """A search with each old name renamed where it is a term (`@llm`, `-@llm`), in any
    case, as search reads tags; quoted text is left as typed."""
    if not isinstance(query, str):
        raise TypeError(f"query must be a string, got {type(query)}")
    pieces = [match.group(0) for match in _SEARCH_PIECE_RE.finditer(query)]
    assert "".join(pieces) == query, "the pieces cover the whole search"
    return "".join(_renamed_search_piece(piece) for piece in pieces)


def _renamed_search_piece(piece: str) -> str:
    prefix = ""
    term = piece
    if term[:1] in _SEARCH_TERM_PREFIXES:
        prefix = term[:1]
        term = term[1:]
    folded = term.casefold()
    if folded not in META_TAG_RENAMES:
        return piece
    return prefix + META_TAG_RENAMES[folded]
