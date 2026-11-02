# Importing browser bookmarks

**Status:** Agreed with the maintainer 2026-11-02. **Built 2026-11-02** (the maintainer tried it with their Firefox export: all checks pass; `docs/ui/command-palette.md`, Import…). Still to do: check a Chrome and a Safari export (and Firefox's Other Bookmarks and tags), then delete this note. A new import source beside Obsidian vault, Markdown folder and Any folder. Builds on folder tags ending in `/` (`virtual-folders`), and the import's prefix folder (`import-prefix-folder`). Importing the file again adds everything again (§3).

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

- **One root note per bookmark, one line:** the bookmark's title as a link to its address, shown as the site's icon, the title, then ` · domain` (`docs/ui/content-formatting.md`, Links In View Mode). A link with its own text keeps it and its page's title is never fetched, so the user's own name for a bookmark stays and a dead page still shows its title. If the title is empty, the bare address, which shows its fetched title once one is known. (Decided 2026-11-02; replaces the title on one line and the address on the next, which showed the title twice.)
- **Created when it was bookmarked:** the note's created date is `ADD_DATE`, as the other imports keep a file's dates. If it's missing, the import time.
- **Folders become folder tags** under the prefix folder: `Bookmarks/Recipes/Soups/`.
- **The browser's own top folders are left out:** Chrome's "Bookmarks bar", "Other bookmarks" and "Mobile bookmarks"; Safari's "Favorites" and "Bookmarks Menu"; Firefox's "Bookmarks Toolbar", "Bookmarks Menu" and "Other Bookmarks". They say where the browser showed a bookmark, not what it's about. A folder on Chrome's bar comes in as `Bookmarks/Recipes/`, and a bookmark loose in a top folder goes straight into the prefix folder. *Check* how each browser marks these in the file (Chrome's bar carries `PERSONAL_TOOLBAR_FOLDER="true"`); recognize them by that, or by their position as the top level, rather than by their name, which is translated.
- **Firefox's tags become ordinary tags.**
- **Source tag:** `imported:source=bookmarks:at=…`.
- **The import fetches nothing from the bookmarked sites:** no titles, descriptions or page text. It would be slow, many pages are dead or need a login, and it would contact every site the user saved. Favicons in the file are left out. Once imported, a bookmark is a link like any other: its site's icon is looked up the first time its note is shown.

## 3. Duplicates

- **One address is one note.** The same address in two folders is one note carrying both folder tags.
- **Importing again only adds** (decided 2026-11-02, `import-export-launch.md` §5): every bookmark in the file comes in again beside the earlier import, with its own import tag. Nothing is matched against earlier imports. (Replaces matching on the address with `replaced` and `removed` marks, from the dropped `importing-again` note.)

## 4. Through the import walkthrough

A new source card, **Browser bookmarks**. Its steps:

1. **Source:** Browser bookmarks.
2. **File:** the Folder screen's shape for one file. A card showing the file's name and "1,240 bookmarks in 38 folders", **Choose File…** to pick one or another, and under it **Folder as it will appear in MetaList**, defaulting to `Bookmarks/`, with the same notice when that folder exists (keep and merge, or rename). The file is uploaded from the browser, so this works on hosted and self-hosted servers as well as on the user's own machine. A file that isn't a bookmarks export is refused on this screen with a sentence saying so.
3. Files, Markdown, Images and Previews don't apply and are skipped.
4. **Summary:** how many bookmarks will come in and in how many folders, the bookmarks left out (decided below), and the prefix folder.
5. **Import**, and the report as the other imports give it, with any bookmark left out and why (no address, say).

## 5. Dropping a bookmarks file

**A dropped bookmarks file opens the import walkthrough** instead of being attached:

- **Browser bookmarks is already chosen** on Source, and the File step's card is already filled in with the dropped file. The user presses Next, Next, Import.
- Opened from the menu, Source still starts with nothing chosen. A drop chooses it only because MetaList already knows what the file is.
- Cancelling the walkthrough adds nothing; the file isn't attached.
- Recognition reads the start of the file, before any upload or preview. Every other `.html` file is dropped as today.

- **Wherever it is dropped, it asks first** (the maintainer, 2026-11-02, replacing "opens the walkthrough at once"): a small dialog, **Import Bookmarks** (focused, so Enter takes it) or **Keep as File**, and Cancel. Import opens the walkthrough as above; Keep as File drops it as any web page is dropped (a new note at the top, or into the note being edited where it lands, with its preview). One rule, onto the list or into a note. Code: `bookmarks-drop-choice-modal-service.js`, `dropPossibleBookmarksFile` in `keyboard-events.js`.

## 6. Invariants

1. A bookmarks file is recognized by its contents, never by its name alone.
2. Nothing is imported before the user has seen the Summary.
3. The import fetches nothing from the bookmarked sites.
4. One address is one note however many folders hold it, within one import.
5. The browser's own top folders never become folder tags.

## 7. Done when

1. Browser bookmarks is a source in the walkthrough and in `IMPORT_SOURCES`, with the steps in §4.
2. Exports from Chrome, Safari and Firefox import with their folders, dates and (Firefox) tags, without the top folders; tests use a small sample of each.
3. Importing the same file twice brings it in twice, each import under its own import tag.
4. Dropping a bookmarks file opens the walkthrough as in §5; dropping any other `.html` file is unchanged.
5. `docs/ready-to-build/import-export-launch.md` lists the source.

## 8. Still open

- ~~Whether the note shows the date added as a line.~~ **Decided 2026-11-02: no;** the note's Created date already is that date (shown in its menu, used by sorting by Created and the Created date range).

## 9. Checked against the code (2026-11-02, when filed)

The references in §0 hold: `IMPORT_SOURCES` (`obsidian`, `markdown`, `files`) in `app/services/obsidian_import/sources.py`; the walkthrough's `SOURCES` and `importSteps` (Source, Folder, Files, Markdown, Images, Previews, Summary) in `import-wizard-steps.js`; `created_at` in `notes.py`; `_HTML_EXTENSIONS` in `file_text_preview.py`.

Found:

- **No import takes an uploaded file today.** Every source is a folder path picked in the server's own dialog (`POST /import/pick-folder`, then `ImportFolderRequest.folderPath` in `app/api/routes/imports.py`). §4's upload from the browser is new: a route that takes the file, and `ImportSourceKey` (the same file) gains `bookmarks`. The hosted folder upload (`folder-import-and-file-previews.md` §4) isn't built either, so this would be the first upload into an import.
- **There is no import report any more** (dropped 2026-11-01, `import-export-launch.md` §5): the walkthrough closes on a search context of the import's tag. §4's "the report as the other imports give it" can only mean the Summary, so bookmarks left out (no address) would be listed there, before the import. *Ask.*
- **Drops** are handled in `keyboard-events.js` (`handleDropEvent`, `processDroppedFiles`, with `shouldCreateTopNoteForFileDrop` in `file-drop-policy-service.js`). A drop onto a note and one onto the list both go through it; Recognizing a bookmarks file goes before both, so the walkthrough opens wherever it lands (§5).
- **Folder and tag names** would go through the same cleanup as a vault's (`_tag_text`, `_checked_tag` in `notes.py`: spaces become dashes, renames reported), and under the prefix folder (`import_folder_prefix`, `folder_tag_for`).
- **The exports themselves can't be checked from the repo:** there is no sample from any browser. Tests need a small real export from Chrome, Safari and Firefox (§7.2), including how each marks its top folders (§2).
- Aside: `app/static/js/modules/import-sources.js` holds a second, older `IMPORT_SOURCES` (Obsidian and Markdown only) that nothing imports; the walkthrough's `SOURCES` is the live list.

### Decided (the maintainer, 2026-11-02)

- **Bookmarks that can't be used in MetaList are left out and listed on the Summary,** before anything is imported; there is no report afterwards (the import report was dropped 2026-11-01). **Only website addresses come in** (`http:` and `https:`; the maintainer: "we only want URLs to websites"). Everything else is left out: a bookmark with no address, Firefox's smart folders (`place:` addresses such as "Most Visited"), bookmarklets (`javascript:`), browser-internal pages (`chrome://`, `about:`, `edge://` and the like) and files on the computer (`file:`, found in the Firefox export). The Summary gives the count by kind ("3 left out: 2 Firefox smart folders, 1 bookmarklet") with a fold arrow listing each by title. This replaces §4's "the report as the other imports give it".
- **The file is uploaded from the browser,** for Choose File and for a drop alike (§4, §5): one path that works on personal, self-hosted and hosted, read in memory with no plaintext temporary file. It is the first import that uploads; the folder imports keep the server's folder dialog on a personal install until their hosted upload (`folder-import-and-file-previews.md` §4) is built.
- **A dropped bookmarks file asks first, wherever it is dropped:** Import Bookmarks (the default) or Keep as File (§5).
- **Each bookmark is one line, its title linked to its address, with no date line** (§2, §8): no repetition, the user's own title kept, nothing fetched for it.
- **Tests start from a real Firefox export** (Chrome's next, once it can be exported; Chrome wouldn't open on 2026-11-02), which the maintainer provides outside the repo. Only its structure is read (elements, attributes, how the top folders, dates and any tags are written, counts), never its titles or addresses; the committed samples are made up with the same structure. Chrome's and Safari's formats stay unchecked until an export of each is at hand: §7.2's samples for them must not be written from memory and passed off as checked.

### Checked against a real Firefox export (2026-11-02)

Structure only, from the maintainer's own export (Firefox on macOS, 123 bookmarks in 11 folders, nested 3 deep); no titles or addresses were copied:

- The first line is `<!DOCTYPE NETSCAPE-Bookmark-file-1>`, as §1 says. A `<meta>` Content-Security-Policy and `<TITLE>Bookmarks</TITLE>` follow.
- **Firefox's top level is the Bookmarks Menu itself:** the menu's own bookmarks and folders sit directly in the outermost list, with no folder for the menu. Bookmarks Toolbar is a folder there, marked `PERSONAL_TOOLBAR_FOLDER="true"` (as Chrome's bar is). So "recognize the top folders by their position as the top level" (§2) is wrong for Firefox: a folder the user made in the menu is at the same level as the toolbar and must be kept. Leave out only the marked folder, and keep everything else at its path.
- **Other Bookmarks didn't appear** (it was empty in this export), so how Firefox marks it when it has bookmarks is still unchecked.
- **Firefox's own "Mozilla Firefox" folder** (the bookmarks it comes with) is an ordinary, unmarked folder in the menu, so it comes in as `Bookmarks/Mozilla-Firefox/` unless the user deleted it in Firefox.
- Every link has `HREF`, `ADD_DATE` and `LAST_MODIFIED`, both dates in seconds (10 digits). Folders carry the same dates. Most links carry `ICON_URI` and an `ICON` data URI (left out, §2).
- No `TAGS` attribute (this user tags nothing in Firefox) and no `place:` smart folders, so neither is checked yet.
- Addresses: 115 `https`, 5 `http`, 2 `file:` and 1 `about:`. One address appears in two folders (§3: one note with both folder tags). No bookmark has an empty title.

### Acceptance checks (2026-11-02, before the code)

What the maintainer should see, with their own Firefox export:

1. **Source** shows a fourth card, **Browser bookmarks**, under Any folder.
2. Choosing it, Next shows **File**: "No file chosen yet" and **Choose File…**. Choosing the export shows its name with a check and "123 bookmarks in 11 folders", and under it **Folder as it will appear in MetaList**, `Bookmarks` at first, with the same notice as the folder imports when that folder exists.
3. Choosing a file that isn't a bookmarks export says so on the File screen, and Next refuses.
4. Next goes straight to **Summary** (no Files, Markdown, Images or Previews): how many bookmarks become notes, how many folders become folder tags, the folder everything goes into, and "3 left out: they aren't website addresses" with an arrow listing each by title and kind (2 files on this computer, 1 browser page).
5. **Import** closes the walkthrough on a new search context of the import's tag. Each bookmark is one note, one line: the site's icon, the bookmark's title, ` · domain`. Its tags are its folder under `Bookmarks/` and `imported:source=bookmarks:at=…`; Firefox's Bookmarks Toolbar is not a folder level. Its Created date (note menu) is the day it was bookmarked.
6. An address saved twice is one note: in two folders, it carries both folder tags; twice in one folder (as one is in the maintainer's export), that folder's tag once.
7. **Dropping the export** onto the list, or into a note being edited, asks: Import Bookmarks (focused) or Keep as File. Import opens the walkthrough on Source with Browser bookmarks chosen and the File step already filled; Next, Next, Import. Closing the walkthrough adds nothing. Keep as File attaches it as before. Dropping any other `.html` file works as before, without asking.
8. All of it reads well in the dark theme.
