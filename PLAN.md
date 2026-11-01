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
1. The Create Vault dialog has a checkbox "Import an Obsidian vault into it", under the
   ports, unticked, its box and words on one line, in light and dark themes.
2. Ticked, Create and Open Vault opens the new vault in its own tab as usual; once it has
   opened (after its login, if it asks for one), the Import Obsidian Vault dialog is open
   there, ready for Choose Folder.
3. The import goes into the new vault; the vault the dialog was opened from is unchanged.
4. Closing the import dialog leaves the new vault empty. Reloading the new vault doesn't
   open the dialog again (the request travels in the address as `#import-obsidian`, removed
   once read).
5. Unticked, creating a vault is unchanged.

**Built 2026-10-31** (`app/static/js/modules/import-on-open.js`). Slice 1d replaces its
checkbox with "Import from".

### Slice 1d: setting up a new vault (the maintainer, 2026-10-31)
Create Vault asks three questions, each a checkbox; the new vault opens each ticked step in
this order, the next when the one before closes, and an unticked one is skipped (all
unticked: the vault opens as today).
Acceptance checks:
- Create Vault shows, under the ports, three checkboxes in this order, unticked: "Protect it
  with a password", "Set up AI in it", "Import from". Ticking "Import from" shows a
  drop-down beside it (Obsidian vault, Markdown folder), Obsidian vault chosen.
- "Set up AI in it" ticked without a password: a line under it says "Without a password,
  the key is kept only until MetaList restarts."
- The new vault opens each ticked step's dialog in turn, the next when one closes: Add
  Password, AI Agent Settings, the import dialog for the chosen source.
- Adding the password reloads the vault and asks for the login; once logged in, the
  remaining steps go on. Closing a dialog without finishing it goes on to the next step.
- The steps travel in the address (`#setup=password+ai+import-obsidian`), each taken out as
  it starts: a reload never repeats a finished step.
- Nothing ticked: the vault opens as today.
1. **Protect it with a password:** Add Password opens first.
2. **Set up AI in it:** AI Agent Settings opens next. Ticked without a password, a line
   under it says the key is kept only until MetaList restarts (a vault without a password
   keeps keys only in the server's memory, `docs/design/ai-providers.md` §3; never in the
   browser).
3. **Import from:** ticked, a drop-down shows what can be imported (Obsidian vault; a
   Markdown folder once slice 1c is built), and its import dialog opens last.

### Slice 2b: the AI suggests tags for an import (the maintainer, 2026-10-31)
**Dropped 2026-11-01** (the maintainer: the AI has too little context, and the wait is too
long): no AI in the import at all; the new vault wizard sets an AI up and nothing more. The
notes below are kept as the record of what was built and removed.
1. With an AI set up, the import dialog has "Have the AI suggest tags" (unticked), with the
   number of notes beside it.
2. After the import, the AI suggests tags for the imported notes exactly as it does for a
   note and its children today (`docs/ui/tag-bar.md`, AI Tag Proposals): proposals, shown as
   robot counts, that search already finds; nothing is accepted for the user. A floating card
   shows how far it has got, and work goes on meanwhile.
3. New tags are allowed whatever AI Tagging Vocabulary says: a new vault holds almost no
   tags but the folder ones.
4. The import's folder tags are never proposed: a note gets its folder's tag from its file
   and any other note it would be wrong on, by definition. This is enforced in code, not
   only asked of the AI.

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
is one note, tasks there shown as ☐ and ☑; the import report comes in written as chosen, and
as one note (2026-11-01: split, it was dozens of notes the summary never counted). Also built alongside it: `Delete Notes (Current View)…` (`docs/ui/command-palette.md`).
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

## Phase 2: the setup and import wizards (the maintainer, 2026-10-31)

Creating a vault and importing into one are workflows the person walks through, and they
look slick: `import-export-launch.md` §3a, brought forward. Built before the Markdown export
(the maintainer: how these are set up will inform the exporter), and the importer is nailed
down first. They replace the developer version's dialogs (slices 1b, 1d, 2b keep working
underneath: the same import, the same steps, the same AI proposals). Slice 3 (properties and
tags) is built inside the import wizard. **To agree before any code.**

### One frame for both
- A full-window page over the list: a progress bar across the top names every step (Password,
  AI, Import, Done; or the import's own), the current one marked, finished ones ticked, so the
  person always sees how many questions there are and how far along they are.
- Going forward, the screen slides out to the left and the next comes in from the right; Back
  slides the other way. Same slide as the reference views (250 ms, the same easing); with
  Reduce Motion a quick fade (120 ms); with Animated Transitions off, no motion.
- Each screen: a title, one or two sentences of explanation (wanted here, §3a), its choices,
  and Back and the main button (Next). Every question has a default, but the person goes
  through every step: no button skips ahead (the maintainer, 2026-10-31, replacing §3a's
  "Import with these choices"). Enter is the main button; Escape asks before leaving a
  wizard half done.
- A question shows only when it applies (§3a): no AI step's tag question without an AI set
  up; no "what will be approximated" screen when nothing would be.

### The new vault wizard
Create Vault (in the vault it is opened from) asks only the name and ports, in the same frame
as its first step; the new vault opens straight into the rest.
1. **Password:** "Protect this vault with a password", ticked; unticking it folds the fields
   away (the maintainer, 2026-10-31: a checkbox, not "leave it empty to skip"). The fields:
   strength meter, "Generate Password…" opening the existing generator with "Use This
   Password". One line says what each means: notes
   encrypted; without one, the AI key is kept only until MetaList restarts. Setting it keeps
   this window logged in: no second login (the server opens a session for the window that
   set it; other windows of the vault are logged out, as today).
2. **AI:** "Set up an AI", ticked, over the providers (OpenAI, Anthropic, Google, as cards)
   and the chosen one's key, with Google's billing warning (as AI Agent Settings).
3. **Bring in your notes:** Obsidian vault, Markdown folder, or Start empty. Choosing one
   continues into the import wizard's steps, which join the progress bar.
4. **Summary ("Ready to set up your vault"):** what will happen (password, AI, and the
   import's preview when importing); its button is the green Set Up Vault.
5. **Setting up:** the last step, its progress; done, the wizard closes on the vault (no
   done screen: the maintainer, 2026-11-01).

#### Acceptance checks (wiring, 2026-11-01)
1. "Create Vault…" opens the full-window wizard on its first step, Vault: the name and the
   ports, the progress bar naming every step (Vault, Password, AI, Your notes, Summary,
   Set up). Next is greyed out until the name and ports are valid.
2. Its green "Create Vault" creates the vault and opens it in a new tab, straight into the
   wizard on Password, Vault ticked in the bar and no Back to it; the first tab's wizard
   closes.
3. Password: "Protect this vault with a password" ticked, Password and Confirm with the
   strength meter; "Generate Password…" opens the existing generator, whose "Use This
   Password" fills both fields. Next is greyed out until the password is long and strong
   enough and the two match.
4. AI: the three providers and the key; Next refuses a key that can't be one (wrong start,
   too short) on this step, saying why, before anything is saved.
5. Your notes: Obsidian, Markdown or Start empty; importing goes on through Folder, Split
   and Write as.
6. Summary lists the password, the AI and the import's preview; its button is the green
   "Set Up Vault". Nothing has changed before it.
7. Setting up, in order: the password (no login screen, ever), the AI key (kept, as the
   vault has a password), the import; then the wizard closes on the vault.
   Done leaves the vault showing the import's search context; reloading the page asks for
   no password.

### The import wizard
**Wired 2026-10-31:** "Import Notes…" in the palette runs the real import (the developer
version's two commands and dialog are gone); the summary is the server's preview
(`CmdPreviewImport`, `POST /import/preview`). From the palette, and from step 3 above.
1. **Source:** Obsidian vault or Markdown folder, each with its direction label (§4: one-way,
   and the sentence saying what comes back out).
2. **Folder:** Choose Folder…; then its name, its Markdown files and attachments counted.
   Each note is tagged with its folder and the tags written in its file (slice 3); nothing to
   choose, so no checkbox (the maintainer, 2026-10-31).
3. **Split:** the three modes shown on samples exactly as the notes would look: a built-in
   sample and one of the person's own files (one with headings and lists, picked for them;
   another can be picked). Switching modes animates the notes splitting apart or joining.
   Each mode's good and bad in a line or two (§3a).
4. **Write as:** rich text or Markdown, the choices beside a sample note that changes in
   place as Split's does: Markdown's marks slide in, the formatting falls away, the
   `@markdown` tag appears (the maintainer, 2026-10-31).
5. ~~**AI tags**~~: dropped 2026-11-01 (the maintainer): the import never mentions AI; the
   new vault wizard sets one up and does not use it on the import.
6. **Summary ("Ready to import"):** a preview of what the import will do, before anything
   is written: how many files will become how many notes, attachments and folder tags, and
   what will appear differently (comments, block IDs, callouts as `@quote`, …), each line
   "N of your … will …". Its button is the green Import.
7. **Importing:** the last step (the maintainer, 2026-10-31): its progress; done, the wizard
   closes on the imported notes, in their new search context, the report first (2026-11-01:
   no screen saying it is done, "a waste of time").

### Motion cases (interaction principles; agree before code)
Principle: only the person's action changes the screen, and the slide shows where they went.
1. Next: the screen slides left, the next one in from the right; the progress bar's mark moves
   to the next step at the same time.
2. Back: the reverse.
3. A step that does not apply is skipped: the slide goes straight to the following one, and
   the bar shows the skipped step as not part of this run.
4. Reduce Motion: a 120 ms fade in place, nothing moves. Animated Transitions off: no motion.
5. A window resized mid-slide: the slide ends where it was going; nothing is left half off
   screen.
6. The split preview: switching modes moves the sample notes between their places (splitting
   apart or joining); the screen around them stays still.

### Open
- Full window, or a large centered panel over the dimmed list? (Recommended: full window.)
- An early look as a clickable prototype first (the real frame and screens, choices not yet
  wired), so the look is agreed before the wiring? (Recommended.)

## Changed since (the maintainer, 2026-11-01)
- **No import report:** the report note is gone (slices 1, 1c and 2 below still describe it, as built then). The
  wizard's Summary says beforehand what will appear differently or be left out; Decision 4's "the report says it
  was imported before" goes with it. The files come in at the top as Obsidian's file list orders them: in each folder its
  subfolders first, then its files, each A to Z.
- **No done screen:** the import wizard closes on the imported notes; the new vault wizard on the vault.

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
