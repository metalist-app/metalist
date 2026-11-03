# References and floating notes

Use this reference to explain MetaList accurately. It describes user capabilities,
not permission or tools for you to execute every operation. You can answer and
request one supported menu/dialog opening. You cannot submit a form, change
settings, run a shell command, or mutate notes through this help response. Do not
claim that you inspected current notes or settings: none are supplied here.
Prefer user-facing steps over implementation details. If the reference does not
answer a question, say what is unknown; do not invent syntax or controls.

Sources: docs/ui/references.md

# UUID References

## Status
- The written form decides, for notes as for files, anywhere in the text:
  - **Embed**: `![[UUID]]` shows the source in place. Alone in its note it is the note; amid other text it sits as its own tinted block, with its own ▾/▸, the text before and after it on lines of their own.
  - **Link**: `[[UUID]]` is always a link, even alone in its note. Until 2026-10-26 a lone `[[UUID]]` was an embed; those notes are links now, and adding `!` makes one an embed again.
  - **Link text**: `[[UUID|shown text]]` is a link that reads `shown text` instead of the target's first line, and keeps it when that line changes. Type `|text` before the `]]` by hand. The text is plain, runs to the `]]` (further `|` included) and can't hold brackets; an empty one is not a reference. `![[UUID|text]]` is still the embed, its text unused. A link to a file reads the text in place of the file's name.
  - References are made by typing `[[` (or `![[`), or with **Link to…** and **Embed…** (the right-click menu of the note being edited, for a right-click in its text, and the command palette), which type it and open the list. ⌘R and ⇧⌘R no longer paste references; they do nothing.
  - A link to an `@password` or `@username` note shows that note's own row: its icon and value (a password blurred). Clicking the value copies it; the link's reference icon goes to the note. Exports, prints and the AI show `••••••••`.
  - Typing `[[` in a note opens a list of notes to reference; what is typed after it narrows the list. ↑/↓ or pointing move, Enter, Tab or a click chooses (it becomes `[[UUID]]`, or `![[UUID]]` after `![[`), Escape closes the list and keeps the text. The note copied last (Copy Note) comes first whenever it matches, and first with nothing typed, until another is copied, even after a restart. Then notes whose first line holds the typed text, then near matches (a typo, part of a word), then notes holding it in their text (with a snippet), then near matches there; in each, notes the current view shows first, then the most recently edited; at most 8. The highlighted note's preview card shows beside the list. The card shows the top of the note as the list draws it (Markdown, headings, colours, pictures; passwords and usernames hidden), cut at about six lines with a fade. Resting the pointer on a `[[UUID]]` or `![[UUID]]` while editing, or on a link otherwise, shows the same card just below that line after a moment; moving off, typing, clicking or scrolling hides it. So does the caret inside one while editing (Escape hides it; `Previews While Editing` turns it off). A file's UUID shows the picture, diagram or file card. The note being edited is never offered. A password note is offered under its parent (found by the parent's first line), shown as a lock and `••••••••`, never by the password. Nothing matching shows no list; `[[@` starts a wrapper tag and opens nothing.
- File references keep two forms: `![[UUID]]` shows the picture or diagram, `[[UUID]]` a file card.
- An email file (`.eml`, as dragged out of Mail or Outlook) is a card marked **EMAIL**, named by its subject and sender, with **Open** and **Download**. **Open** shows it in the viewer: subject, From/To/Cc/Date, the body (HTML sanitized, no tracking pictures) and its attachments as buttons that download them. Search and find (⌘F) read the email's words. A web page saved whole (`.mht`) is a card marked **WEB PAGE**, named by its title; Open shows the page with its own saved pictures, and nothing of it is fetched from the web.
- `[[...]]` containing exactly a note or file UUID is always a link, even when the note has a matching `[[...]]` scoped wrapper tag (for example `[[@LaTeX]]`); other `[[...]]` text is formatted by that wrapper, and links nested inside it still render.
- A UUID can resolve to:
  - a note
  - a file attachment

## Rendering Rules
- **View mode**:
  - Note targets:
    - **Embeds.** A note whose only content is an embed holds it: it shows the source in place, tinted grey (light `#e4e7eb`; dark `#202224`), drawn exactly as the main tree draws notes: the same boxes, indent, spacing and ▾/▸ arrows. An embed inside an embed (a note in the source that is itself only a reference) is a shade deeper (`#d5dade`, then `#c6ccd2`; dark `#2a2d30`, `#35393d`).
    - The holder folds as its source: its ▾/▸ collapses or expands the source everywhere (the original in the tree and every other embed of it), and its own children with it. When the source is folded anywhere, the holder shows folded. Undo reverts both. Folded, the holder shows its embed, still an embed, with the source folded to its first line, in its own formatting. Only the `!` decides whether a reference is an embed or a link, folded or not. An embed always starts a line of its own: a note reading `Snack: ![[UUID]]` has a ▾/▸ and folds to `Snack:`; a note starting with an embed folds to that embed, with its source folded. A folded note is always one line, ending with … when too long, embeds on it included.
    - Each note inside an embed shows the collapse saved for it, with its own ▾/▸ where it can collapse; pressing it folds that note everywhere. A note being edited is saved and left first. Full screen and floating windows show no embed arrows.
    - The holder's own children (indented under it in the tree) show after the source's children, as notes of the level around the holder (white in the main tree). They belong to the holder, not the source: the source knows nothing of them, and they cannot be moved in among the source's children.
    - An embed's reference icon, a page with an arrow coming into it (tooltip: `Go to source note`), sits at its top right and opens the source note in a temporary reference-source context.
    - **Links.** A link is underlined link text, the referenced note's first line as its folded note draws it (formulas inline, bold and italics kept, in the link's colour), followed by the same reference icon, in the line where it is written; no panel. A link to a note that holds an embed reads as that embed's source's first line. Clicking it opens the source in a temporary reference-source context.
    - when the referenced note's first visible line is an image or Excalidraw diagram, a link shows the same thumbnail the collapsed source shows (plus any text on that line) instead of `(empty note)`. AI chat citations stay text-only.
    - link previews retain first-line footnote superscripts, including markers attached from standalone footnote lines, without showing the reference bodies.
    - **Referenced by badge:** a note other notes reference shows how many at the top right of its first line, a blue number (`99+` past 99; the tooltip gives the exact count). It counts notes, not references: one note linking twice counts once. Clicking it (or Enter) opens **Referenced by**, the referring notes in tree order; × or Escape goes back. A note being edited is saved first. Not on a phone, in full screen, floating windows or exports.
    - A link that is too long for its line is cut with `…`; its icon still follows it.
    - Backlink membership and occurrence counts are cached in server memory alongside the note store. Hydration builds the index; content/accepted-tag changes, additions, deletions, and bulk-tag updates maintain affected entries. Collapse/expand and view refreshes reuse it without rescanning the vault. Lock/reset clears it; restore/reload rebuilds it. Lists preserve current tree order and derive previews only for referring notes.
    - when a link's preview is a standalone URL with a cached link title, it displays the same `title · domain` treatment as the source note instead of the raw URL. Inline/prose URLs remain raw. Quoted-text search also matches cached titles of URLs in a note (`docs/ui/search-semantics.md`).
    - right-click anywhere inside a rendered reference and choose **Go to Source Note** to open that source note with the same navigation behavior.
    - An embed is a window onto its source: it can change how the source is shown (collapse), never what it says. Text, tags, to-do status and children are changed in the source (its reference icon). Clicking anywhere in an embed edits the holder (its `[[UUID]]` shows). A `@todo` / `@done` checkbox inside an embed shows the status but is not a control: pressing it does nothing (it neither toggles nor edits the holder; a note being edited stays edited).
  - File targets:
    - non-image files render a file card/link row with a badge naming the file's own type and the file title: its extension (`.CSS`, `.JS`, `.RTF`, `.PDF`, `.MP4`; `.markdown` as `.MD`) whatever MIME type the browser sent, and its kind (`FILE`, `DRAW`) only when it has no extension of up to four letters or digits (the maintainer, 2026-11-02: `TXT` for a `.css` and `FILE` for an `.rtf` were "very nonspecific"; `_format_file_badge`).
    - embedded image files (`![[UUID]]`) render an authenticated image preview with a `download image` control beneath it; the picture shows at its own size, never larger, up to the card's width (520 px), so a small icon is not stretched (the maintainer, 2026-11-02; `scripts/browser-image-size-regressions.mjs`).
    - right-clicking the rendered image preview also offers image actions (`Copy Image`, `Save Image`, `Rename File…`, `Zoom Image`, `Open Image in New Tab`).
    - **Rename File…**: right-click a file card (first item), a picture stored as a file (after `Save Image`) or a diagram (after `Save Diagram File`). The new name shows on every card for that file, search finds it, and downloads use it. The extension is fixed beside the field and can't change; a blank name can't be used; characters a file name can't hold (`/ \ : * ? " < > |`) become `-`. Nothing else about the file changes. ⌘Z doesn't undo a rename: rename it back.
    - link-mode image files (`[[UUID]]`) keep the generic compact file card/link row.
    - embedded Excalidraw diagrams (`.excalidraw` files, badge `DRAW`) render their stored light or dark SVG preview; double-click or right-click **Edit Diagram** to open the full-screen editor. See `docs/ui/excalidraw.md`.
    - clicking the rendered file reference's badge (`.MD`) or its underlined name downloads the decrypted file from the server; hovering them shows the tooltip "Click to download <file name>". Clicking beside the name edits the note, and dragging from there moves it, like anywhere else on a note.
    - when the host note is collapsed, non-image file references stay visible as a single compact row showing the badge and a truncated title.
    - when the host note is collapsed and the first visible line is an embedded image file or diagram, the note collapses to a compact thumbnail-only version of that preview.
  - Rendered references have no embed/link controls: a reference is an embed or a link by where it is (alone in its note, or with other content).
  - Opening a source (the reference icon or a link) opens a reference view: a temporary search context whose internal UUID query stays hidden. The search input fades out and a gray chip grows in, centered in the bar (`Source note`, with the source's first line as its tooltip; `Reference` for one AI citation; `All references` for an AI answer's Open all references), and the list slides left; coming back slides right. A magnifier where the input began starts a new search.
- **Edit mode**:
  - Note/file tokens remain literal raw text (`[[UUID]]`, or `![[UUID]]` for a file shown as its picture).
  - Saved-file image actions are not available from the raw token; they are available once the token renders as an image preview in view mode.

## File Attachment Workflow
- `Attach File…` in the command palette opens the native file picker.
- If you are editing a note, the selected file is uploaded and its `![[UUID]]` token is inserted into that note.
- If no note is active, the app creates a new note first, then inserts the file reference there.
- Drag/drop follows the same attachment path for non-image files.
  - Dropping onto the actively edited note inserts into that note.
  - Dropping anywhere else creates a new top note first, then inserts there.
  - Dropping files on a virtual folder in the folder tree (the folder highlights while dragging over it): the same new top note, put in that folder, and not left open for editing. On the tree's top `/`, in no folder.
  - A folder dropped from the desktop, alone, opens Import on "Any folder" with that folder chosen; its import folder starts as the folder's name, under the virtual folder it was dropped on (`Projects/Photos`). The browser lists its files first; after the checklist only the ticked files are copied to MetaList (a "Copying your files" step), into a holding place outside the vault that cancelling or importing removes. An interrupted copy starts over.
  - A folder dropped with anything else (files, or another folder) brings nothing in: "Drop a folder on its own."
  - A dropped `.txt` asks **Note** (the default; Enter) or **File**: Note makes a note at the top with its text (on a tree folder, filed there), File the usual card; Cancel or Esc brings nothing in. Several `.txt` dropped together are asked once, one note each in the order dropped.
  - A dropped `.md` (with any `.txt` dropped with it) opens Import at its Markdown screen, the file already copied: Turn into notes (Split, Write as) or Keep as files, then Import. On a tree folder, the notes go into that folder. Whatever is dropped and imported (a `.md`, a folder, a bookmarks file) gets the tags of the search context it was dropped in, as a note made there does, and shows at the top of that context, which stays as it is: no new search context opens.
  - Text files dropped with other files: the other files come in at once, then the text files ask.
  - Text files dropped into the note being edited ask Note or File too: Note puts their text where they were dropped, File their cards.
- Dropping a `.txt`, `.md`, `.csv` or `.json` file, a code file (`.py`, `.js`, `.sh`, `.sql`, `.yaml` and more) or a web page (`.html`) also copies its text into a new child note under the note holding its pill, shown expanded: note data beside the file data, so search finds the text. Markdown is tagged `@markdown`, CSV `@csv`, JSON `@json` and code `@code=<language>`, so they render as formatted text, a table, pretty-printed JSON and highlighted code. A web page's child shows the page without its scripts and styles. A PDF gets no child note. The child is the last child, one per file in drop order. It is an ordinary note: edit or delete it freely (deleting it removes its note data); the stored file is unchanged and clicking the pill still downloads it. Files over 200 KB or not in UTF-8, and a web page with nothing to show, get only the pill, with a banner saying why. `Attach File…` adds no child.
- A PDF's, Word document's (`.docx`) or RTF's text is read for search and find (⌘F) in the background, a floating card in the lower left showing it as it goes ("Reading document text: 3 of 7", then above its bar the time so far at the left and about how long is left at the right); it waits for an import to finish and never slows MetaList down. A restart goes on with the files not read yet, older ones included. When MetaList gets a better way to read a kind of file, every file of that kind is read again by itself.
- A Word document (`.docx`), an older Word document (`.doc`, Word 97-2003) or an RTF opens in the viewer from its card's **Open**: a `.docx`'s headings, bold, italics, lists, tables, links, footnotes and pictures (never its fonts, colours or page layout); a `.doc`'s text, paragraph by paragraph, with its headers, footers and footnotes (no formatting or pictures); an RTF's paragraphs, bold and italics. In the viewer all three show bold, italics, underline, strikethrough and highlights in Word's colours, and their text can be selected and copied. Their words are found by search and find (⌘F). `.pages` files keep **Download** only.
- Preview notes keep up with MetaList: when it gets a better way to make a kind of file's preview, every preview of that kind nobody has edited is made again in place (a card in the lower left says "Updating previews"); an edited preview stays as written, and a deleted one never comes back. A Word or RTF file imported before Word and RTF previews existed gets its preview at the next start.
- A PDF gets no child note; its text is searchable instead. A quoted search (`"rent is due"`) finds a note by words inside the PDFs it shows, and a line or two of the PDF's text shows under the card with the words marked. A new PDF becomes searchable a few seconds after it arrives (its text is read in the background); a scanned PDF, or one that is damaged or locked with a password, is found by its name only. Search covers a PDF's first ~2,000 pages (5 MB of text). The text is stored encrypted with the file; the AI can find notes by it but never reads it.
- Named image files dropped or pasted into the editor prompt for one of two paths:
  - `Paste Inline`: embed the image into note HTML as compressed `data:image/...`.
  - `Save as File`: upload the original file without recompression and insert its `![[UUID]]` token.
- Pasting a named image while no note is active uses the same prompt and creates the destination note at the top.
- Clipboard image-pixel paste with no meaningful source filename keeps the direct inline embed path by default.
- The attach flow saves the note immediately after insertion so the new reference survives refresh/reload.
- `Add Excalidraw Diagram` attaches a new, empty `.excalidraw` file the same way and opens the diagram editor.
- Files live in a sibling SQLite database derived from the main DB path (`*.files.db`).
- Attachments are immutable except Excalidraw diagrams, which the diagram editor replaces in place.
- Startup only loads the file UUID registry into memory; file metadata/blob rows are decrypted on demand for rendering/download.

## Failure / Safety Cases
- Missing or deleted UUID: render a "missing reference" marker (subtly red-tinted).
- Circular chain (A -> B -> A): render a "circular reference" marker and stop recursion at that point.
- Removing every note reference to a file does not delete the file automatically.
- `Trim Unused Files…` is the explicit cleanup path for unreferenced file rows.

## Keyboard Workflow
- `Cmd/Ctrl + C` with no text selection copies a note (server clipboard + system clipboard payload).
- A reference to the copied note: type `[[` (or `![[` for an embed) and press Enter; the copied note is the first suggestion. For a note that embeds it: add a note, type `![[`, press Enter.
- `Cmd/Ctrl + R` and `Shift + Cmd/Ctrl + R` do nothing (they pasted references until 2026-10-26); MetaList keeps `Cmd/Ctrl + R` from reloading the page.

- Deleting or cutting a note that other notes reference (link or embed, to it or to any note under it, from outside it) asks first: *"N other notes reference this note. Delete it anyway? Their references will show as missing."* (or *Cut*). A note being edited is saved and left before the dialog shows (interaction principle 6); Cancel leaves it in place, Delete or Cut goes ahead, and one undo brings it back with its references working. An unreferenced note is deleted or cut at once.

## Search Semantics
- Embeds (`![[UUID]]`) contribute non-meta tags from the source and its complete descendant subtree, including further embeds within that subtree. A link (`[[UUID]]`) contributes no tags: if note A links to note B tagged X, a search for X doesn't find A (since 2026-10-31). Tags inherited from ancestors above the source are excluded. The host retains tags inherited from its own parents, and its children inherit the host's effective tags normally. Accepted and proposed tags remain separate until combined for search.
- Required and excluded tag searches, tag suggestions, inherited-tag metadata, and Untagged Notes use these effective tags. Example: a source tagged `foo`, an embed of it, and a child beneath that embed all match `foo` and are excluded by `-foo`.
- For `foo → bar → baz`, embedding `bar` matches tags on `bar` and `baz`, without inheriting tags from `foo`. Searching for a tag on `baz` shows the reference host, and an expanded embed displays `bar → baz`. Canonical notes retain ordinary ancestor-tag inheritance; link-mode references retain compact rendering.
- References do not import source text for quoted-text searches, meta tags, or tag-bar comments. Ontology implications and text matchers still run per note after inheritance.
- Reference chains propagate transitively within each referenced subtree boundary. Cycles are valid; removing tags or references recomputes the affected dependency closure from direct tags so cycles cannot retain stale tags. Explicit references to ancestors contribute their subtrees normally. Missing/file targets, self-references, and formatting scopes do not supply note tags.
- Hydration caches effective tags in the note store/search index. Edits, bulk tag changes, moves, deletion, and restoration update the affected references and descendants; collapse and view refreshes reuse the cached tags.
- UUID link-click behavior:
  - The temporary source search context searches for the referenced UUID internally while leaving the search input visually empty.
  - Temporary reference mode is registered before activating the search context, so even nested reference navigation never briefly exposes an inherited UUID query in the search field.
  - Following again from a reference view adds a level, and the chip gains a `←` (tooltip `Back`). `←`, or Escape outside editing and dialogs, goes back one level; `×` (tooltip `Back to your search`) goes straight back to the original search from any depth, closing every reference view; both return to the exact scroll position. Following a reference to a view already open on the way back to the search (A → B, then a link back to A) goes back to that view instead of opening another one, closing the ones after it; a link to the view shown does nothing. A later AI reference replaces the AI references shown; the same ones clicked again do nothing. Reference views are kept with the search contexts on the server, so reloads and other windows show them; a search context is never named by a note ID. With Reduce Motion the slide is a quick fade; with Animated Transitions off nothing moves.
  - Typing in the search input dismisses reference-source mode and keeps the temporary search context as a normal one.
  - Opening, replacing, or returning from reference views applies note changes immediately, without note appearance/disappearance or collapse animations.
  - Target note is included.
  - Target ancestors are included.
  - Target descendants are included (not redacted).
  - Non-matching sibling branches in visible context are redacted via normal search rules.

## Related Docs
- `docs/ui/content-formatting.md`
- `docs/ui/command-palette.md`
- `docs/ui/controls.md`
- `docs/ui/search-semantics.md`
- `docs/design/differential-view-protocol.md`

## Excalidraw Diagrams
- Add one with **Add Excalidraw Diagram** in the right-click menu of the note being edited, or `Add Excalidraw Diagram` in the command palette. The diagram is attached as a `.excalidraw` file and referenced with `![[UUID]]`; the editor opens immediately.
- In view mode a diagram shows as a picture for the current light or dark theme. Double-click it, or right-click it and choose **Edit Diagram**, to open the full-screen editor. A single click anywhere on it edits its note, a moment later (so a double-click can still open the editor), and dragging from it moves the note.
- Right-click a diagram for **Make Bigger**, **Make Smaller**, **Reset Size**, **Zoom Diagram**, and **Save Diagram File**. Size uses the same `@size` tag as images.
- In edit mode the note shows only the raw `![[UUID]]` token.
- The editor autosaves 2 seconds after drawing stops. **Done** or `Cmd/Ctrl+Enter` saves and closes; `Escape` belongs to Excalidraw and does not close the editor. **Discard Changes** (click twice) restores the diagram as it was when the editor opened.
- Each editing session is one undo step: `Cmd/Ctrl+Z` in the main view restores the diagram as it was before the session. A newly added diagram undoes together with its insertion, so one undo removes it. Undo inside the editor is Excalidraw's own.
- Text inside diagrams is not searchable, not used for tags, and not visible to AI.
