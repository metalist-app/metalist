# Import and export at launch: Obsidian and Logseq in, Obsidian-compatible Markdown out

**Status:** Agreed with the maintainer 2026-10-27. Ready to build except the items in §9, which are open: ask before deciding them. Large: two importers, one exporter, an import report.

**Two phases** (the maintainer, 2026-10-30), so decisions about how it works and how it looks are never made at the same time:
1. **A plain developer version first,** to prove the import works: shown only when MetaList runs in development (`METALIST_ENVIRONMENT=development`, as the AI cost display is), with plain controls: pick a vault folder with the existing folder picker (the backup dialog's), pick a split mode, import, read the report. Tried against real public Obsidian vaults. No polish, no animation.
2. **The polished flow (§3a) later,** once the import is right.

**Build order** (the maintainer, 2026-10-30), each step with its own early look:
1. Unicode tags (§"Found when filed"). **Built 2026-10-30;** documented in `docs/ui/tag-bar.md` (Whitespace + Tokens).
2. Obsidian import, developer version.
3. Obsidian export, developer version.
4. Obsidian import, polished flow (§3a).
5. Obsidian export, polished flow.
6. Logseq import, developer version.
7. Logseq import, polished flow.

The export comes before any polish because a problem found in it may change how the import works, and that feedback should come early. The developer versions are tried against Obsidian's Help vault (`obsidianmd/obsidian-help`), kept outside the repo: it has no license (checked 2026-10-30), so it is never committed; the committed fixtures are our own synthetic vault (§7).

**Relation to existing docs:** extends `docs/future-plans/obsidian-import-export.md` (the link and embed mapping, aliases, and the image-size question). Keep that mapping; this note adds everything around it. §8 lists work that is agreed for **after** launch, so that nothing here is built in a way that blocks it.

Written from a read-only look at the repo. Every code reference was checked on 2026-10-27, but check again before relying on one. Facts about Obsidian and Logseq not checked against their current documentation are marked *verify*.

## Found when filed (2026-10-28)

Filed from `docs/inbox/2026-10-27-import-export-launch.md`.

- **References hold:** `backup_service.py`, `html_export.py`, `app/security/rendered_html.py`, `app/upload_limits.py`, `is_password_note` (`content_formatting.py`), `strip_latex_source_attributes` (`markdown_rendering.py`), and "Tag search" in `docs/design/ontology-rules-v1.md` all exist. Nothing in `app/` imports or exports Obsidian or Logseq (the only mention is a word list in the vendored zxcvbn).
- **Tags are ASCII only** (`docs/ui/tag-bar.md`, Whitespace + Tokens): printable ASCII, without `: , " \ > < [ ] { } ( ) * | ; ~` and backtick, and never starting with `-`, `+` or `/`. A folder or tag named `Café` or `日記` loses those characters, possibly all of them. **Decided 2026-10-30: tags allow free Unicode,** so such names come in exactly; built first, as part of the Obsidian import (2026-10-30; `docs/ui/tag-bar.md`, Whitespace + Tokens, is now the reference). The ASCII rule has no recorded reason (tag-bar grammar, 2026-01-11) and the server's `is_valid_tag_token` never enforced it; the browser does (`isAsciiPrintable` in `tag-syntax-service.js` and `search-syntax-service.js`, `selected-text-tag-service.js`; `tag_properties.py` checks `isascii` for the property separator). Three rules come with it, so tags that look the same are the same:
  1. Every tag is stored in Unicode NFC.
  2. Control and format characters (zero-width spaces, direction marks) are rejected, and every Unicode space ends a tag like a normal space.
  3. Browser and server fold case the same way (Python and JavaScript differ on `ß` and Turkish `İ`).
  Look-alike letters across scripts (Cyrillic `а`, Latin `a`) are accepted as a known limit. Built; trying it also found that pasting into the search bar dropped property searches and pasting into the tag bar stripped `:` and `=` from tags with values (both fixed, `docs/ui/dictation-paste.md`).
- **"Spaces become dashes" is not a tag-bar rule.** In the tag bar a space ends the tag. The importer needs its own rule; dashes match how values are written (`author=Ursula-Le-Guin`).
- **The main search can't find a folder's notes by prefix** (§9 item 9): it matches tags exactly, "never a shorter prefix" (`docs/ui/search-semantics.md`, Tag Terms), so `Projects` doesn't find `Projects/Client-A`. Only the tag bar's suggestions and the ontology editor's tag search match prefixes, and both are for picking one tag.
- **MetaList has task tags:** `@todo` and `@done` are built-in meta tags (`tag-syntax-service.js`). §9 item 3's "until MetaList has tasks" doesn't hold; Logseq's `TODO`/`DONE` could map to them.
- **Tag values:** MetaList writes them as `name=value` or `tag:name=value`, with no spaces in a value, and a super tag once per note (`docs/ui/tag-bar.md`, Super Tags). `key:: value` lines and frontmatter keys with spaces in their values come in with dashes, which the report should list as approximated.
- **Notes have no title field:** a note's title is its first line. "The title comes from the file name" means the importer writes the file name as the note's first line, unless the file already starts with it as a heading.

---

## 0. Scope

**At launch:**
- **Import an Obsidian vault.** Any folder of Markdown files uses the same importer.
- **Import a Logseq graph** (the Markdown-files version).
- **One Markdown export** that opens cleanly as an Obsidian vault, with a switch to plain links for other apps. Working name: "Export as Markdown (Obsidian-compatible)."
- A direction label before every import, and an import report after it.
- The existing MetaList backup (`app/services/backup_service.py`) stays the exact, lossless copy.

**Priority:** coming *from* Obsidian and Logseq has to be as good as it can be, because that's what decides whether people switch. The export is the escape hatch: nothing lost, readable Markdown, opens in Obsidian. It does not need to come back into MetaList exactly at launch, since the backup already does that.

**Nothing exists yet:** no Obsidian or Logseq importer or exporter in `app/`. The existing exports are HTML (`app/services/html_export.py`) and the backup.

## 1. Rules for every importer

1. **Direction label before anything is written** (§4).
2. **Nothing dropped silently.** Everything not imported, or imported in a different form, is in the import report (§5).
3. **Imports never modify existing notes** and never touch the source; MetaList only reads the files it's given.
4. **Imported content is untrusted.** It goes through the same HTML sanitizer as pasted content (`app/security/rendered_html.py`). Links and embeds never trigger fetches. Attachments are stored, never executed.
5. **Runs in the user's own process**, with progress shown. No plaintext temporary files on disk: parse uploads from the request stream or memory (*verify* the parsers can). Use the existing upload limits (`app/upload_limits.py`); chunk or resume very large imports.

## 2. Obsidian vault or Markdown folder → MetaList

### 2.1 Files and folders

- **Each file becomes a root note,** wherever it sat in the vault. The title comes from the file name.
- **Folders become folder tags, never notes.** A file in `Projects/Client A/` gets the tag `Projects/Client-A`:
  - the full folder path, with `/` between levels
  - made valid the way the tag bar makes a new tag: capitalization kept, spaces become dashes, disallowed characters removed (`docs/ui/tag-bar.md`, new-tag rule)
  - the path is only the tag's name; **no ontology rules are added**
  - files at the top of the vault get no folder tag
- **No container note.** The vault is never gathered under one "Imported from Obsidian" note.
- **Remember which tags came from folders, and each folder's original name** (`Client A`, not `Client-A`), once per tag rather than on every note. The export uses this to rebuild the folders (§6.6). How it's stored is your call.

**Why:** one folder can hold hundreds of documents, each several pages long. Making it a parent note with hundreds of long children is the wrong shape. Loose root notes with nothing organizing them would be just as bad. Tags are how MetaList organizes things outside the tree, so the folder structure stays useful and searchable.

**Finding a folder's notes:** the ontology editor's tag search puts prefix matches first (`docs/design/ontology-rules-v1.md`, "Tag search"), so typing `Projects/` there lists every folder under Projects. Check whether the main search and the tag bar can find all notes under a folder prefix. If they can't, report it (§9, item 9) rather than adding rules.

### 2.2 Content of each file

- **Frontmatter:** `tags` → tags; `created` and `updated` → timestamps (else the file times); `aliases` → kept for link resolution; other keys → tag values where they fit, the rest listed in the report.
- **The person importing chooses how files are split** (decided 2026-10-30, §9 item 2), for the whole import, in the import dialog before anything is written, with a live preview of one of their own files that redraws as they switch. No threshold is guessed for them. The report names the mode used.
  1. **No splitting:** each file is one note tagged `@markdown`, its Markdown kept exactly, so the export writes it back unchanged.
  2. **Headings and lists:** headings and list items become notes, a heading's section indented under it; a run of paragraphs stays in one note.
  3. **Headings, lists and paragraphs** (the default, the MetaList way): every paragraph is a note as well, paragraphs as siblings, as below.

  Per-folder modes and a rich-text "no splitting" were considered and rejected (the maintainer, 2026-10-30).

  Every mode keeps the rest of this section: one root note per file, folder tags, `@bullets`/`@numbered` on list parents, links, the report. The Paragraphs rules:
  - **The file** becomes a root note titled with the file name; everything in the file goes under it. A first heading that repeats the file name is the title, not a note of its own.
  - **Each paragraph is a note** at its level.
  - **A list goes under the paragraph or heading just before it,** nested bullets as deeper children, in order. That note gets `@bullets` (`@numbered` for a numbered list), so its children show as the list they were.
  - **Headings become notes** with their section under them; a deeper heading nests under the nearest higher one (`###` straight after `#` goes under the `#`).
  - Example: `Intro.` / `- one` / `- two` / `Closing.` gives `Intro.` (`@bullets`) with children `one` and `two`, then `Closing.` beside `Intro.`, not under it.
- **Links and embeds:** as mapped in `docs/future-plans/obsidian-import-export.md`, including `[[Note|alias]]`. Standard `[x](y.md)` links resolve the same way. Links whose target isn't in the vault stay as text and are listed in the report.
- **Tags:** inline `#tags` and frontmatter tags → tags. **Nested tags (`#a/b`) come in as the plain tag `a/b`**, with no rule `a/b => a`, the same convention as folder tags.
- **`key:: value` lines** → tag values.
- **Attachments** that notes reference → files.
- **Not converted** (kept as attachments, listed in the report): Canvas, Bases, plugin data, Dataview queries, `.excalidraw.md` drawings (*verify* whether the scene can be extracted).

**Reference implementation:** Obsidian's official importer is open source and handles many quirks. Use it as a reference for edge cases; check its license before copying any code (*verify*).

## 3. Logseq graph (Markdown files) → MetaList

- pages → root notes
- blocks → child notes, nesting and order kept
- `tags::` → tags; other page and block properties → tag values
- `collapsed:: true` → collapsed
- `((uuid))` block references and `{{embed}}` → references and embedded references
- `journals/` → root notes titled and dated by day
- `assets/` → files
- **Kept as text and listed in the report:** queries, `TODO`/`DONE` and other task states, scheduled and deadline dates (whether they become tags is open, §9 item 3)
- **Logseq's database version** (in beta since mid-2026) is not a launch target. Its users can export a Markdown graph, *verify*.

## 3a. The import and export flow (added 2026-10-30)

**Phase 2:** not built until the developer version works (see Status).

Importing and exporting should feel slick, the way a first-run setup should: a few well-explained, illustrated, animated screens that take the person through it, not one dense dialog. MetaList has no first-run setup yet; this flow sets the pattern for one.

- **Screens, in order:** what to import (Obsidian vault or Markdown folder) with its direction label (§4); how to split files; what will be approximated, and that the source is never modified; progress; the report (§5). The export gets the same treatment (§6): options, the plaintext warning (§6.9), progress, the summary.
- **The split choice is shown, not described.** Each of the three modes (§2.2) is shown on samples exactly as the notes would look in MetaList: a built-in sample with a heading, paragraphs and a list, and one of the person's own files (one with headings and lists, picked for them; they can pick another). Switching modes animates the notes splitting apart or joining.
- **Each mode says what it's good and bad at,** in a line or two. For example, no splitting: the file comes back from export exactly, and a quoted search covers the whole document, but sections can't be folded, tagged or moved on their own. Headings, lists and paragraphs: any paragraph can be moved, tagged or linked, but a quoted search covers one paragraph.
- **Explanatory text is wanted here,** unlike the rest of MetaList's UI, which keeps text minimal and puts detail in tooltips: these are one-time decisions about a whole vault (the maintainer, 2026-10-30).

## 4. Direction labels

Every format in the import picker shows one label, repeated on the confirmation screen with one sentence of explanation, **before** anything is written:
- **Round-trip:** "You can export back to this format at any time with your notes, structure and tags intact." For: MetaList backup, Obsidian, Markdown folder.
- **One-way:** for apps MetaList can import from but not export to.
- **Logseq at launch:** one-way until a Logseq export exists (proposed, §9 item 8). The sentence would say that MetaList's Markdown export can be copied into a Logseq graph's `pages/` folder (*verify* how well Logseq reads it).

Also shown before every import: what will be approximated for that format, and that the source is never modified.

## 5. The import report

Shown at the end of every import, and also saved as a note in the vault ("Import report — Obsidian — 2026-10-27") so it can be found later:
- **Counts:** notes, children, tags, folder tags, tag values, references, files.
- **Approximated:** per category, for example "38 frontmatter keys became tag values."
- **Not imported:** with the reason and where the original is, for example "4 Canvas files: kept as attachments."
- **Unresolved links:** each one, with the note it's in.
- **Renamed tags and folders:** original → MetaList name.
- **The direction label again,** with one sentence on how to leave.

Be specific. This report is where a new user's trust starts.

**Importing the same vault twice** should be noticed ("this vault was already imported on …") and offered as "import as a copy" or "cancel," never silently duplicated (proposed: record a fingerprint of each import).

## 6. The Markdown export (Obsidian-compatible)

Delivered as a `.zip`. Unzipped, it opens directly as an Obsidian vault.

### 6.1 Layout

```
MetaList export – <vault> – <YYYY-MM-DD>/
  Marathon plan for spring.md         ← one file per root note
  Marathon plan for spring/           ← only if it has long children (6.3)
    Race-day checklist.md
  Projects/
    Client A/
      Kickoff notes.md                ← a note with the folder tag Projects/Client-A
  attachments/
    route-map.png
  MetaList rules.md                   ← readable ontology rules
```

### 6.2 One file per root note

- **File name:** the root note's first line as plain text.
  - Remove `\ / : * ? " < > | # ^ [ ]`, trim to a safe length (about 120 characters), and normalize to NFC.
  - On a collision, add ` (2)`, ` (3)`, and so on. Titles that differ only in Unicode normalization must not overwrite each other.
  - A root note with no text gets `Untitled <created date>`.
- **Frontmatter,** only when there's something to put in it: `tags`, `created`, `updated`, `metalist-id`, and tag values as properties. Keys that clash with Obsidian's reserved properties (`tags`, `aliases`, `cssclasses`) get the prefix `ml-`.
- **Body:** the root note's own content, then its children as an outline.

### 6.3 Children

- **Children of a note tagged `@bullets` or `@numbered`** are written as that list; **other children as paragraphs**. Decided 2026-10-30; the rules below for short and long children apply within that.
- **Short children** become nested list items, one tab per level (*verify* that's Obsidian's default). A short child is a single paragraph with no headings, lists, tables, code blocks, images, files or drawings, and at most `EXPORT_SHORT_CHILD_MAX_CHARS` characters. Start at 500 and tune it (§9 item 4).
- **Long children** (anything else) get their own file at `<root title>/<child title>.md`, embedded in place with `![[<root title>/<child title>]]`. Their own children go inside that file by the same rules. Each such file has its own frontmatter.
- Order is the outline order; an embed sits exactly where its child sat.

### 6.4 Tags, tag values and what isn't written

- **Explicit tags:** in frontmatter for files, inline `#tag` for list items. Obsidian tags can't contain spaces or be purely numeric (*verify*): spaces become `-`, and a numeric tag gets a prefix (for example `n2026`).
- **Tag values:** frontmatter properties for files, inline `key:: value` for list items.
- **Not written at launch:** inherited tags, suggested tags, meta tags (`@…`), and collapsed state. Markdown has no place for them, and the backup keeps them. Where a meta tag changes how content looks, the conversion handles it: `@code=python` becomes a fenced code block with that language. The export summary says that these weren't written and that the backup keeps everything.
- **Ontology rules:** written to `MetaList rules.md` in MetaList's own syntax, for people to read. Don't approximate rules with Obsidian nested tags.

### 6.5 References and attachments

- **References:** as mapped in `docs/future-plans/obsidian-import-export.md`. A reference to a root note is `[[Root title]]`, and to a promoted child `[[Root title/Child title]]`. A reference to an outline child needs an Obsidian block ID: write `^ml-<id>` **only on children something actually points at** (proposed), and link as `[[Root title#^ml-<id>]]`. A reference to a note left out of the export becomes plain text and goes in the summary.
- **Attachments:** go to `attachments/` under their original names, with ` (2)` added on a collision. Images become `![[photo.png]]`, other files `[[report.pdf]]`. Before exporting, show the size ("This export includes 3.2 GB of files") and offer a notes-only option.

### 6.6 Folders

- **A note with a folder tag** goes into that folder, under the folder's original name (§2.1), so a vault imported from Obsidian comes back with the same folders. The folder tag becomes the folder and isn't also written as an Obsidian tag.
- **Everything else is a flat list of files** at the top. Export never infers folders. For a vault built in MetaList it's hard to know which folders should exist, and ontology rules can't supply them: a tag can imply several broader tags, so the rules don't form a tree. The user can sort files into folders in Obsidian.

### 6.7 Content conversion (HTML → Markdown)

- **Converts cleanly:** paragraphs, headings, bold, italic, strikethrough, links, inline code, code blocks with language, lists, tables, blockquotes, horizontal rules.
- **Highlights** become `==text==`. Colors and font sizes are dropped and listed in the summary.
- **Math** becomes `$…$` and `$$…$$`. Check how LaTeX source is stored; `strip_latex_source_attributes` is in `app/services/markdown_rendering.py`.
- **Mermaid** becomes a fenced `mermaid` block.
- **Excalidraw** becomes a `.excalidraw` scene file in `attachments/`, plus an embedded PNG preview (format open, §9 item 5). Charts saved as attachments follow the same answer.
- **Image size:** see the open question in `docs/future-plans/obsidian-import-export.md`.
- Anything that can't be converted goes in the export summary, never silently dropped.

### 6.8 The plain Markdown switch

For apps that don't read Obsidian syntax:
- `[[wikilinks]]` become standard links: `[Title](Title.md)`, `[Title](Root/Child.md)`.
- Embeds become links. Long children stay in their own files.
- Block IDs are dropped; references to a child point at its root file.
- `==highlights==` become `**bold**`.
- Tags stay as inline `#tag`, and frontmatter stays.

### 6.9 Safety

- **The export is plaintext.** Say so before downloading: "This export is not encrypted. Anyone with the file can read it, including your passwords."
- **Password notes:** detected with `is_password_note` (`app/services/content_formatting.py`). Whether they're included by default is open (§9 item 1). Either way, offer the opposite as an option.
- **No AI** is involved in import or export, and AI exclusions don't apply: it's the user's own data going to the user.
- **No plaintext temporary files:** stream the zip straight into the response, and stream attachments from the encrypted file store into it (*verify* the zip writer can). On a personal or self-hosted install, the export can also be written to a chosen folder, as backups are.
- **Export works in every account state** and never needs MetaList to read the result.

## 7. Tests (the launch gate)

**Gate:** Obsidian and Logseq imports pass on fixture vaults in CI with nothing dropped silently: everything not imported is in the report. The Markdown export opens as an Obsidian vault with notes, tags, links and attachments intact.

**Fixtures:**
- a synthetic Obsidian vault and a synthetic Logseq graph covering everything in §2 and §3, made by us
- public example vaults (Obsidian's Help vault, for example) as reference only, not committed unless their license allows
- a large real vault, in a private test pipeline only, never committed

**Edge cases:**
- **Folders:** nested several levels; two folders with the same name in different places (`Work/Notes` and `Home/Notes`); folder names with spaces or disallowed characters; a file whose own tags include its folder's tag; files at the top of the vault.
- **Names:** titles that differ only in Unicode normalization; forbidden filename characters; very long titles; empty files; files with the same name in different folders.
- **Structure:** deep nesting (more than 10 levels); a long child inside a long child.
- **Tags and links:** tags with spaces or purely numeric names; nested tags; links to missing notes; circular references; aliases.
- **Logseq:** journals; block references to blocks on other pages; properties on pages and on blocks.

**Export check:** export the synthetic vault after importing it. Every note, tag, link and attachment is present, and folders match the original.

## 8. After launch (agreed; don't build yet, but don't block it)

- **An exact round trip through Markdown:** a hidden `.metalist/` sidecar carrying what Markdown can't hold (meta tags, suggested tags, collapsed state, original tag names, rules, file metadata, IDs), block IDs on every child, re-import that matches notes after edits in Obsidian, and round-trip CI. Keep the export's layout stable so this can be added later.
- **Export options:** also write inherited tags; one file per note.
- **A Logseq export** (pages, journals, `key:: value` properties, `collapsed::`, a minimal config so the folder opens as a graph).
- **AI-suggested folders for exporting a vault built in MetaList:** opt-in, only when AI is on. Pass 1 proposes a folder tree from the tag list with counts plus a sample of titles. Pass 2 places notes into that tree in batches, which also places untagged notes. Notes excluded from AI are never sent; they're placed by their tags. Shown as a preview before exporting.
- **Imports from Evernote (ENEX), then Notion**, both one-way.
- **Links into part of a note** (considered 2026-10-30, not ruled out; design open): MetaList links point at whole notes, so with no splitting an Obsidian heading or block link (`[[Plan#Budget]]`, `[[Plan#^abc123]]`) can only point at the whole note. Links could later be extended to point at a heading or block inside a note.

## 9. Open (ask the maintainer; don't decide)

1. **Password notes in exports:** included by default with the warning (proposed), or left out by default?
2. ~~When a Markdown file counts as outline-shaped~~ **Decided 2026-10-30:** every file becomes a tree: each paragraph, heading and list item is a note, a list sits under the paragraph or heading before it with `@bullets`/`@numbered` (§2.2). A share-of-the-file threshold was rejected as arbitrary. The person importing picks no splitting, headings and lists, or headings, lists and paragraphs (the default). Known cost of Paragraphs: a quoted text search matches within one note, so two words in different paragraphs no longer find the file together (tags are inherited, so tag searches still do). If that becomes a problem, change how text search works rather than the import (the maintainer, 2026-10-30).
3. **Logseq tasks:** do `TODO`/`DONE` and scheduled/deadline dates become tags, tag values, or plain text? Proposed: plain text, until MetaList has tasks.
4. **`EXPORT_SHORT_CHILD_MAX_CHARS`:** 500 is a guess. Tune it on a real vault so most children stay inline.
5. **Excalidraw (and charts) going to Obsidian:** a plain `.excalidraw` file plus a PNG (proposed), or the Obsidian plugin's `.excalidraw.md` format?
6. **Image sizes:** Obsidian sets a width per image; MetaList sets a size factor on the note. How close counts as close enough on import, and what does export write? (Already open in `docs/future-plans/obsidian-import-export.md`.)
7. **A note with two folder tags** (only if someone adds a second): which folder does export use?
8. **Logseq's label at launch:** one-way until a Logseq export exists (proposed), and the exact wording.
9. ~~Finding a folder's notes~~ **Decided 2026-10-30: nothing new.** The main search matches tags exactly, but typing `Projects` in the search suggests every subfolder tag (`Projects/Client-A`, ...), so it is easy to find what to type. No prefix search and no added rules.

## 10. Acceptance checks

- An Obsidian vault with folders imports with every file as a root note, each tagged with its folder path, and no folder or container notes.
- The direction label shows before anything is written. The import report lists everything not imported or approximated, and is saved as a note.
- A Logseq graph imports with pages, blocks, nesting, properties, journals and assets.
- The export opens in Obsidian as a vault: one file per root note, long children embedded, tags, tag values, links, attachments, and folders rebuilt for notes with folder tags. A vault built in MetaList comes out flat.
- The plain switch produces standard links and no block IDs.
- The plaintext warning shows before download, and no plaintext temporary files are written.
- The fixtures and edge cases in §7 pass in CI.
