from __future__ import annotations

import re

from app.services.content_formatting import COMMENT_CLOSE, COMMENT_OPEN, find_plain_text_urls
from app.services.quoted_values import VALUE_QUOTE, opens_value, quoted_value_end
from app.services.email_search_text import EMAIL_THUMBNAIL_KINDS, email_search_words
from app.services.file_registry import file_registry
from app.services.link_titles import link_title_store, normalize_url_for_link_title
from app.services.tag_characters import normalize_text
from app.utils.text_utils import strip_html_keeping_link_urls


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def extract_tag_bar_comment_text(tags: str) -> str:
    if not isinstance(tags, str):
        raise TypeError(f"tags must be a string, got {type(tags)}")

    comments: list[str] = []
    index = 0
    while index < len(tags):
        start = _find_comment_open(tags, index)
        if start == -1:
            break

        end = tags.find(COMMENT_CLOSE, start + len(COMMENT_OPEN))
        if end == -1:
            break

        inner = tags[start + len(COMMENT_OPEN) : end]
        normalized = _normalize_whitespace(inner)
        if normalized:
            comments.append(normalized)

        index = end + len(COMMENT_CLOSE)

    return " ".join(comments)


def _find_comment_open(tags: str, start: int) -> int:
    """The next comment opener at or after start outside a quoted value (title="a /* b" holds
    none), or -1."""
    if VALUE_QUOTE not in tags:
        return tags.find(COMMENT_OPEN, start)
    index = start
    while index < len(tags):
        if opens_value(tags, index):
            index = quoted_value_end(tags, index).end
            continue
        if tags.startswith(COMMENT_OPEN, index):
            return index
        index += 1
    return -1


def list_link_title_urls(content_text: str) -> frozenset[str]:
    """The normalized URLs written out in a note's text; their cached titles are searchable."""
    if "://" not in content_text:
        # Most notes have no URL; skip the scan during hydration.
        return frozenset()
    urls: set[str] = set()
    for url in find_plain_text_urls(content_text):
        normalized_url = normalize_url_for_link_title(url)
        if normalized_url is not None:
            urls.add(normalized_url)
    return frozenset(urls)


def append_link_titles_casefold(text_casefold: str, link_title_urls: frozenset[str]) -> str:
    """Searchable text plus the cached titles of the note's URLs (docs/ui/search-semantics.md).

    Only titles already fetched count; a title fetched later is added when the
    search index refreshes the notes containing that URL.
    """
    if not isinstance(text_casefold, str) or not isinstance(link_title_urls, frozenset):
        raise TypeError("append_link_titles_casefold requires text and a frozenset of URLs")
    titles: list[str] = []
    for url in sorted(link_title_urls):
        title = link_title_store.get_ok_title(url)
        if title is not None:
            titles.append(title.casefold())
    if not titles:
        return text_casefold
    return " ".join([text_casefold, *titles])


def link_titles_in_html(content_html: str) -> tuple[str, ...]:
    """The fetched titles of the web addresses in a note's HTML, those quoted search reads
    (docs/ui/search-semantics.md): tag suggestions read the same (docs/ui/tag-bar.md)."""
    if not isinstance(content_html, str):
        raise TypeError("content_html must be a string")
    titles: list[str] = []
    for url in sorted(list_link_title_urls(strip_html_keeping_link_urls(content_html))):
        title = link_title_store.get_ok_title(url)
        if title is not None:
            titles.append(title)
    return tuple(titles)


def build_searchable_text_casefold_from_plaintext(content_text: str, tags: str) -> str:
    """Visible text, tag-bar comments and the cached titles of URLs in the text, casefolded."""
    return append_link_titles_casefold(
        build_searchable_base_text_casefold(content_text, tags),
        list_link_title_urls(content_text),
    )


def build_searchable_base_text_casefold(content_text: str, tags: str) -> str:
    """Visible text, the names of files it references ([[id]], shown by name), the words
    of emails it references, and tag-bar comments, casefolded (without URL titles)."""
    if not isinstance(content_text, str):
        raise TypeError(f"content_text must be a string, got {type(content_text)}")
    if not isinstance(tags, str):
        raise TypeError(f"tags must be a string, got {type(tags)}")

    comment_text = extract_tag_bar_comment_text(tags)

    combined = content_text
    referenced_files = file_registry.referenced_file_names(content_text)
    file_names = [name for _file_id, name in referenced_files]
    if file_names:
        combined = " ".join([combined, *file_names])
    email_words = [
        email_search_words(file_id) for file_id, _name in referenced_files
        if file_registry.thumbnail_kind_of(file_id) in EMAIL_THUMBNAIL_KINDS
    ]
    email_words = [words for words in email_words if words != ""]
    if email_words:
        combined = " ".join([combined, *email_words])
    if comment_text:
        if combined:
            combined = f"{combined} {comment_text}"
        else:
            combined = comment_text

    # One Unicode form, as searches are (app/services/tag_characters.py).
    return normalize_text(combined).casefold()


def build_searchable_text_casefold(content_html: str, tags: str) -> str:
    if not isinstance(content_html, str):
        raise TypeError(f"content_html must be a string, got {type(content_html)}")
    if not isinstance(tags, str):
        raise TypeError(f"tags must be a string, got {type(tags)}")

    return build_searchable_text_casefold_from_plaintext(strip_html_keeping_link_urls(content_html), tags)


