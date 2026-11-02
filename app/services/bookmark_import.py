"""A browser's bookmarks export read (docs/ready-to-build/bookmark-import.md): every major
browser writes the same HTML layout, folders (`<DT><H3>name</H3><DL>…</DL>`) of links
(`<DT><A HREF="…" ADD_DATE="…">title</A>`). Recognized by its first line, never by its name.
Only website addresses come in; the rest is left out and said on the Summary. Nothing is
fetched from the bookmarked sites."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Dict, List, Tuple

from app.services.input_errors import InputRejected

# The first line every browser writes (Chrome, Edge, Safari, Firefox).
BOOKMARKS_DOCTYPE = "<!DOCTYPE NETSCAPE-Bookmark-file-1>"
# What may come before it: a byte order mark and blank space.
_LEADING_CHARACTERS = "﻿ \t\r\n"
# The browser's own folders that say where it showed a bookmark, not what it is about: they
# are no folder level (§2). Marked in the file, so recognized whatever their translated
# name. Chrome's and Firefox's bar carry the first (checked in a Firefox export, 2026-11-02);
# Firefox's Other Bookmarks the second (not seen yet: it was empty).
_BROWSER_FOLDER_MARKS = ("personal_toolbar_folder", "unfiled_bookmarks_folder")
# Firefox's own tags on a bookmark, comma separated (not seen yet: none in the export).
_TAGS_ATTRIBUTE = "tags"
_TAGS_SEPARATOR = ","
_FOLDER_ELEMENT = "h3"
_LINK_ELEMENT = "a"
_LIST_ELEMENT = "dl"
_ADDRESS_ATTRIBUTE = "href"
_ADDED_ATTRIBUTE = "add_date"
_MODIFIED_ATTRIBUTE = "last_modified"
# Only these come in (the maintainer, 2026-11-02: "we only want URLs to websites").
_WEBSITE_SCHEMES = ("http", "https")
_SCHEME_SEPARATOR = ":"

# Why a bookmark is left out, as the Summary words it.
NO_ADDRESS = "no address"
SMART_FOLDER = "Firefox smart folder"
BOOKMARKLET = "bookmarklet"
COMPUTER_FILE = "file on this computer"
BROWSER_PAGE = "browser page"
_KIND_BY_SCHEME = (("place", SMART_FOLDER), ("javascript", BOOKMARKLET), ("file", COMPUTER_FILE))


@dataclass(frozen=True)
class Bookmark:
    """One website address, however many folders hold it (§3): its first title, every folder
    holding it (each as its names from the top, the browser's own folders left out), its tags,
    and when it was first bookmarked and last changed (None when the file doesn't say)."""

    address: str
    title: str
    folders: Tuple[Tuple[str, ...], ...]
    tags: Tuple[str, ...]
    added_at: datetime | None
    modified_at: datetime | None


@dataclass(frozen=True)
class LeftOut:
    """A bookmark that isn't a website address: its title and why."""

    title: str
    kind: str


@dataclass(frozen=True)
class BookmarksFile:
    bookmarks: Tuple[Bookmark, ...]
    left_out: Tuple[LeftOut, ...]


def is_bookmarks_export(text: str) -> bool:
    """Whether text is a browser's bookmarks export, by its first line."""
    return text.lstrip(_LEADING_CHARACTERS)[:len(BOOKMARKS_DOCTYPE)].casefold() == BOOKMARKS_DOCTYPE.casefold()


def read_bookmarks(text: str) -> BookmarksFile:
    """The website bookmarks in a bookmarks export, in the file's order, and the ones left out."""
    if not is_bookmarks_export(text):
        raise InputRejected("That file isn't a bookmarks export. Export your bookmarks from the browser and choose that file.")
    reader = _Reader()
    reader.feed(text)
    reader.close()
    return BookmarksFile(bookmarks=tuple(reader.merged()), left_out=tuple(reader.left_out))


def _moment(seconds: str) -> datetime | None:
    """A date the file gives in seconds since 1970; None when it gives none or it isn't one."""
    if not seconds.strip().isdigit():
        return None
    return datetime.fromtimestamp(int(seconds.strip()), tz=timezone.utc)


def _attribute_text(attributes: Dict[str, str | None], name: str) -> str:
    """An attribute's text as the file gives it; '' when the browser wrote none (every
    attribute of an export is optional: a link may lack its address, dates or tags)."""
    if name not in attributes:
        return ""
    value = attributes[name]
    if value is None:
        return ""
    return value


def _left_out_kind(address: str) -> str:
    """Why an address isn't brought in, or '' for a website address."""
    if address.strip() == "":
        return NO_ADDRESS
    scheme = address.split(_SCHEME_SEPARATOR, 1)[0].strip().casefold()
    if _SCHEME_SEPARATOR in address and scheme in _WEBSITE_SCHEMES:
        return ""
    for named_scheme, kind in _KIND_BY_SCHEME:
        if scheme == named_scheme:
            return kind
    # Every other scheme is the browser's own (chrome:, about:, edge:) or no website.
    return BROWSER_PAGE


@dataclass
class _Seen:
    """A website address as read so far."""

    title: str
    folders: List[Tuple[str, ...]]
    tags: List[str]
    added_at: datetime | None
    modified_at: datetime | None


class _Reader(HTMLParser):
    """Walks the export: each `<DL>` opens the folder its `<H3>` named (the outermost, and a
    browser folder, open none), each `<A>` is a bookmark in the folders open."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # The folder names open, and for each `<DL>` whether it opened one.
        self._folders: List[str] = []
        self._opened: List[bool] = []
        # The `<H3>` just read: its name, and whether it is a browser folder; None outside one.
        self._heading: List[str] | None = None
        self._heading_is_browser_folder = False
        self._next_folder: str | None = None
        self._link: Dict[str, str | None] | None = None
        self._link_text: List[str] = []
        self._seen: Dict[str, _Seen] = {}
        self.left_out: List[LeftOut] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == _FOLDER_ELEMENT:
            self._heading = []
            self._heading_is_browser_folder = any(mark in attributes for mark in _BROWSER_FOLDER_MARKS)
        elif tag == _LIST_ELEMENT:
            opens = self._next_folder is not None
            if opens:
                self._folders.append(self._next_folder)
            self._opened.append(opens)
            self._next_folder = None
        elif tag == _LINK_ELEMENT:
            self._link = attributes
            self._link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == _FOLDER_ELEMENT and self._heading is not None:
            # A browser folder's list opens no folder: its bookmarks are where it is.
            if not self._heading_is_browser_folder:
                self._next_folder = "".join(self._heading).strip()
            self._heading = None
        elif tag == _LIST_ELEMENT and self._opened:
            if self._opened.pop():
                self._folders.pop()
        elif tag == _LINK_ELEMENT and self._link is not None:
            self._add_link(self._link, "".join(self._link_text).strip())
            self._link = None

    def handle_data(self, data: str) -> None:
        if self._heading is not None:
            self._heading.append(data)
        elif self._link is not None:
            self._link_text.append(data)

    def _add_link(self, attributes: Dict[str, str | None], title: str) -> None:
        address = _attribute_text(attributes, _ADDRESS_ATTRIBUTE).strip()
        kind = _left_out_kind(address)
        if kind != "":
            self.left_out.append(LeftOut(title=title, kind=kind))
            return
        folder = tuple(self._folders)
        tags = [tag.strip() for tag in _attribute_text(attributes, _TAGS_ATTRIBUTE).split(_TAGS_SEPARATOR) if tag.strip() != ""]
        added_at = _moment(_attribute_text(attributes, _ADDED_ATTRIBUTE))
        modified_at = _moment(_attribute_text(attributes, _MODIFIED_ATTRIBUTE))
        if address not in self._seen:
            self._seen[address] = _Seen(title=title, folders=[folder], tags=tags, added_at=added_at, modified_at=modified_at)
            return
        seen = self._seen[address]
        if folder not in seen.folders:
            seen.folders.append(folder)
        seen.tags.extend(tag for tag in tags if tag not in seen.tags)
        seen.added_at = _earliest(seen.added_at, added_at)
        seen.modified_at = _latest(seen.modified_at, modified_at)

    def merged(self) -> List[Bookmark]:
        return [
            Bookmark(
                address=address, title=seen.title, folders=tuple(seen.folders), tags=tuple(seen.tags),
                added_at=seen.added_at, modified_at=seen.modified_at,
            )
            for address, seen in self._seen.items()
        ]


def _earliest(first: datetime | None, second: datetime | None) -> datetime | None:
    if first is None:
        return second
    if second is None:
        return first
    return min(first, second)


def _latest(first: datetime | None, second: datetime | None) -> datetime | None:
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)
