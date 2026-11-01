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
2. **PDF:** its text, for reading and search, and the PDF itself shown by the browser.
3. **RTF and `.docx`:** converted to text, keeping bold, italics and lists where the converter can, then through the same HTML sanitizing as a note's content. Pick the converter (§7).
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
- **RTF and `.docx` use small Python libraries** (§7, second point), not pandoc: installed with MetaList's Python dependencies on every platform, nothing extra to install. A `.docx` keeps headings, bold, italics and lists (a library such as *mammoth*, to HTML); an RTF preview may be plain text if the simple RTF libraries give no formatting, which is acceptable since the original stays attached. Everything converted goes through the note sanitizer as pasted HTML does. Check each library's current version, maintenance and licence before adding it.
- **A PDF's text up to 200 KB goes into its preview whole; past that, MetaList asks** (§7, third point): a dropped PDF whose text is over 200 KB brings a question offering the first part (200 KB, the note ending with a line saying the rest was cut) or the whole text, so search finds words anywhere in it. The whole text still stops at a safety cap the user sets in the menu (a setting, 500 KB by default: more is no preview anymore, decided 2026-11-01). Past the cap the note ends with the same line.
- **A folder import asks once for all long PDFs:** one question in the checklist step ("PDFs with more than 200 KB of text: first part / whole text"), applying to every such PDF, with an optional threshold for this import that applies to all of them (instead of the 200 KB) (decided 2026-11-01).
- **Previews are a choice in the import** (the maintainer, 2026-11-01): the walkthrough offers to make the previews of §5 or just store the files; just storing gives each file its note and card, no preview children.
- **The checklist, as tried** (the maintainer, 2026-11-01): each kind opens (the notes' fold arrow) to list its files, the largest first, a file over the limit named in red; each file has a box, ticked as its kind is unless ticked against it (the kind's box a dash then; ticking the kind sets all its files again); each kind's bar is green for what will be imported and grey for what won't. Split and Write as are asked only when Markdown files are ticked.
- **Markdown files: notes or files** (the maintainer, 2026-11-01): a folder of files' Markdown screen first asks, for all of them at once, Turn into notes (recommended) or Keep as files; kept, each is a note holding just its file, as a PDF is, and Split and Write as aren't asked. A `.txt` file still comes in with its text. The Obsidian and Markdown imports don't ask.
- **The default unticked list** (§7, fourth point; §3's smart defaults):
  - Folders: hidden ones (a name starting with a dot: `.git`, `.obsidian`, `.vscode`, `.cache`, `.Trash`); code dependencies (`node_modules`, `bower_components`, `vendor`, `.venv`, `venv`, `__pycache__`, `site-packages`); build output (`dist`, `build`, `target`, `.next`, `out`); system folders (`$RECYCLE.BIN`, `System Volume Information`).
  - Files: hidden ones (`.DS_Store`, `.gitignore`, `.env`); system leftovers (`Thumbs.db`, `desktop.ini`, `Icon\r`); Office lock files (`~$…`); compiled leftovers (`.pyc`, `.o`, `.class`).
  - Each is a row in the checklist the user can tick back.

Nothing is left open for this note.
