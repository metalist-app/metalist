# Files shown, not copied: no preview notes

**Status:** Agreed with the maintainer 2026-11-03. Part 1 (§2 to §4, §7) and §5's drops (checks 22 to 26) built the same day, in an early look; still to build: the Markdown screen's sample from the dropped file (it shows the built-in sample), a folder import's `.txt` files following the Markdown screen (check 27), and Convert to Note (§6). Ready to build; §9 and the open points of §11 decided the same day. **Replaces the preview notes** of `docs/ready-to-build/folder-import-and-file-previews.md` §5 and its later preview decisions ("Which previews start ticked", "Dropped files preview every type", the preview half of "Text and preview versions"). Keeps its searchable file text and extends it.

Written from a read-only look at the repo; filed from `docs/inbox/` on 2026-11-03, with the references checked and what it meets in the code recorded (§11).

---

## 0. Today (from the code)

- A dropped or imported text, CSV, JSON, code, web page, Word or RTF file gets a **preview note**: an editable child holding a copy of its text (`app/services/file_view.py`, `_PREVIEW_ALGORITHM_VERSIONS`). Editing it never changes the file. Preview versions and edits are tracked so newer algorithms remake untouched ones (`file_preview_notes`, files database version 14).
- PDF, Word and RTF have **kept text**: extracted once, stored encrypted with the file, used by search and `Cmd+F` with a snippet under the card (`app/services/file_text_search.py`, `TEXT_READER_VERSIONS`; `docs/ui/search-semantics.md`; `docs/ui/find.md`, "Inside files"). PDFs have no preview note.
- Pictures, `.eml` emails and drawings already show themselves in the note; a picture has a `download image` control (`docs/ui/references.md`).
- Clicking a file card's badge or name downloads the file. No viewer exists, and no audio or video player (planned only, §5 of the folder-import doc).
- The import walkthrough's Markdown screen offers Turn into notes / Keep as files, Split and Write as, on a live sample (`import-wizard-steps.js`, `MARKDOWN_AS`, `SPLITS`, `CONTENTS`). A dropped bookmarks export already asks Import Bookmarks or Keep as File.

## 1. Why

Some file types had previews and others didn't, which reads as arbitrary, and a preview is an editable copy that drifts from the file it came from. Two jobs are kept apart instead: **finding** a file by its words, and **looking** at it. Neither copies the file into a note.

## 2. Finding: kept text for every file with text

- Kept text for PDF, Word and RTF as now, **plus text, Markdown, code, CSV, JSON and web pages**: same storage (`file_texts`), same filter, same snippet, same reader versions (add each kind to `TEXT_READER_VERSIONS`; files already in MetaList are read once in the background, as for the existing kinds).
- Kept text is never shown as a note and can't be edited.
- The AI's note tools don't read it, as today. Accepted; not part of this.

## 3. Looking: three kinds of file

| The file | How it shows |
|---|---|
| **Pictures, emails, drawings, audio, video** | **The note shows the file itself.** Pictures, emails and drawings as today; **audio and video get the browser's `<audio>`/`<video>` player in the note**, streamed from the authenticated file URL |
| **PDF, text, Markdown, code, CSV, JSON, Word, RTF, web pages** | **A card with two buttons: Open and Download.** Open brings up the viewer (§4) |
| **Everything else** | **A card with Download** only |

- The buttons say what a click does; no dialog asks which.
- Clicking the card's name or badge no longer downloads. Right-click actions (`Rename File…`) stay.
- The file text snippet under a matched card stays.

**Pictures stored as files: no download line.** The `download image` control under an embedded picture file goes, to cut clutter; its right-click menu does that job (`context-menu-registry.js`, the image items):
- **Copy Image** as today (the picture as shown, as a PNG).
- **Save Image becomes "Download File"** for a picture stored as a file: it already downloads the original (`image-context-menu-action-service.js`, `loadImageBlob`), which may be much larger than what is shown.
- A picture pasted into the text (not a file) keeps Copy Image and Save Image.
- Rename File…, Zoom Image and Open Image in New Tab unchanged.

## 4. The viewer

- **Over MetaList, as View Full Screen is;** closed with `Esc` or ×; **Download** in its corner; for `.md` and `.txt`, **Convert to Note…** too (§6).
- **Made when opened, never stored:**
  - PDF: the browser's own PDF viewer on the decrypted file (*check* the CSP and each browser).
  - Text and code: as text, code highlighted as `@code` is.
  - Markdown, CSV, JSON: drawn as `@markdown`, `@csv`, `@json` notes are.
  - Word (`mammoth`), RTF (MetaList's own reader), web pages: converted and sanitized as a note's HTML (`sanitize_note_html`). The existing converters move from making preview notes to feeding the viewer.
- `Cmd+F` in the viewer is the browser's own find, as in any dialog (`docs/ui/find.md`).
- Works at phone width.

## 5. Dropped `.md` and `.txt` files

- **A dropped `.md` file opens the import walkthrough at its Markdown screen,** filled in, the sample drawn from the dropped file: Keep as file, or Turn into notes with Split and Write as. Then Import. Dropped on a tree folder, the notes or the file get that folder's tag.
- **A dropped `.txt` file asks Note or File,** shaped like the bookmarks question. Note: a new note with its text. File: a card, as any file.
- **Several dropped together:** one question for all.

## 6. Convert to Note

- **Convert to Note…** in a `.md` or `.txt` card's right-click menu and in its viewer.
- A `.md` file goes through the Markdown screen; a `.txt` file converts at once.
- **It is a conversion:** the notes take the card's place (same position, same tags) and the file is removed. **Undo restores the file and its card** and removes the notes.

## 7. What goes away

- Preview notes and their special cases (folding, adopting older previews).
- The walkthrough's **Previews** screen.
- Preview version tracking (`file_preview_notes`, `_PREVIEW_ALGORITHM_VERSIONS`). Kept text keeps its own reader versions.
- **One-time cleanup, no compatibility code** (MetaList has no outside users yet): a preview note MetaList wrote and nobody edited (its last-updated time still the time MetaList wrote it, as the current tracking decides) is deleted; an edited one stays as an ordinary note, no longer tied to the file. A schema step drops the tracking table; update the encryption audit and `docs/security/README.md`.

## 8. Invariants

1. No file's contents are copied into a note, except by the user's own choice (a dropped or converted `.md`/`.txt` turned into notes).
2. Every file with text is found by its words.
3. A card says what its buttons do; nothing downloads or opens unasked.
4. Converting a file to notes removes the file; Undo restores it.

## 9. Decided (the maintainer, 2026-11-03, when filed: each as suggested)

- A dropped `.txt` focuses **Note**.
- `.md`/`.txt` dropped with other files: the text files ask; the rest come in as files at once.
- A `.md`/`.txt` dropped into a note being edited: the same question; Note inserts the text at the drop point.
- A folder import's `.txt` files (today always brought in with their text): the Markdown screen's Turn into notes / Keep as files covers them too.

## 10. Done when

1. No new preview notes are made by drops or imports; the Previews screen is gone; existing untouched previews are removed once, edited ones kept.
2. Text, Markdown, code, CSV, JSON and web pages are found by their words, with snippets and in `Cmd+F`.
3. Cards show Open and Download (or Download only) per §3; a picture file has no download line and its menu says Download File; the viewer shows each kind in §4; audio and video play in the note.
4. Dropped `.md` and `.txt` files ask per §5; Convert to Note works per §6, with Undo.
5. `docs/ui/references.md`, `search-semantics.md`, `find.md`, the folder-import doc and the help describe it; tests cover each row of §3, the viewer per kind, both drop questions, conversion and its Undo, and the cleanup.

## 11. Checked against the code (2026-11-03, when filed)

Every reference in §0, §3 and §5 holds: `_PREVIEW_ALGORITHM_VERSIONS` (`file_view.py`), `file_preview_notes` (files database version 14), `TEXT_READER_VERSIONS` (`file_text_search.py`), `docs/ui/find.md` "Inside files", the `download image` button (`embedded_references.py`, `note-file-image-download-link`), the image items of `context-menu-registry.js` (Copy Image, Save Image, Zoom Image, Open Image in New Tab, Rename File…), `loadImageBlob` (`image-context-menu-action-service.js`), and the walkthrough's `SPLITS`, `MARKDOWN_AS` and `CONTENTS` (`import-wizard-steps.js`).

What it meets in the code (all on `feature/virtual-folders`, uncommitted when filed):

- **The preview tracking was built the same day and is live in the maintainer's vault.** Database step 13 → 14 added `file_preview_notes` and the maintainer's MetaList ran it at a restart, which made first previews for older Word and RTF files and adopted older previews. So §7's "a schema step drops the tracking table" is a step 14 → 15. The one-time cleanup needs that table (which note is a preview, and the time MetaList wrote it), so it must run before the table goes. Migrations run at login, before the notes are loaded; the step can still read what it needs (it gets the vault key, `note_data` decrypts to the note and the time, and `notes.updated_at` is readable), but deleting notes there means relinking their siblings in SQL. Open (§9).
- **What stays from that day's work:** kept text's reader and filter versions (`file_texts.reader_version`, `filter_version`), the mammoth reader for Word (moves to the viewer, §4), and the RTF fix for TextEdit's line ends (RTF reader version 2). §2's new kinds are added to `TEXT_READER_VERSIONS`, and to the selection of searchable files (`is_searchable_file`, `is_searchable_file_name`); the reading worker (`file_text_worker.py`) knows PDF, Word and RTF only.
- **The docs and help built that day describe preview notes** ("Text and preview versions" and "Word previews through mammoth" in `folder-import-and-file-previews.md`, `docs/ui/references.md`, `docs/ui/floating-messages.md` "Updating previews", the help skill `help-references.md`): rewritten when this is built.
- **A dropped `.md` file reaching the walkthrough** has no path to it: the walkthrough reads a folder, picked on the server's machine or uploaded from a dropped folder (`app/services/import_uploads.py`). A single dropped file would go through the same upload.
- **§6, Undo restoring a removed file:** files are deleted outright today (`delete_files`). Open (§9).
- **On-screen changes** (cards with Open and Download, the viewer, the picture's download line going, the menu item renamed): their cases are agreed before the code (AGENTS.md, "On-screen Behavior").

### Decided, from the check (the maintainer, 2026-11-03)

- **The cleanup is the 14 → 15 step itself:** at login it reads the tracking table, deletes each preview note nobody edited (relinking its siblings), then drops the table. One step, nothing left over; an edited preview stays as an ordinary note.
- **Convert to Note replaces the card and keeps the file stored,** unreferenced, until Trim Unused Files removes it, so Undo only puts the card back (§6's "the file is removed" means its card).

## 12. Acceptance checks and on-screen cases (2026-11-03, before the code)

Decided with the maintainer the same day: a click on a card outside its buttons **edits the note** (as a click on a picture or diagram does); an inline `[[file]]` link **opens the viewer** for a type it shows and **downloads** any other; audio and video **load on Play** (the whole file, up to the attachment limit, then play: a file request needs the tab header, which `<audio>`/`<video>` can't send; streaming would need a new kind of file access); the PDF shows **in the viewer**, the security policy allowing frames of `blob:` addresses only (`app/security/http_headers.py`, today `frame-src 'none'`), which MetaList makes itself from the decrypted PDF. Proposed points are marked; the whole list waits for the maintainer's agreement.

**A. File cards** (`![[…]]`)
1. PDF, text, Markdown, code, CSV, JSON, Word, RTF and web page: badge, name, then **Open** and **Download** on the same line after the name.
2. Any other file: badge, name, **Download**.
3. Clicking the name or badge downloads nothing; elsewhere on the card it edits the note.
4. Phone width: the buttons wrap under the name, no sideways scroll; dark theme followed.
5. A folded note whose first line is a card keeps its buttons on that line.
6. A note being edited shows its card as its `![[…]]` reference, as today.
7. Floating windows and full screen show the buttons; downloaded exports and prints show the card without them.
8. A search snippet stays under its card.

**B. Pictures stored as files**
9. No `download image` line; the note is that much shorter.
10. Right-click: Copy Image, **Download File** (the original, in place of Save Image), Rename File…, Zoom Image, Open Image in New Tab.
11. A picture pasted into the text keeps Copy Image and Save Image.

**C. Audio and video**
12. A player in the note (video with its picture), never wider than the note, a video never enlarged past its own size.
13. Nothing plays until Play, which loads the file first.
14. Right-click: Download File, Rename File….

**D. The viewer**
15. Over MetaList as Zoom Image is: the file's name, **Download**, **Convert to Note…** (`.md`, `.txt`) and ×; `Esc` closes it, and (proposed) a click outside it.
16. PDF in the browser's viewer; text as text; code highlighted; Markdown, CSV, JSON drawn as their notes; Word through mammoth with its pictures; RTF through MetaList's reader; web pages sanitized.
17. A long file scrolls inside; closing leaves the list exactly where it was.
18. `Cmd+F` inside is the browser's find.
19. Phone width: full screen.
20. A file that can't be read says so, with Download.
21. (Proposed) Text over 5 MB shows its first 5 MB, a last line saying the rest is in the download.

**E. Dropped `.md` and `.txt`**
22. A `.txt` alone asks Note or File, Note focused; Note makes a note at the top with its text, File a card, Cancel nothing.
23. A `.md` alone opens the walkthrough at its Markdown screen, its sample from the file; on a tree folder, that folder's tag.
24. (Proposed) Several are asked once: any `.md` among them, the walkthrough takes them all; all `.txt`, the Note or File question covers them all.
25. With other files: the text files ask, the rest come in at once.
26. Into a note being edited: the same question; Note puts the text at the drop point, File the card.
    Built (2026-11-03): a `.md` dropped into a note being edited asks Note or File as a `.txt` does (no walkthrough: the drop is into that note); Note puts its text, as written, at the drop point. Elsewhere the other files come in first, then the question, so no two dialogs open at once (`dropWithTextFiles`, keyboard-events.js; the question in `text-drop-choice-modal-service.js`; the walkthrough opens at its Markdown step through `droppedTextFilesChoices`, import-wizard-steps.js). Built later that day (the maintainer: the notes didn't show in the search context they were dropped in): an import a drop starts (a `.md`, a folder, a bookmarks file) gives its top notes the tags a note made in that search context gets, filed in the context's virtual folder unless the import has a folder of its own, and the walkthrough closes on that context refreshed, not a new one (`droppedHere`, command-palette-controller.js; the request's `dropContext`; `drop_context_tags` and `root_records`, import_obsidian_vault.py; tests: `test_obsidian_import.py`). Undone 2026-11-11 (the maintainer: bookmarks dropped in the journal search came in among the journal entries): an import takes none of the search's tags, a drop's either, and the request carries no search (`root_records`; test: `test_a_dropped_import_takes_none_of_the_searchs_tags`, test_bookmark_import.py). The view after a drop is E in `desktop-drops-into-folders.md`.
27. A folder import's `.txt` files follow the Markdown screen's choice.

**F. Convert to Note**
28. In a `.md`/`.txt` card's right-click menu and its viewer; `.txt` at once, `.md` through the Markdown screen.
29. (Proposed) A card alone in its note: that note gets the text (or the first split note, the others after it as siblings), keeping its tags and place. A card among other text: the text replaces the card's line.
30. One Undo puts the card back; the file stays stored until Trim Unused Files.

**G. Search and cleanup**
31. `Cmd+F` and quoted searches find words in text, Markdown, code, CSV, JSON and web-page files, with a snippet; files already in MetaList are read once in the background ("Reading document text").
32. At the first login after the update, untouched preview notes are gone, edited ones stay as ordinary notes; no new previews, no Previews screen, no "Updating previews".

