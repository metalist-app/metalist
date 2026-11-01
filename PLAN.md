# PLAN: Obsidian import, developer version (build step 2)

Step 2 of `docs/ready-to-build/import-export-launch.md`. It follows that plan's §2 and the
feature map in `docs/ready-to-build/obsidian-mapping.md` (★ rows). Goal: prove the import is
right against real vaults before any polish. The polished flow (§3a), Logseq and the export
come later.

## What the developer version is

- **In every environment** (the maintainer, 2026-10-31; it was first only in development).
  Until the polished flow, anyone given a release gets this developer version.
- **Plain controls:**
  - "Import Obsidian vault…" in the command palette opens a small dialog, into the vault in
    use. Creating a vault offers the same import into the new vault (slice 1b).
  - **Folder:** pick the vault with the operating system's folder dialog (the backup
    picker's, with its own prompt).
  - **Split mode and content:** two plain choices (§2.2), live from slice 4 on.
  - **Import,** then the report.
- **Server-side,** reading the folder on this machine. It never writes to the folder.

## How it is built

- **Code:** a package `app/services/obsidian_import/`:
  - **Vault reader:** walks the files; skips `.obsidian/`, `.trash/` and hidden folders.
  - **Frontmatter reader.**
  - **Markdown block splitter.**
  - **Link resolver:** Obsidian's rule, relative to the source first, then any path ending
    in the name, then aliases.
  - **Tag maker:** the tag bar's rules applied on the server, since the server checks only
    a few (mapping A4).
  - **Note builder and report writer.**
- **Two passes:** first plan every note and give it an id, then resolve links to those ids,
  then write. Nothing is written until the whole vault is parsed, so a parse error writes
  nothing.
- **Writing:** one request transaction for all notes, through the batched path the undo of a
  delete uses (`apply_restore_records` → `store.restore_subtree`). It takes each note's own
  created and updated times and builds the search index once.
- **Attachments:** go through `file_storage.create_file`, which commits in the files
  database separately. They are stored only after the notes are planned. If writing the
  notes then fails, the stored files are unused, and Trim Unused Files removes them.
- **Order:** new root notes go at the top of the list, in the vault's order (path,
  case-insensitive, as Obsidian's file list sorts by name). The report note goes first.
- **Content:** sanitized by `sanitize_note_html` like anything pasted. Links never fetch.
- **Source tag** (the maintainer, 2026-10-31): every imported root note and the report note
  get the ordinary tag `imported:source=obsidian:at=2026-10-31T14:05` (the import's date and
  time). Searching `imported` finds every import of any kind, `imported:source=obsidian`
  every Obsidian one, and `imported:at=2026-10-31T14:05` one import. A `-` in front hides
  them: an excluded note takes its children with it (checked in a throwaway, 2026-10-31). It
  is not an `@` tag, since `@` tags are not inherited; the user can remove it like any tag.
- **Undo:** not undoable in the developer version. Searching `imported:at=…` finds one
  import's notes, to delete them; the report lists them too.
- **Fixture:** a synthetic vault of our own in `tests/fixtures/obsidian-vault/`, covering
  §7's edge cases. Obsidian's Help vault is tried by hand, kept outside the repo (no
  license).

## Slices, each with its own early look and sample vault

### Slice 1: files in, as Markdown, with a report
**Built 2026-10-31** (checkpoint `a8135b8b`).
1. The command palette has "Import Obsidian vault…" (first only in development; since
   2026-10-31 in production too).
2. Importing a vault makes one root note per `.md` file, wherever it sits. `.obsidian/`,
   `.trash/` and hidden folders are skipped, and so are other files (until slice 2).
3. A note's first line is its file name without `.md`. A first heading that repeats the name
   is that title, not a second line.
4. A file in `Projects/Client A/` gets the tag `Projects/Client-A`: the folder path, spaces as
   dashes, characters the tag bar forbids removed. Files at the vault's top get none. No
   folder or container notes.
5. Frontmatter `tags` become tags. `created`/`updated` set the note's times; otherwise the
   file's times are used.
5a. Every imported root note and the report note carry
   `imported:source=obsidian:at=<date and time of the import>`. Searching
   `imported:source=obsidian` shows every imported note, children included, and
   `-imported:source=obsidian` hides them all.
6. The content is the file's Markdown, tagged `@markdown` ("No splitting", "Markdown" for now).
   Obsidian's single-Return line breaks are written as standard breaks (open question 2),
   unless the vault turns strict line breaks on.
7. A report note, "Import report — Obsidian — <vault> — <date>", comes first. It holds counts,
   skipped files and folders, renamed tags (original → MetaList) and the direction label
   ("one-way").
8. The vault folder is unchanged afterwards (every file byte for byte, every time).
9. An empty file, a name with forbidden characters, a 300-character name, and two files with
   the same name in different folders all import.

### Slice 1b: offered when a vault is created (the maintainer, 2026-10-31)
Importing works into the vault in use (slice 1) and also when a new vault is made, the
onboarding idea of §3a brought forward.
1. The Create Vault dialog has a choice "Import an Obsidian vault into it".
2. With it chosen, Create and Open Vault opens the new vault as usual, and the import dialog
   is already open there, ready to pick the Obsidian folder. Cancelling it leaves an empty vault.
3. The import runs in the new vault, never in the one the dialog was opened from.
4. Without the choice, creating a vault is unchanged.

### Slice 1c: a plain Markdown folder (the maintainer, 2026-10-31)
The same importer, offered as its own option, for a folder of Markdown files from any app.
1. The command palette also has "Import Markdown folder…", and creating a
   vault offers it too.
2. Files, folders, frontmatter, times and the report work as for an Obsidian vault. The
   notes are tagged `imported:source=markdown:at=…`, and the report is titled "Import report
   — Markdown — <folder> — <date>".
3. Line breaks stay as written: plain Markdown already uses standard breaks, so no backslash
   is added (only an Obsidian vault without strict line breaks gets them).
4. Obsidian-only syntax found in such a folder (`[[links]]`, `%%comments%%`) is handled as
   for Obsidian once slice 2 is built.

### Slice 2: links, embeds and attachments
**Built 2026-10-31** (`app/services/obsidian_import/links.py`, `resolve.py`). Settled while
building it: links are tokens while each file is planned and become `[[UUID]]` once every
note has its id; a note is found as Obsidian finds it (the path from the vault's top or the
linking file's folder, then the shortest path ending with it, then an alias); block IDs are
hidden and kept as anchors of the note holding them; a link to a heading kept whole reads
"Note > Heading"; a file over the attachment limit is left out and listed, its links kept
as written. Not yet: `|300` doesn't size a picture (MetaList keeps the text only).
1. `[[Note]]`, `[[Note|alias]]`, `[[Folder/Note]]` and `[text](Note%20Name.md)` become links to
   the right note (`[[UUID]]`, `[[UUID|alias]]`). Frontmatter `aliases` resolve too.
2. `![[Note]]` becomes an embed of that note.
3. `![[photo.png]]`, `![[photo.png|300]]` and `![alt](images/photo.png)` store the image as a
   file and embed it. `|300` stays as the embed's text (mapping E3★).
4. `[[report.pdf]]` stores the file and links to it.
5. A link to a missing note stays as text, listed in the report with the note it's in.
6. Heading and block links (`[[Note#Budget]]`, `[[Note#^abc]]`) point at the whole note and
   are listed in the report.
7. Attachments no note references are not imported; the report lists them.
8. Canvas, Base and `.excalidraw.md` files are stored as files, listed in the report.

### Slice 3: properties and tags
1. An inline `#meeting` stays in the text and adds the tag `meeting` to its note. `#a/b`
   becomes the tag `a/b`. `#` inside code, URLs and headings is no tag (mapping G1, G2, G6).
2. Other frontmatter keys become tag values: `title: A New Hope` gives
   `title="A New Hope"`; a list repeats the value; numbers, booleans and dates are written
   as they are (C4–C8).
3. A key that can't be a tag value (nested YAML, a link in a property, an empty value) is
   left out and listed in the report.
4. Every tag the import writes passes the tag bar's own rules. Anything renamed is listed.
5. A daily note named `2026-10-30.md` also gets `@datetime=2026-10-30` (B6).

### Slice 4: split modes and rich text
**Built 2026-10-31** (`app/services/obsidian_import/blocks.py`, `content.py`, `tree.py`). Settled
while building it: tasks are MetaList tasks (`@todo`, `@done`) in either content, since an
`@markdown` note can't show a task box; a list right after a heading gives the heading
`@bullets`/`@numbered` only when the list is all its section holds; No splitting as rich text
is one note, tasks there shown as ☐ and ☑; the import report comes in split and written as
chosen. Also built alongside it: `Delete Notes (Current View)…` (`docs/ui/command-palette.md`).
1. The dialog offers the split modes: No splitting, Headings and lists, and Headings, lists
   and paragraphs (the default). It also offers the content: Rich text (the default) or
   Markdown.
2. **Headings, lists and paragraphs:**
   - Every paragraph is a note.
   - A heading is a note with its section under it; a deeper heading goes under the nearest
     higher one.
   - A list goes under the paragraph or heading before it, which gets `@bullets` or
     `@numbered`; nested items are deeper notes.
3. **Headings and lists:** the same, but a run of paragraphs stays in one note.
4. **Rich text:**
   - Bold, italic, strike, highlight, inline code and links become MetaList's own HTML.
   - Tables become tables.
   - A quote or callout becomes an `@quote` note (a `((@quote))` region in a note holding
     more), a callout's title in bold (H19).
   - A fenced code block becomes its own note `@code=<language>`; Mermaid becomes `@mermaid`.
   - `$$…$$` becomes an `@LaTeX` note, and inline `$…$` a scoped LaTeX region.
   - Footnotes become MetaList's footnotes.
5. `- [ ]` / `- [x]` items become notes tagged `@todo` / `@done`.
6. In the split modes, `[[Note#Heading]]` and block links point at that heading's or
   paragraph's note.

### `@quote`: a style tag for quotes (the maintainer, 2026-10-31)
**Built 2026-10-31**, callouts included (`docs/ui/content-formatting.md`). Check 4's Markdown
export comes with the export.
A quote as Markdown means it: a block with a bar at its left. Like `@heading`, it keeps
imported notes in MetaList's own formatting, so the export stays clean.
1. A note tagged `@quote` shows its text as a Markdown quote does: indented, a grey bar at
   its left, in light and dark themes. Its children and its tag bar are unchanged.
2. Folded, an `@quote` note shows its first line with the bar.
3. `((@quote))` in the tag bar (or `[[@quote]]`, `{{@quote}}`, any depth) makes each matching
   region a quote. A region on lines of its own is a quote block there; a region mid-line
   breaks out onto lines of its own, the text before and after it on lines of their own
   (as an embed amid text does). The brackets hide in view mode and show while editing.
4. The HTML export and printing show it as the list does. The Markdown export (not built
   yet) writes each line with `> `.
5. **Import:** a quote that becomes a note of its own is its text tagged `@quote`; a quote
   inside a note holding more (No splitting, or a run of paragraphs under Headings and lists)
   is a `((…))` region with `((@quote))`. A quote holding a list or several paragraphs keeps
   them inside its note.
6. **Callouts:** `@quote` too, its first line the type and title in bold
   (`**Note: A callout**`) (agreed 2026-10-31).
7. The tag docs and the AI help skills list `@quote` with the other style tags.

## Decisions (the maintainer, 2026-10-31, approving this plan)

1. **YAML:** add PyYAML and use only its safe loader.
2. **Line breaks in Markdown content:** Obsidian's single-Return breaks become a backslash at
   the line's end (unless the vault turns strict line breaks on).
3. **`%%comments%%` and block IDs (`^abc`):** comments are kept as text, block IDs removed;
   the report lists both (until mapping rows H13 and F1 are decided).
4. **The same vault imported twice:** imported again; the report says it was imported before.
5. **The source tag:** `imported:source=obsidian:at=<date and time>`, without the vault's name
   (the report note names it).
6. **Slice order:** 1 → 4 → 2 → 1b → 1c → 3 (1c added, and the import choices of slice 4 brought forward after trying slice 1, by the maintainer, 2026-10-31).
