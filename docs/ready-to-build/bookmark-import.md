# Importing browser bookmarks

**Status:** Agreed with the maintainer 2026-11-02. Ready to build. A new import source beside Obsidian vault, Markdown folder and Any folder. Builds on folder tags ending in `/` (`virtual-folders`), the import's prefix folder (`import-prefix-folder`) and importing the same source again (`importing-again`, handed over the same day).

Written from a read-only look at the repo; filed from `docs/inbox/` on 2026-11-02, with the references checked (§9).

---

## 0. Today (from the code)

- Nothing reads bookmarks. The import sources are `obsidian`, `markdown` and `files` (`app/services/obsidian_import/sources.py`, `IMPORT_SOURCES`; `app/static/js/modules/wizard/import-wizard-steps.js`, `SOURCES`).
- The walkthrough's steps: Source (nothing chosen at first), Folder (the folder, and "Folder as it will appear in MetaList" on the same screen), Files, Markdown, Images, Previews (each only when it applies), Summary, Import (`importSteps`).
- Imported notes keep their original dates (`app/services/obsidian_import/notes.py`, `created_at`).
- A dropped `.html` file gets a web-page preview note (`app/services/file_text_preview.py`, `_HTML_EXTENSIONS`). A dropped bookmarks export would become one long page of links.

## 1. The file

Every major browser exports bookmarks to the same HTML layout, so one reader covers them all:

- **Chrome, Edge, Brave:** Bookmark manager → ⋮ → Export bookmarks.
- **Safari:** File → Export → Bookmarks.
- **Firefox:** Bookmarks → Manage bookmarks → Import and Backup → Export Bookmarks to HTML.

It's nested folders (`<DL>`, `<DT><H3>name</H3>`) of links (`<DT><A HREF="…" ADD_DATE="…">title</A>`). `ADD_DATE` is in seconds since 1970. Firefox may also write its bookmark tags in a `TAGS` attribute. *Check* a current export from each browser.

**It is recognized by its first line, `<!DOCTYPE NETSCAPE-Bookmark-file-1>`, never by its name.** The file is plain `.html` (`bookmarks_11_2_26.html`, `Bookmarks.html`), so a renamed file still works and an ordinary web page is never mistaken for one. Firefox's `.json` backup is a different format and isn't covered.

## 2. What each bookmark becomes

- **One root note per bookmark:** the page title as its first line, then the address as a link. If the title is empty, the address alone.
- **Created when it was bookmarked:** the note's created date is `ADD_DATE`, as the other imports keep a file's dates. If it's missing, the import time.
- **Folders become folder tags** under the prefix folder: `Bookmarks/Recipes/Soups/`.
- **The browser's own top folders are left out:** Chrome's "Bookmarks bar", "Other bookmarks" and "Mobile bookmarks"; Safari's "Favorites" and "Bookmarks Menu"; Firefox's "Bookmarks Toolbar", "Bookmarks Menu" and "Other Bookmarks". They say where the browser showed a bookmark, not what it's about. A folder on Chrome's bar comes in as `Bookmarks/Recipes/`, and a bookmark loose in a top folder goes straight into the prefix folder. *Check* how each browser marks these in the file (Chrome's bar carries `PERSONAL_TOOLBAR_FOLDER="true"`); recognize them by that, or by their position as the top level, rather than by their name, which is translated.
- **Firefox's tags become ordinary tags.**
- **Source tag:** `imported:source=bookmarks:at=…`.
- **Nothing is fetched from the bookmarked sites:** no titles, descriptions or page text. It would be slow, many pages are dead or need a login, and it would contact every site the user saved. Favicons in the file are left out.

## 3. Duplicates

- **One address is one note.** The same address in two folders is one note carrying both folder tags.
- **Importing again follows `importing-again`:** a bookmark is matched on its address, exactly as written, against earlier bookmark imports. Unchanged: skipped. Title or folders changed: comes in as a copy, and the old version's import tag gains `replaced=<time>`. Gone from the browser: stays, and gains `removed=<time>`. Nothing is overwritten or deleted.

## 4. Through the import walkthrough

A new source card, **Browser bookmarks**. Its steps:

1. **Source:** Browser bookmarks.
2. **File:** the Folder screen's shape for one file. A card showing the file's name and "1,240 bookmarks in 38 folders", **Choose File…** to pick one or another, and under it **Folder as it will appear in MetaList**, defaulting to `Bookmarks/`, with the same notice when that folder exists (keep and merge, or rename). The file is uploaded from the browser, so this works on hosted and self-hosted servers as well as on the user's own machine. A file that isn't a bookmarks export is refused on this screen with a sentence saying so.
3. Files, Markdown, Images and Previews don't apply and are skipped.
4. **Summary:** how many bookmarks are new, changed (come in as copies), unchanged (skipped) and gone from the browser, and the prefix folder.
5. **Import**, and the report as the other imports give it, with any bookmark left out and why (no address, say).

## 5. Dropping a bookmarks file

**A dropped bookmarks file opens the import walkthrough** instead of being attached:

- **Browser bookmarks is already chosen** on Source, and the File step's card is already filled in with the dropped file. The user presses Next, Next, Import.
- Opened from the menu, Source still starts with nothing chosen. A drop chooses it only because MetaList already knows what the file is.
- Cancelling the walkthrough adds nothing; the file isn't attached.
- Recognition reads the start of the file, before any upload or preview. Every other `.html` file is dropped as today.

*Check* where a dropped file is handled today, and whether a drop onto a note (as an attachment) should behave the same; the maintainer has only discussed a drop onto MetaList.

## 6. Invariants

1. A bookmarks file is recognized by its contents, never by its name alone.
2. Nothing is imported before the user has seen the Summary.
3. Nothing is fetched from the bookmarked sites.
4. One address is one note however many folders hold it; importing again never copies an unchanged bookmark.
5. The browser's own top folders never become folder tags.

## 7. Done when

1. Browser bookmarks is a source in the walkthrough and in `IMPORT_SOURCES`, with the steps in §4.
2. Exports from Chrome, Safari and Firefox import with their folders, dates and (Firefox) tags, without the top folders; tests use a small sample of each.
3. Importing the same file twice adds no notes; a changed file behaves as `importing-again` describes.
4. Dropping a bookmarks file opens the walkthrough as in §5; dropping any other `.html` file is unchanged.
5. `docs/ready-to-build/import-export-launch.md` lists the source.

## 8. Still open

- Whether the note shows the date added as a line. Suggested: no, since the note's created date already is that date.

## 9. Checked against the code (2026-11-02, when filed)

The references in §0 hold: `IMPORT_SOURCES` (`obsidian`, `markdown`, `files`) in `app/services/obsidian_import/sources.py`; the walkthrough's `SOURCES` and `importSteps` (Source, Folder, Files, Markdown, Images, Previews, Summary) in `import-wizard-steps.js`; `created_at` in `notes.py`; `_HTML_EXTENSIONS` in `file_text_preview.py`.

Found:

- **No import takes an uploaded file today.** Every source is a folder path picked in the server's own dialog (`POST /import/pick-folder`, then `ImportFolderRequest.folderPath` in `app/api/routes/imports.py`). §4's upload from the browser is new: a route that takes the file, and `ImportSourceKey` (the same file) gains `bookmarks`. The hosted folder upload (`folder-import-and-file-previews.md` §4) isn't built either, so this would be the first upload into an import.
- **There is no import report any more** (dropped 2026-11-01, `import-export-launch.md` §5): the walkthrough closes on a search context of the import's tag. §4's "the report as the other imports give it" can only mean the Summary, so bookmarks left out (no address) would be listed there, before the import. *Ask.*
- **Drops** are handled in `keyboard-events.js` (`handleDropEvent`, `processDroppedFiles`, with `shouldCreateTopNoteForFileDrop` in `file-drop-policy-service.js`). A drop onto a note and one onto the list both go through it; §5's open point (whether a drop onto a note opens the walkthrough too) stays open.
- **Folder and tag names** would go through the same cleanup as a vault's (`_tag_text`, `_checked_tag` in `notes.py`: spaces become dashes, renames reported), and under the prefix folder (`import_folder_prefix`, `folder_tag_for`).
- **The exports themselves can't be checked from the repo:** there is no sample from any browser. Tests need a small real export from Chrome, Safari and Firefox (§7.2), including how each marks its top folders (§2).
- **Builds on `importing-again`** for §3's second import, which isn't built.
- Aside: `app/static/js/modules/import-sources.js` holds a second, older `IMPORT_SOURCES` (Obsidian and Markdown only) that nothing imports; the walkthrough's `SOURCES` is the live list.
