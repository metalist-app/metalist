"""Importing a browser's bookmarks export (docs/ready-to-build/bookmark-import.md). The sample
is made up in the structure of a real Firefox export (checked 2026-11-02): the outermost list
is the Bookmarks Menu itself, the toolbar a folder marked PERSONAL_TOOLBAR_FOLDER."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.bookmark_import import (
    BOOKMARKLET,
    BROWSER_PAGE,
    COMPUTER_FILE,
    NO_ADDRESS,
    SMART_FOLDER,
    is_bookmarks_export,
    read_bookmarks,
)
from app.services.input_errors import InputRejected
from app.services.note_store import store
from app.services.store import store as tree
from app.usecases.import_bookmarks import CmdImportBookmarks, CmdPreviewBookmarkImport
from tests.unit.test_super_tag_last_values import live_database  # noqa: F401 (the fixture)

# 2019-03-03 12:00 UTC and 2020-01-02 00:00 UTC, in seconds as browsers write them.
_MARCH_2019 = 1551614400
_JANUARY_2020 = 1577923200
_IMPORTED_AT = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)

_FIREFOX_LIKE = f"""<!DOCTYPE NETSCAPE-Bookmark-file-1>
<!-- This is an automatically generated file. -->
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks Menu</H1>

<DL><p>
    <DT><H3 ADD_DATE="{_MARCH_2019}" LAST_MODIFIED="{_MARCH_2019}">Recipes</H3>
    <DL><p>
        <DT><H3 ADD_DATE="{_MARCH_2019}" LAST_MODIFIED="{_MARCH_2019}">Soups &amp; Stews</H3>
        <DL><p>
            <DT><A HREF="https://example.com/leek-soup" ADD_DATE="{_MARCH_2019}" LAST_MODIFIED="{_JANUARY_2020}" ICON_URI="https://example.com/favicon.ico" ICON="data:image/png;base64,AAAA">Leek soup &amp; bread</A>
        </DL><p>
        <DT><A HREF="https://example.org/lasagna" ADD_DATE="{_JANUARY_2020}" LAST_MODIFIED="{_JANUARY_2020}" TAGS="dinner,family favourites">Mom's lasagna</A>
    </DL><p>
    <DT><A HREF="https://example.net/menu-top" ADD_DATE="{_JANUARY_2020}" LAST_MODIFIED="{_JANUARY_2020}">Loose in the menu</A>
    <DT><A HREF="file:///Users/someone/Documents/plan.pdf" ADD_DATE="{_JANUARY_2020}">A file</A>
    <DT><A HREF="about:config" ADD_DATE="{_JANUARY_2020}">Config</A>
    <DT><A HREF="javascript:alert(1)" ADD_DATE="{_JANUARY_2020}">A bookmarklet</A>
    <DT><A HREF="place:sort=8&amp;maxResults=10" ADD_DATE="{_JANUARY_2020}">Most Visited</A>
    <DT><A HREF="" ADD_DATE="{_JANUARY_2020}">Nowhere</A>
    <DT><H3 ADD_DATE="{_MARCH_2019}" LAST_MODIFIED="{_MARCH_2019}" PERSONAL_TOOLBAR_FOLDER="true">Bookmarks Toolbar</H3>
    <DL><p>
        <DT><A HREF="https://example.com/leek-soup" ADD_DATE="{_JANUARY_2020}" LAST_MODIFIED="{_JANUARY_2020}">Leek soup again</A>
        <DT><A HREF="https://example.com/on-the-bar" ADD_DATE="{_JANUARY_2020}" LAST_MODIFIED="{_JANUARY_2020}">On the bar</A>
        <DT><H3 ADD_DATE="{_MARCH_2019}" LAST_MODIFIED="{_MARCH_2019}">Work</H3>
        <DL><p>
            <DT><A HREF="https://example.com/standup" ADD_DATE="{_JANUARY_2020}" LAST_MODIFIED="{_JANUARY_2020}">Standup notes</A>
            <DT><A HREF="https://example.com/standup" ADD_DATE="{_JANUARY_2020}" LAST_MODIFIED="{_JANUARY_2020}">Standup notes</A>
        </DL><p>
    </DL><p>
    <DT><A HREF="https://example.com/untitled" ADD_DATE="{_JANUARY_2020}"></A>
</DL><p>
"""


def _by_address():
    return {bookmark.address: bookmark for bookmark in read_bookmarks(_FIREFOX_LIKE).bookmarks}


def test_an_export_is_recognized_by_its_first_line_not_its_name() -> None:
    assert is_bookmarks_export(_FIREFOX_LIKE)
    assert is_bookmarks_export("﻿\n  <!doctype netscape-bookmark-file-1>\n<DL></DL>")
    assert not is_bookmarks_export("<!DOCTYPE html><html><body><a href='https://example.com'>x</a></body></html>")


def test_a_web_page_is_refused_with_a_sentence() -> None:
    with pytest.raises(InputRejected, match="isn't a bookmarks export"):
        read_bookmarks("<!DOCTYPE html><html></html>")


def test_only_website_addresses_come_in_in_the_files_order() -> None:
    assert list(_by_address()) == [
        "https://example.com/leek-soup", "https://example.org/lasagna", "https://example.net/menu-top",
        "https://example.com/on-the-bar", "https://example.com/standup", "https://example.com/untitled",
    ]


def test_the_rest_is_left_out_with_why() -> None:
    left_out = [(item.title, item.kind) for item in read_bookmarks(_FIREFOX_LIKE).left_out]

    assert left_out == [
        ("A file", COMPUTER_FILE), ("Config", BROWSER_PAGE), ("A bookmarklet", BOOKMARKLET),
        ("Most Visited", SMART_FOLDER), ("Nowhere", NO_ADDRESS),
    ]


def test_the_toolbar_is_no_folder_level_and_the_menus_own_folders_are_kept() -> None:
    bookmarks = _by_address()

    assert bookmarks["https://example.com/on-the-bar"].folders == ((),)
    assert bookmarks["https://example.com/standup"].folders == (("Work",),)
    assert bookmarks["https://example.org/lasagna"].folders == (("Recipes",),)
    assert bookmarks["https://example.net/menu-top"].folders == ((),)


def test_one_address_is_one_bookmark_with_every_folder_holding_it() -> None:
    soup = _by_address()["https://example.com/leek-soup"]

    assert soup.folders == (("Recipes", "Soups & Stews"), ())
    assert soup.title == "Leek soup & bread"
    assert soup.added_at == datetime.fromtimestamp(_MARCH_2019, tz=timezone.utc)
    # Twice in one folder: that folder once.
    assert _by_address()["https://example.com/standup"].folders == (("Work",),)


def test_firefox_tags_are_read() -> None:
    assert _by_address()["https://example.org/lasagna"].tags == ("dinner", "family favourites")


def test_the_summary_counts_what_comes_in_and_what_is_left_out(live_database) -> None:  # noqa: F811
    preview = CmdPreviewBookmarkImport(file_text=_FIREFOX_LIKE, folder_prefix="Bookmarks", imported_at=_IMPORTED_AT).execute()

    assert preview["prefixFolder"] == "Bookmarks/"
    assert preview["bookmarkCount"] == 6
    assert preview["folderCount"] == 3
    assert preview["leftOut"] == [
        ["A file", COMPUTER_FILE], ["Config", BROWSER_PAGE], ["A bookmarklet", BOOKMARKLET],
        ["Most Visited", SMART_FOLDER], ["Nowhere", NO_ADDRESS],
    ]


def test_each_bookmark_is_one_note_at_the_top_its_title_linked(live_database) -> None:  # noqa: F811
    result = CmdImportBookmarks(
        file_text=_FIREFOX_LIKE, folder_prefix="Bookmarks", add_to_existing=True, token="", imported_at=_IMPORTED_AT,
    ).execute()

    assert result["noteCount"] == 6
    assert result["sourceTag"] == "imported:source=bookmarks:at=" + _IMPORTED_AT.astimezone().strftime("%Y-%m-%dT%H:%M")
    roots = [store.get_note(note_id) for note_id in tree.children(None)]
    assert len(roots) == 6
    soup, lasagna, menu_top, on_the_bar, standup, untitled = roots
    assert soup.content == '<a href="https://example.com/leek-soup">Leek soup &amp; bread</a>'
    assert soup.tags.split() == ["Bookmarks/Recipes/Soups-&-Stews/", "Bookmarks/", result["sourceTag"]]
    assert lasagna.tags.split() == ["Bookmarks/Recipes/", "dinner", "family-favourites", result["sourceTag"]]
    assert menu_top.tags.split() == ["Bookmarks/", result["sourceTag"]]
    assert on_the_bar.tags.split() == ["Bookmarks/", result["sourceTag"]]
    assert standup.tags.split() == ["Bookmarks/Work/", result["sourceTag"]]
    assert untitled.content == "https://example.com/untitled"
    assert soup.created_at == datetime.fromtimestamp(_MARCH_2019, tz=timezone.utc)
    assert soup.updated_at == datetime.fromtimestamp(_JANUARY_2020, tz=timezone.utc)


def test_an_existing_folder_is_added_to_only_when_ticked(live_database) -> None:  # noqa: F811
    CmdImportBookmarks(
        file_text=_FIREFOX_LIKE, folder_prefix="Bookmarks", add_to_existing=True, token="", imported_at=_IMPORTED_AT,
    ).execute()

    with pytest.raises(InputRejected, match="already exists"):
        CmdImportBookmarks(
            file_text=_FIREFOX_LIKE, folder_prefix="Bookmarks", add_to_existing=False, token="", imported_at=_IMPORTED_AT,
        ).execute()


def test_importing_again_only_adds(live_database) -> None:  # noqa: F811
    for _ in range(2):
        CmdImportBookmarks(
            file_text=_FIREFOX_LIKE, folder_prefix="Bookmarks", add_to_existing=True, token="", imported_at=_IMPORTED_AT,
        ).execute()

    assert len(tree.children(None)) == 12
