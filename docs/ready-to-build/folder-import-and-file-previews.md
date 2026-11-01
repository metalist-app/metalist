# Importing a folder of any files, and which files get previews

**Status:** Agreed with the maintainer 2026-11-01. Ready to build, apart from the open points in §7. Related: `virtual-folders` (folder tags ending in `/`, handed over the same day); this import doesn't depend on its folder tree.

Written from a read-only look at the repo; filed from `docs/inbox/` on 2026-11-01, with the references checked (§9).

---

## 0. Today (from the code)

- The Obsidian and Markdown-folder imports pick a folder with the operating system's dialog **on the machine the server runs on** (`app/api/routes/imports.py`, `native_folder_picker`), show a summary first (`preview_import`), skip hidden folders and report them, and bring in a non-Markdown file only as an attachment some note refers to (`app/services/obsidian_import/vault.py`).
- A file may be up to 100 MiB (`app/upload_limits.py`, `MAX_ATTACHMENT_BYTES`).
- A dropped `.txt`, `.md`, `.csv` or `.json` file up to 200 KB gets its text copied into a child note, rendered with `@markdown`, `@csv` or `@json` (`app/services/file_text_preview.py`). Images and `.eml` emails have their own previews (`docs/ui/references.md`). Every other file, PDFs included, shows a file card.

## 1. The idea

With folders as tags, a folder of files from the computer comes in the way an Obsidian vault does, keeping its structure. A new import source: **a folder of files**, any kind.

## 2. What each file becomes

- **Markdown and text files** become notes with their text, as the Markdown-folder import does.
- **Every other file** becomes a root note holding just the file (as a drop does: its card, or the picture), with a preview where its type has one (§5). No line with its name over it: the card shows the name (the maintainer, 2026-11-01), and search finds the note by it.
- **Each note gets its folder's tag** with the trailing slash (`Photos/2024/`); files at the top of the chosen folder get none.

## 3. The size check and the file-type checklist

Before anything is copied, the walkthrough shows what the folder holds, grouped by file type:

| | Type | Files | Size | Bar |
|---|---|---|---|---|
| ☑ | Images | 1,840 | 3.4 GB | ████████████ |
| ☑ | PDF | 312 | 1.2 GB | ████ |
| ☐ | Code dependencies (`node_modules`) | 38,500 | 610 MB | ██ |
| ☑ | Markdown and text | 96 | 2 MB | ▏ |
| ☐ | Hidden and system files (`.DS_Store`, `.git`) | 4,210 | 9 MB | ▏ |

- **Sorted by total size,** largest first.
- **A bar per type** shows its size relative to the others, in one neutral color, beside the numbers.
- **Smart defaults; the user decides.** Hidden and system files, version-control folders, code dependency folders and app caches start unticked; everything else ticked.
- **A total bar** under the list: what's ticked against the storage left (the hosted plan's storage; on personal and self-hosted, the disk's). It updates as boxes change.
- **Red only for going over a limit, never for being large:** a type holding files over the per-file limit, and the total bar when the ticked files won't fit.
- Files over the per-file limit are listed and skipped. The report lists everything left out, with the reason.

## 4. Choosing the folder on hosted

The current dialog runs on the server's machine, which is the user's computer only in the personal deployment. **Hosted and self-hosted need the folder from the browser:** a folder picker or a folder dropped on the page. The browser can list names and sizes before uploading, so the checklist in §3 comes first; then the ticked files upload one by one. *Check* how browsers cope with very large folders.

## 5. Previews, in order

1. **Code files** (`.py`, `.js`, `.sh`, …): text, shown with `@code=<language>` as code already is. Another table of extensions in `file_text_preview.py`.
2. **PDF:** no preview note (changed 2026-11-01, see "Searchable file text" below): its text is kept with the file, encrypted, for search only, and the PDF itself is shown by the browser.
3. **RTF and `.docx`:** a preview note keeping headings, bold, italics, lists and simple tables, through the same HTML sanitizing as a note's content (`.docx` with `mammoth`, RTF with MetaList's own converter), and their text kept with the file for search too.
4. **HTML files:** sanitized as pasted HTML is.
5. **Audio and video:** the browser's own player; no text.

**Not previewed:** spreadsheets, PowerPoint, Pages and Numbers (hard to convert faithfully; a wrong preview is worse than a file card).

Previews keep today's rules: the copied text is an ordinary child note, editing it never changes the file, and a file too large for a preview keeps only its card. The previews apply to dropped files too, not only to the import.

## 6. Invariants

1. Nothing is copied before the user has seen the size check and the checklist.
2. Nothing is left out silently: every skipped file or type is in the report with its reason.
3. Red marks only something over a limit.
4. A preview never changes the stored file.

## 7. Left to you (all four decided 2026-11-01: §9)

- How a hosted import uploads a large folder from the browser, and whether it resumes after a dropped connection.
- The converter for RTF and `.docx` (`pandoc`, or a smaller library), weighing size and safety.
- How much of a long PDF's text a preview holds (text previews stop at 200 KB today).
- The default list of junk folders and files.

## 8. Done when

1. "A folder of files" is an import source; each file becomes a note as in §2, with its folder tag.
2. The checklist, bars, total and red states behave as in §3, before anything is copied.
3. The import works from the browser on hosted and self-hosted (§4).
4. Code files, PDF, RTF, `.docx`, HTML, audio and video get the previews in §5, for imports and drops.
5. The behavior is described in `docs/ui/`, with tests for the checklist defaults, the limits and each preview type.

## 9. Checked against the code (2026-11-01, when filed)

Every reference in §0 holds: the native folder dialog (`imports.py`, `pick_folder`), the summary (`preview_import`), hidden folders skipped and reported (`vault.py`, `_HIDDEN_PREFIX`), other files only as attachments a note refers to, the 100 MiB limit (`upload_limits.py`, overridable with `METALIST_MAX_ATTACHMENT_BYTES`), the 200 KiB text previews of `.txt`, `.md`, `.csv`, `.json` (`file_text_preview.py`, `MAX_PREVIEW_BYTES`), and a PDF shown as a card with a `PDF` badge (`embedded_references.py`). `@code=<language>` exists (Pygments, any alias: `docs/ui/content-formatting.md`).

Found:

- **Text files aren't imported today.** The Markdown-folder import reads `.md` files only (`vault.py`, `_MARKDOWN_SUFFIX`; `count_markdown_files` counts only those), so §2's "as the Markdown-folder import does" means adding `.txt` (and any other text type) to it.
- **Hidden folders: skipped today, a type to tick here.** The Obsidian and Markdown imports skip hidden folders outright and report them; §3 lists them as a type that starts unticked. Whether the vault imports keep skipping them or get the same checklist is open below.
- **Folder tags with the slash exist only on `feature/virtual-folders`** (`notes.py`, `_folder_tag`), not on `main` yet. §2 builds on that branch landing.
- **The folder count before importing** (`pick_import_folder`) counts Markdown files only; the checklist needs every file's type and size.

### Decided (the maintainer, 2026-11-01)

- **The Obsidian and Markdown imports keep skipping hidden folders** and reporting them, as now; the checklist is for the folder-of-files import.
- **A hosted import resumes** (§7, first point): the browser uploads the ticked files one at a time and MetaList records which have arrived. If the upload stops (sleep, a dropped connection, a closed tab), MetaList offers to resume when the user comes back: they pick the same folder again (a page can't reopen it by itself) and the files already in are skipped. Every file that arrived is kept either way.
- **RTF and `.docx` use small Python libraries** (§7, second point; RTF changed 2026-11-01: MetaList's own converter, see "Searchable file text" below), not pandoc: installed with MetaList's Python dependencies on every platform, nothing extra to install. A `.docx` keeps headings, bold, italics and lists (a library such as *mammoth*, to HTML); an RTF preview may be plain text if the simple RTF libraries give no formatting, which is acceptable since the original stays attached. Everything converted goes through the note sanitizer as pasted HTML does. Check each library's current version, maintenance and licence before adding it.
- *Superseded 2026-11-01 by "Searchable file text": a PDF has no preview note, so neither question below is asked.* **A PDF's text up to 200 KB goes into its preview whole; past that, MetaList asks** (§7, third point): a dropped PDF whose text is over 200 KB brings a question offering the first part (200 KB, the note ending with a line saying the rest was cut) or the whole text, so search finds words anywhere in it. The whole text still stops at a safety cap the user sets in the menu (a setting, 500 KB by default: more is no preview anymore, decided 2026-11-01). Past the cap the note ends with the same line.
- **A folder import asks once for all long PDFs:** one question in the checklist step ("PDFs with more than 200 KB of text: first part / whole text"), applying to every such PDF, with an optional threshold for this import that applies to all of them (instead of the 200 KB) (decided 2026-11-01).
- **Previews are a choice in the import** (the maintainer, 2026-11-01): the walkthrough offers to make the previews of §5 or just store the files; just storing gives each file its note and card, no preview children.
- **Which previews start ticked** (the maintainer, 2026-11-01; PDF changed the same day by "Searchable file text": no row, its text always kept for search): a preview is note data (the file's text copied into a child note) on top of the file data, so it costs notes-database size, a child note per file, and puts the text where search and the AI's note tools reach it. The screen ticks PDF, Word and RTF at first (finding words in documents is why they come in; their text is small beside the file) and leaves code and HTML unticked (they come in numbers, and a preview copies the whole file). Each type shows how many files and about how much note data ticking it adds. Audio and video have no box: their player copies nothing.
- **Dropped files preview every type that has a preview** (the maintainer, 2026-11-01): no question and no setting, as `.txt` and `.md` drops already do; a drop is deliberate and small, and deleting the preview's child note removes its note data and keeps the file. The import's ticks apply to that import only. A PDF with more than 200 KB of text still asks, as decided above.
- **Word and RTF now, in order** (the maintainer, 2026-11-01): first PDF, code and HTML previews (no new dependency: `pypdf` is one already), each with its own early look; then Word (`.docx`) and RTF on the same branch, before real folders are imported, so no imported file misses its preview and no "make a preview" action for older files is needed. Likely libraries: `mammoth` for `.docx` (to HTML, keeping headings, bold, italics and lists) and `striprtf` for RTF (plain text); check each one's current version, upkeep and licence before adding it. Old binary `.doc` and `.pages` stay file cards.
- **PDF, code and HTML previews, first step: acceptance checks** (2026-11-01, before the code). Dropped files: (1) a dropped `.py` (and the other code endings of §5) gets a child note with its code, tagged `@code=<language>` and drawn highlighted; (2) a dropped PDF gets a child note with its text, page after page; one with more than 200 KB of text gets the first 200 KB and a last line saying the rest was cut (the question offering the whole text, its cap setting and the import's threshold come in a later step); (3) a scanned PDF with no text, or one that can't be read, gets no preview and the drop says why in the floating message, as a file too large does today; (4) a dropped `.html` page gets a child note showing the page as pasted HTML shows (scripts, styles and the page's head left out); (5) `.txt`, `.md`, `.csv` and `.json` drops are unchanged. The import (Any folder): (6) a Previews screen after Images, only when ticked files have previews: one row per type (PDF; Code; Web pages; CSV and JSON), each with how many files and about how much note data its previews add; PDF ticked at first, the rest not; (7) a ticked type's files come in with the same child note a drop gives them, an unticked type's with just their card; (8) the Summary says how many previews will be made as note data. Not in this step: Word and RTF, PDFs shown by the browser, previews for an Obsidian or Markdown folder's attachments.
- **Searchable file text** (the maintainer, 2026-11-01, after the first PDF previews read badly: a PDF's text comes out in reading order only by guessing its layout, and the tools that guess well are heavy machine-learning models; a PDF's own look is best seen in the PDF):
  - **A PDF gets no preview note.** Its text is extracted (pypdf, as now) and kept with the file as file data: in the files database, encrypted as the file is, so it backs up with the file and never grows the notes database. The PDF itself is read in the browser's viewer (§5).
  - **Word (`.docx`) and RTF get a preview note,** as code and web pages do: `.docx` through `mammoth` to HTML, RTF through MetaList's own converter (RTF says outright what is bold, a paragraph or a table cell, so nothing is guessed: paragraphs, bold, italics, underline, headings by font size, colours, every script's characters, lists and simple tables; pictures and rare features left out), both through the note sanitizer. Their text is also kept with the file, so they are found by their words even after the preview note is deleted.
  - **Search finds a note by the text of the files it shows,** as it finds it by their names today, with the same matching (any case, also inside words: `"fat"` finds "father"). How (the maintainer, 2026-11-01, after measuring: a quoted term scans about 6 ms per 10 MB of text, so scanning every file's whole text would slow every search as files pile up):
    - **Stored per file, encrypted:** the extracted text (pulled out once, in the background, when the file arrives) and a bloom filter of its 4-letter pieces (casefolded). The filter is encrypted too: it can be asked whether a file holds a word.
    - **Loaded at login:** only the filters (about 7% of the text's size: 75 KB for 1 MB of text), in the background as the `[[` catalog is. The text is never loaded at login.
    - **At search:** each quoted term of 4 or more characters is checked against every file's filter ("definitely not" or "maybe"; about 5 ms for 500 files). Only a "maybe" file's text is read and decrypted (about 1 ms per MB) and searched for real, so the results are exactly those of a full scan. Measured on 1 MB of English: a word the file doesn't hold still looks possible 7% of the time with 4-letter pieces (51% with 3, 1% with 5, at more than twice the size).
    - **Shorter terms** (`"AI"`) can't use the filter: every file's text is checked.
    - **A bounded cache of recently read text** (about 64 MB, emptied when the vault locks, as email words are): search-as-you-type, suggestions and repeated searches reuse it, so a short term is slow only the first time.
    - **The snippet** under a matched card comes from the same text.
  - **A match inside a file shows why:** a short snippet of the file's text under its card, the found words highlighted. A new on-screen element: its cases are agreed before the code (interaction principles).
  - **Always on, for drops and imports:** no box on the Previews screen (it keeps Code, Web pages, CSV and JSON, and Word and RTF). Files already in MetaList get their text once, in the background, from the bytes MetaList holds.
  - **The AI doesn't read it:** file text is not note text, so the AI's note tools don't see it.
  - **A schema change:** a new encrypted table in the files database (one row per file: its text and its filter, with the file's content revision, so a replaced file's text is extracted again). Database version 12 → 13, a migration, the encryption audit and `docs/security/README.md` (AGENTS.md).
  - **Undid part of the first step** (2026-11-01, before it was committed): the PDF preview note and the PDF row of the Previews screen went, so its acceptance checks (2), (3) for PDFs and "PDF ticked at first" in (6) no longer apply; its code, web page, CSV and JSON previews stayed, none ticked at first.
  - **Up to 5 MB of text per file** (about 2,000 pages; 1 MB is about 400 to 500 pages of a book): every real book whole. The cap only bounds what checking one file costs. A file cut there says so in its snippet ("search covers the first ~2,000 pages").
  - **Built for PDF 2026-11-01** (docs/ui/search-semantics.md, docs/ui/references.md "File text snippets"; tested in a throwaway: phone width, dark theme, edit and Escape, folding, Find). Found while checking: a snippet's lines made a one-card note foldable, and folding it hid the snippet and the arrow for good; the snippet no longer counts toward folding, and a note folded with nothing to fold shows it. Kept so (the maintainer, 2026-11-01): a snippet never makes a note foldable, because folding is data that persists, while a snippet is there only for one search. A folded note shows no snippet even when its card is its first line (weighed and kept the same day): a snippet shown only when the card happens to be the folded line would be an exceptional rule, and odd when the card is folded away.
  - **Acceptance checks** (agreed 2026-11-01, before the code; the snippet's cases agreed with the maintainer, AGENTS.md "On-screen Behavior"). This step covers PDF; Word and RTF text join it when their converters are built.
    1. A quoted search finds a note holding a PDF by a word in the PDF, with the usual matching: any case, inside words (`"lease"` finds "Leaseholder"), edge spaces for word edges.
    2. An excluded phrase (`-"draft"`) leaves out a note whose PDF holds it.
    3. Results are exactly those of reading every file's whole text (a test runs both on the same files and compares them).
    4. A PDF dropped or imported becomes searchable once its text is extracted in the background, and PDFs already in MetaList are extracted once in the background after login. Until then they match by name only; a later search finds them, and nothing redraws by itself.
    5. At login only the filters are loaded; no file's text is held in memory until a search reads it, and the cache of read text stays under its size and empties when the vault locks.
    6. In a vault with a password, the text and the filter are stored encrypted; the encryption audit accepts the files database at versions 12 and 13; a version-12 database migrates; a restored older backup is migrated as installed, the archive untouched.
    7. Deleting a file deletes its text; a file whose content is replaced gets its text extracted again.
    8. A scanned PDF (no text), a damaged one and one locked with a password come in as files that match by name only, with no error.
    9. A PDF with more than 5 MB of text keeps the first 5 MB; its card's tooltip says search covers the first ~2,000 pages.
    10. Full screen, floating windows, export, print, copied text and find in the list (`Cmd+F`) neither show nor search file text.
  - **The snippet's cases** (principles 1, 2, 3 and 5 of `docs/ui/interaction-principles.md`; proposed, to be agreed):
    - *Shows* under a file's card, in a note in the list, when a required quoted phrase of the search is in that file's text: a line or two of text around the first match, cut at word edges with "…", every required phrase in it marked as search highlights are (soft yellow; dark gold in the dark theme). The search is the user's action and the list is drawn again for it anyway, so the snippet adds no movement of its own (2); the mark tells where in the file the search matched, which the user can't see otherwise (5).
    - *Several files* in one note: a snippet under each file that matched; *one file, several phrases*: one snippet, from the first match, marking every phrase it shows.
    - *A note that matches by its own text and by a file:* the snippet shows too (it says the file matched as well).
    - *A phrase only in the file's name:* no snippet (the name is on the card).
    - *Excluded phrases and tags:* never a snippet.
    - *A collapsed note:* the card shows if it is on the first line, without a snippet: collapsing is the user's choice (4), and a snippet would make the note taller. (Open: a small mark on the card instead, taking no space.)
    - *Embedded notes and children shown under a matching note:* a snippet under a matched file there too, as highlights are marked there.
    - *Clicking into the note to edit:* the card turns into its `![[id]]` line, as today, and the snippet goes with it; the clicked point stays under the pointer (1), as when a card turns into its line today.
    - *Escape after editing:* the snippet comes back under the card; the caret's line stays at the same height (1), the viewport hold taking the snippet's height into account like the card's.
    - *Changing the search:* snippets come and go with the redrawn list only; a search that is not changed never gains or loses one (2), even when a file's text finishes extracting meanwhile.
    - *Clicking the snippet:* does what clicking the card does.
    - *Narrow window, phone width:* the snippet wraps under the card within the note's width; no horizontal scroll.
    - *Not shown:* full screen, floating windows, export, print, copied text; find in the list does not search it.
- **The checklist, as tried** (the maintainer, 2026-11-01): each kind opens (the notes' fold arrow) to list its files, the largest first, a file over the limit named in red; each file has a box, ticked as its kind is unless ticked against it (the kind's box a dash then; ticking the kind sets all its files again); each kind's bar is green for what will be imported and grey for what won't. Split and Write as are asked only when Markdown files are ticked.
- **Markdown files: notes or files** (the maintainer, 2026-11-01): a folder of files' Markdown screen first asks, for all of them at once, Turn into notes (recommended) or Keep as files; kept, each is a note holding just its file, as a PDF is, and Split and Write as aren't asked. A `.txt` file still comes in with its text. The Obsidian and Markdown imports don't ask.
- **Images can be compressed** (the maintainer, 2026-11-01): an Images screen after the Markdown one, only when the import brings in images it can shrink (JPEG, PNG, WebP, TIFF, BMP), in every source (a vault's linked images too). Keep originals (chosen at first) or Compress: at most the chosen size on the longest side, high quality, turned upright, without location and camera data. **The size is chosen** (the maintainer, 2026-11-01, after weighing a maximum file size, which would make some photos blurrier than others, and a maximum width and height, which shrink portrait photos more): four cards, 1280, 1920, 2560 (chosen at first) and 3840 pixels on the longest side, each showing about what the import's images come to at it. The summary then says which files become notes and which are stored as file data (they back up differently), and at what size images come in. Acceptance checks (before the code): (1) the screen shows only when such images come in: a folder of files with them ticked, a vault or Markdown folder holding them; (2) it says how many images, their size now and about their size compressed; (3) Keep originals is chosen when it first shows, and importing so stores each image byte for byte; (4) with Compress, a 4000×3000 photo comes in 2560 wide, a sideways phone photo comes in upright, and neither keeps its location or camera data; (5) an image already small enough, or one compression wouldn't make smaller, comes in unchanged; (6) GIF, SVG, HEIC and AVIF, and animated images, come in unchanged; (7) an image that can't be read comes in as it is, and the import goes on; (8) a TIFF or BMP comes in as JPEG (PNG when it has transparency), its name ending to match; (9) in an Obsidian note, `![[photo.jpg]]` shows the compressed photo.
- **The default unticked list** (§7, fourth point; §3's smart defaults):
  - Folders: hidden ones (a name starting with a dot: `.git`, `.obsidian`, `.vscode`, `.cache`, `.Trash`); code dependencies (`node_modules`, `bower_components`, `vendor`, `.venv`, `venv`, `__pycache__`, `site-packages`); build output (`dist`, `build`, `target`, `.next`, `out`); system folders (`$RECYCLE.BIN`, `System Volume Information`).
  - Files: hidden ones (`.DS_Store`, `.gitignore`, `.env`); system leftovers (`Thumbs.db`, `desktop.ini`, `Icon\r`); Office lock files (`~$…`); compiled leftovers (`.pyc`, `.o`, `.class`).
  - Each is a row in the checklist the user can tick back.

Nothing is left open for this note.
