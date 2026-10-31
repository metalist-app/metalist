# Import and export at launch: Obsidian and Logseq in, standard Markdown out

**Goal changed 2026-10-30 (the maintainer):** the export is **standard Markdown** that reads well in any app, not an Obsidian vault. For Obsidian and Logseq we do our best on the import and make no promise that the export preserves everything; nothing has to round-trip. People keep Markdown so their notes outlive the app, and Obsidian-only syntax breaks that promise anyway.

**Status:** Agreed with the maintainer 2026-10-27. Ready to build except the items in §9, which are open: ask before deciding them. Large: two importers, one exporter, an import report.

**Principles** (agreed 2026-10-30, filed from `docs/inbox/2026-10-30-import-export-philosophy.md`):
1. **Best-effort imports.** Obsidian and Logseq first, others maybe later. Some loss is accepted; the import report says exactly what.
2. **No MetaList features that exist only to match another app.** A feature is built only if MetaList would want it on its own.
3. **Three exits, each promised only for what it is:** standard Markdown (readable anywhere: MetaList to everything else, §6), HTML (faithful to how MetaList looks; MetaList to MetaList through its hidden data, §6.7), and the MetaList backup (the only round-trip format for a whole vault).
4. **No single "best" way: the user chooses,** in the walkthrough, on import (how files are split) and on export (for example an embed as a link or as a copy), with a default for every choice (§3a).
5. **Never invent structure.** An export is one ordered document shaped like the notes: root notes in the user's order, children nested (§6.1). No folders, no grouping rules (decided 2026-10-30).
6. **The import turns other apps' notes into normal MetaList** (the maintainer, 2026-10-30): content becomes MetaList's ordinary content (HTML, as anything pasted) in MetaList's structure, not Markdown kept for its own sake. Preserving the original files through import and export is not a goal; the export separately writes reasonable standard Markdown.

Why: the path Obsidian → MetaList → back to Obsidian is the one where the user has left, so it isn't worth special machinery. The export's job is trust before signing up, and standard Markdown gives that to everyone, including people who started in MetaList.

**Two phases** (the maintainer, 2026-10-30), so decisions about how it works and how it looks are never made at the same time:
1. **A plain developer version first,** to prove the import works: shown only when MetaList runs in development (`METALIST_ENVIRONMENT=development`, as the AI cost display is), with plain controls: pick a vault folder with the existing folder picker (the backup dialog's), pick a split mode, import, read the report. Tried against real public Obsidian vaults. No polish, no animation.
2. **The polished flow (§3a) later,** once the import is right.

**Build order** (the maintainer, 2026-10-30), each step with its own early look:
1. Unicode tags (§"Found when filed"). **Built 2026-10-30;** documented in `docs/ui/tag-bar.md` (Whitespace + Tokens).
1a. Tag values with spaces, in quotes (`author="Ursula Le Guin"`, decided 2026-10-30). **Built 2026-10-31,** with value suggestions after `=`, chained search conditions (`:foo="bar":baz>3`) and no new root note in a search no new note can match; documented in `docs/design/tag-properties.md` (Quoted values, Search). The import then writes frontmatter values with spaces quoted, not dashed; the export's hidden metadata must round-trip them, escapes included (`title="The \"Best\" Book"`).
1b. `@markdown` notes keep links and embeds (`obsidian-mapping.md` A1; decided 2026-10-30). **Links and embeds built 2026-10-31** (`docs/ui/content-formatting.md`); the A2 gaps below are next. **Nested lists built 2026-10-31** (`docs/ui/content-formatting.md`), with pasting a nested list offering Markdown. **Markdown images built 2026-10-31.** **Clickable tasks built 2026-10-31** (cases agreed first; `docs/ui/content-formatting.md`, Tasks). Their acceptance checks (2026-10-31, before the code): in an `@markdown` note (1) `![alt](https://…)` shows the image where it is written, no wider than the note, its alt text as the image's description; (2) it loads through MetaList's image proxy, as other web images in notes do; (3) a path or another scheme (`![x](photo.png)`, `![x](javascript:…)`) stays as written text; (4) links and a `!` before other text are unchanged; (5) the AI chat's replies draw no images (a reply could otherwise send data out in an image address), nor do footnotes. Their acceptance checks (2026-10-31, before the code): (1) an item indented two or more spaces (or a tab) under another is drawn inside it, to any depth, bullets and numbers mixed; (2) going back to a shallower indent continues that level's list; (3) a blank line between items, or before a nested list, keeps the list together; (4) a nested numbered list keeps its first number; (5) an item's indented continuation lines stay part of it; (6) the same lists in the AI chat's replies, which share the renderer. Acceptance checks (2026-10-31, before the code): in an `@markdown` note (1) `[[id]]` and `[[id|text]]` show as the same link a plain note shows, inside their paragraph, list item, heading or table cell; (2) `![[id]]` of a note shows the embedded note, as a block of its own between the paragraphs around it; (3) `![[id]]` of an image file shows the image; (4) the Markdown around them still renders (`**bold** [[id]] *it*`); (5) clicking a link goes where it goes in a plain note; (6) editing shows the source unchanged. Then, planned: nested lists, Markdown images, tasks, `==highlight==`, footnotes, callouts, and HTML inside Markdown (sanitized as stored notes are; today all HTML but `<br>` is escaped) in `@markdown` notes (A2). The import's Markdown content choice (§2.2) relies on them; its rich-text choice doesn't.
2. Obsidian import, developer version.
3. Markdown export, developer version.
4. Obsidian import, polished flow (§3a).
5. Markdown and HTML export, polished flow (the HTML export's cases, §6a, are built with it).
6. Logseq import, developer version.
7. Logseq import, polished flow.

The export comes before any polish because a problem found in it may change how the import works, and that feedback should come early. The developer versions are tried against Obsidian's Help vault (`obsidianmd/obsidian-help`), kept outside the repo: it has no license (checked 2026-10-30), so it is never committed; the committed fixtures are our own synthetic vault (§7).

**Feature by feature:** `docs/ready-to-build/obsidian-mapping.md` (drafted 2026-10-30, for review before step 2) maps every Obsidian feature into MetaList and back, with where it loses and the decisions that remain.

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
- **One Markdown export** in standard Markdown (CommonMark with the GitHub extensions: tables, task lists, footnotes, fenced code) and YAML frontmatter, readable in any Markdown app. It opens in Obsidian too, with working links: Obsidian reads standard links. Working name: "Export as Markdown."
- A direction label before every import, and an import report after it.
- The existing MetaList backup (`app/services/backup_service.py`) stays the exact, lossless copy.

**Priority:** coming *from* Obsidian and Logseq has to be as good as it can be, because that's what decides whether people switch. The export is the escape hatch: readable standard Markdown that any app opens. It makes no promise to preserve everything or to come back into MetaList exactly; the backup does that.

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
- ~~Remember which tags came from folders and their original names~~ **Dropped 2026-10-30:** the export no longer rebuilds folders (§6.1), so nothing needs it. Folder tags stay as tags.

**Why:** one folder can hold hundreds of documents, each several pages long. Making it a parent note with hundreds of long children is the wrong shape. Loose root notes with nothing organizing them would be just as bad. Tags are how MetaList organizes things outside the tree, so the folder structure stays useful and searchable.

**Finding a folder's notes:** the ontology editor's tag search puts prefix matches first (`docs/design/ontology-rules-v1.md`, "Tag search"), so typing `Projects/` there lists every folder under Projects. Check whether the main search and the tag bar can find all notes under a folder prefix. If they can't, report it (§9, item 9) rather than adding rules.

### 2.2 Content of each file

- **Frontmatter:** `tags` → tags; `created` and `updated` → timestamps (else the file times); `aliases` → kept for link resolution; other keys → tag values where they fit, the rest listed in the report.
- **The person importing chooses how files are split** (decided 2026-10-30, §9 item 2), for the whole import, in the import dialog before anything is written, with a live preview of one of their own files that redraws as they switch. No threshold is guessed for them. The report names the mode used.
  1. **No splitting:** each file is one note, in rich text or Markdown (the content choice below).
  2. **Headings and lists:** headings and list items become notes, a heading's section indented under it; a run of paragraphs stays in one note.
  3. **Headings, lists and paragraphs** (the default, the MetaList way): every paragraph is a note as well, paragraphs as siblings, as below.

  Per-folder modes were considered and rejected (the maintainer, 2026-10-30).

- **A second, separate choice: what the content is written in** (decided 2026-10-30). It applies to every split mode, "No splitting" included:
  1. **Rich text** (the default, the normal-MetaList way, principle 6): MetaList's ordinary HTML content, with MetaList's best HTML version of Obsidian's extras (a callout as a quote block, `==highlight==` as a highlight).
  2. **Markdown:** each note keeps standard Markdown and is tagged `@markdown`, for people who like editing in Markdown. Obsidian-only extras that Markdown has no form for are written as HTML inside the Markdown (valid Markdown). Needs links in `@markdown` notes (step 1b) and the renderer showing HTML inside Markdown (step 1b's planned fixes).

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

- **Screens, in order:** what to import (Obsidian vault or Markdown folder) with its direction label (§4); how to split files; what will be approximated, and that the source is never modified; progress; the report (§5). The export gets the same treatment (§6): options, the plaintext warning (§6.8), progress, the summary.
- **The split choice is shown, not described.** Each of the three modes (§2.2) is shown on samples exactly as the notes would look in MetaList: a built-in sample with a heading, paragraphs and a list, and one of the person's own files (one with headings and lists, picked for them; they can pick another). Switching modes animates the notes splitting apart or joining.
- **Each mode says what it's good and bad at,** in a line or two. For example, no splitting: the file comes back from export exactly, and a quoted search covers the whole document, but sections can't be folded, tagged or moved on their own. Headings, lists and paragraphs: any paragraph can be moved, tagged or linked, but a quoted search covers one paragraph.
- **Explanatory text is wanted here,** unlike the rest of MetaList's UI, which keeps text minimal and puts detail in tooltips: these are one-time decisions about a whole vault (the maintainer, 2026-10-30).
- **A question appears only if it applies** to what's imported or exported: no embeds, no embed question; no password notes, no password question; and so on (agreed 2026-10-30).
- **Every question has a default,** and an "Export with these choices" (or "Import with these choices") button is on every screen, so someone who doesn't care finishes in one click.
- **Each choice shows a small before/after preview** from the user's own notes, as the import's split choice does.
- **Onboarding:** the import walkthrough can be offered during first-time setup ("Do you have an Obsidian vault you'd like to bring in?").

## 4. Direction labels

Every format in the import picker shows one label, repeated on the confirmation screen with one sentence of explanation, **before** anything is written:
- **Round-trip:** "You can export back to this format at any time with your notes, structure and tags intact." For: the MetaList backup only.
- **One-way:** Obsidian, Markdown folders and Logseq (2026-10-30: no round-trip promise). The sentence says MetaList exports standard Markdown, so notes, text, links and files come back out, but features only that app has may not.

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

## 6. The export: one ordered document (Markdown and HTML)

**Decided 2026-10-30** (filed from `docs/inbox/2026-10-30-export-one-ordered-document.md`; replaces the earlier one-file-per-root-note layout and the folder rebuild). The export is for people who live in MetaList, not for a round trip to another app. One file per root note fails on a real vault:
- **Titles:** a vault full of one-line root notes (`Do laundry` under a to-do search) becomes thousands of three-word files.
- **Order:** files in a folder sort by name, so the user's ordering, half the point of MetaList, is lost.
- **Structure:** the outline is scattered across thousands of files.
- **No heuristic fixes it.** Splitting "short notes" from "documents", or grouping notes into collection files (by month, by tag), misfiles real notes; every such rule was rejected.

The Markdown is **standard Markdown** (decided 2026-10-30): CommonMark with the GitHub extensions most apps read (tables, task lists, footnotes, fenced code), YAML frontmatter, and standard links. No wikilinks, embeds, block IDs or other syntax only one app reads. It opens in Obsidian, VS Code, GitHub, Typora and the like.

### 6.1 One document

1. **An export is one ordered document, the same shape as the existing HTML export** (`app/services/html_export.py`, `build_notes_export_document`): root notes in the user's order, children nested under their parents. Markdown and HTML are built the same way; only the output differs.
2. **Scope, as the HTML export today:** a note and its subtree, a view (search context), or the whole vault. One file, named from the export dialog's Title (the HTML export's existing dialog and naming rule, `docs/ui/controls.md`, Export ▸).
3. **The whole vault is one large file.** Test it on a large vault (about 15,000 root notes, 107,000 notes in all) for size and time; stream it.
4. **No folders.** Folder tags stay as tags; the export never makes folders.

### 6.2 Option: one file per root note

Chosen by the user for an export whose first lines make usable titles (for example a journal where each root note starts with its date). Offered for both formats.
- **File name:** the root note's first line as plain text. Remove `\ / : * ? " < > | # ^ [ ]`, trim to a safe length (about 120 characters), and normalize to NFC. On a collision add ` (2)`, ` (3)`, and so on; titles that differ only in Unicode normalization must not overwrite each other. A root note with no text gets `Untitled <created date>`.
- **Order is not kept** (decided 2026-10-30). Files sort by name, so the order is the user's to arrange: first lines that sort as wanted (a journal whose entries start with their date), or not caring about order. That's why this is an opt-in, for exports where it works, such as a journal search. No numbering or other ordering scheme is added.

### 6.3 Markdown layout

- **Frontmatter at the top describes the export, not the notes:** the search it came from (or the note's title), the export date-time, the vault name. Nothing per note.
- **Notes as an outline:** children nested under their parent. Children of a note tagged `@bullets` or `@numbered` are written as that list (decided 2026-10-30); how other children are written is a walkthrough choice with a before/after preview (decided 2026-10-30; the set and default to confirm, §9 item 7): **Outline** (proposed default: every note a list item, nested by depth, any depth kept), **Document** (a note with children a heading for its depth, `#` to `######`, deeper levels as list items; a note without children a paragraph), or **Plain paragraphs** (one after another, nesting not shown). Standard Markdown can't indent a paragraph (four spaces make a code block), so only lists and headings show nesting.
- **Embeds** (`![[UUID]]`, a note's whole subtree shown in place): standard Markdown cannot include one file in another. A walkthrough choice, asked only if the export has embeds (§9 item 11): a link where the embed was (default), or a copy of the embedded note in each place (a note embedded in seven places gives seven copies).
- **Links** (`[[UUID]]`, `[[UUID|text]]`): to a note inside the document, an in-page link to an anchor on that note; to a note outside it, plain text, listed in the summary.
- **Attachments:** in a folder beside the document, so the export is a `.zip` when there are any and a single `.md` file when there aren't. Images become `![alt](attachments/photo.png)`, other files `[report.pdf](attachments/report.pdf)`, under their original names with ` (2)` on a collision. Before exporting, show the size ("This export includes 3.2 GB of files") and offer a notes-only option.

### 6.4 Tags and metadata: two independent choices

**Each note carries only its own explicit tags.** Nesting shows inheritance, as in MetaList; never flatten a subtree's tags onto its notes.

1. **Visible tags:** plain `#tags` at the end of each note's first line (`- Do laundry #to-do #home`), values dropped; or no tags. Proposed default: on. How tags that aren't valid `#tag` syntax in common apps are written (spaces can't occur, but `=`, `:`, a leading digit, `.`, `@` can) is **open** (§9 item 10): list the cases found when building.
2. **Hidden metadata:** an HTML comment on each note, every child included, holding what the user picks: nothing (proposed default); created and last-updated date-times; or those plus every explicit tag with its values exactly as MetaList writes them (`jogging:miles=3:duration=30`). Comments are invisible when rendered but show in a raw editor, which is why it's off by default.

- **The same two choices for the HTML export,** where the hidden data is the exchange-file data in `docs/future-plans/html-note-sharing.md`.
- **Disclosure,** consistent with that doc: when hidden metadata is included, the walkthrough says so, and the file says so visibly, for example a closing line "This file also carries tags and dates for MetaList."
- Both choices are walkthrough questions with defaults, shown with a small before/after preview, and skipped when they don't apply (§3a).
- **Not written in either case:** inherited tags (the nesting shows them), suggested tags, meta tags (`@…`, which the conversion turns into formatting, §6.6) and collapsed state. The summary says so; the backup keeps everything.
- **Ontology rules:** written to the end of the document, or as `MetaList rules.md` beside it in a `.zip`, in MetaList's own syntax, for people to read.

### 6.5 Which format is for what

- **HTML is MetaList to MetaList:** its hidden data can hold everything, so the exchange-file import can be exact. Sharing, ontology fragments and recipes ride on it (`docs/future-plans/html-note-sharing.md`).
- **Markdown is MetaList to everything else.** Re-importing MetaList's own Markdown is discouraged: build no special path for it. It goes through the ordinary Markdown importer with the one-way label (§4).

### 6.6 Content conversion

- **Converts cleanly:** paragraphs, headings, bold, italic, strikethrough, links, inline code, code blocks with language, lists, tasks (`@todo`/`@done` as `- [ ]`/`- [x]`), tables, blockquotes, horizontal rules, footnotes.
- **Highlights** become `<mark>text</mark>` (inline HTML is standard Markdown). Colors and font sizes are dropped and listed in the summary.
- **Math** becomes `$…$` and `$$…$$` (GitHub and most apps render it; elsewhere it reads as LaTeX). Check how LaTeX source is stored; `strip_latex_source_attributes` is in `app/services/markdown_rendering.py`.
- **Mermaid** becomes a fenced `mermaid` block; other renderer notes (`@code`, `@json`, `@diff`, `@shell`, `@csv` as a table) become fences or tables.
- **Excalidraw** becomes a `.excalidraw` scene file in `attachments/` plus an image of it, shown with standard image syntax (decided 2026-10-30, §9 item 5). Charts saved as attachments follow the same answer.
- **Image size:** standard Markdown has none; images are written at their natural size, and a size is listed in the summary.
- Anything that can't be converted goes in the export summary, never silently dropped.

### 6.7 The HTML export beside it

It offers the same scope, the one-file-per-root-note option (§6.2) and the two tag and metadata choices (§6.4) as the Markdown export. The HTML export exists (`app/services/html_export.py`; `docs/ui/controls.md`, Export ▸ and `View as HTML…`) and is faithful to how MetaList looks. Offer it beside the Markdown export, in the same walkthrough (agreed 2026-10-30), with these cases settled, each a choice only where it applies:
- **Links to notes inside the file:** clicking jumps there in the page. Today a link in an export is a plain `<span class="note-reference-link-static">` (`embedded_references.py`, `_render_link_text_body`), so it goes nowhere (checked 2026-10-30).
- **Links to notes outside the file:** plain text, or include the linked note (a choice, only if such links exist).
- **File attachments** (drawn today as static cards, `note-file-reference-link-static`): put them in a zip beside the HTML file and link them, or leave them out and say so (a choice, only if there are any).
- **The whole vault:** offered where the Markdown export is offered (§6.1). *Found when filed:* exporting the All Notes view with no search (`View as HTML…`) may already be the whole vault, since a view exports exactly what it shows; check before building anything.

### 6.8 Safety

- **The export is plaintext.** Say so before downloading: "This export is not encrypted. Anyone with the file can read it, including your passwords."
- **Password notes:** detected with `is_password_note` (`app/services/content_formatting.py`). Left out by default; including them is an opt-in in the walkthrough, asked only if there are any, and opting in asks "Are you sure?" with the plaintext warning (§9 item 1, decided 2026-10-30).
- **No AI** is involved in import or export, and AI exclusions don't apply: it's the user's own data going to the user.
- **No plaintext temporary files:** stream the document (or the zip) straight into the response, and stream attachments from the encrypted file store into it (*verify* the zip writer can). On a personal or self-hosted install, the export can also be written to a chosen folder, as backups are.
- **Export works in every account state** and never needs MetaList to read the result.

## 7. Tests (the launch gate)

**Gate:** Obsidian and Logseq imports pass on fixture vaults in CI with nothing dropped silently: everything not imported is in the report. The export meets §7's export checks below.

**Fixtures:**
- a synthetic Obsidian vault and a synthetic Logseq graph covering everything in §2 and §3, made by us
- public example vaults (Obsidian's Help vault, for example) as reference only, not committed unless their license allows
- a large real vault, in a private test pipeline only, never committed

**Edge cases:**
- **Folders:** nested several levels; two folders with the same name in different places (`Work/Notes` and `Home/Notes`); folder names with spaces or disallowed characters; a file whose own tags include its folder's tag; files at the top of the vault.
- **Names:** titles that differ only in Unicode normalization; forbidden filename characters; very long titles; empty files; files with the same name in different folders.
- **Structure:** deep nesting (more than 10 levels).
- **Tags and links:** tags with spaces or purely numeric names; nested tags; links to missing notes; circular references; aliases.
- **Logseq:** journals; block references to blocks on other pages; properties on pages and on blocks.

**Export checks** (2026-10-30):
1. Exporting a search with 200 one-line root notes gives one Markdown file listing them in the user's order, each with its own `#tags`.
2. A note with nested children exports with the nesting intact; a child shows only its own tags.
3. With hidden metadata set to "dates and tags", every note and child has a comment with created, updated and its tags with values; the file has the visible disclosure line. With it off, there are no comments.
4. A link to a note in the export jumps to it; a link to a note outside becomes text and is in the summary.
5. One file per root note, chosen on a journal search, gives one file per entry named from its first line.
6. The HTML export offers the same scope, per-root-note option and metadata choices.
7. The output parses as CommonMark with the GitHub extensions; a whole-vault export of a large vault completes and streams.

## 8. After launch (agreed; don't build yet, but don't block it)

- ~~An exact round trip through Markdown~~ **Dropped 2026-10-30:** the export makes no round-trip promise (see the goal at the top); the backup is the exact copy.
- **Export options:** also write inherited tags. A walkthrough choice when it's built (§3a). ("One file per root note" is now a launch option, §6.2.)
- ~~A Logseq export~~ **Dropped 2026-10-30:** the standard Markdown export is the one export.
- ~~AI-suggested folders~~ **Replaced 2026-10-30:** no AI folder feature in MetaList. Instead **the user's AI agent can do an export following the user's own instructions** ("set this up as an Obsidian vault with folders", "one file per month"), with nothing codified by MetaList. It sees only what the AI privacy settings allow (hidden notes stay in the flat list), and needs an export it can drive (which note goes in which folder, which choices) without rewriting notes. Design it when it's built.
- **Imports from Evernote (ENEX), then Notion**, both one-way.
- **Links into part of a note** (considered 2026-10-30, not ruled out; design open): MetaList links point at whole notes, so with no splitting an Obsidian heading or block link (`[[Plan#Budget]]`, `[[Plan#^abc123]]`) can only point at the whole note. Links could later be extended to point at a heading or block inside a note.

## 9. Open (ask the maintainer; don't decide)

1. ~~Password notes in exports~~ **Decided 2026-10-30:** a walkthrough choice, asked only if the export has any. **Left out by default**, as in the HTML export (whose "Include Unredacted Passwords" is unchecked). Including them is an opt-in, and opting in asks once more, "Are you sure?", with the plaintext warning.
2. ~~When a Markdown file counts as outline-shaped~~ **Decided 2026-10-30:** every file becomes a tree: each paragraph, heading and list item is a note, a list sits under the paragraph or heading before it with `@bullets`/`@numbered` (§2.2). A share-of-the-file threshold was rejected as arbitrary. The person importing picks no splitting, headings and lists, or headings, lists and paragraphs (the default). Known cost of Paragraphs: a quoted text search matches within one note, so two words in different paragraphs no longer find the file together (tags are inherited, so tag searches still do). If that becomes a problem, change how text search works rather than the import (the maintainer, 2026-10-30).
3. **Logseq tasks:** do `TODO`/`DONE` and scheduled/deadline dates become tags, tag values, or plain text? Proposed: plain text, until MetaList has tasks.
4. ~~Order in one-file-per-root-note exports~~ **Decided 2026-10-30:** not kept; files sort by name and arranging that is the user's (§6.2). (This item replaced `EXPORT_SHORT_CHILD_MAX_CHARS`, dropped with the short/long children split.)
5. ~~Excalidraw (and charts) going to Obsidian~~ **Decided 2026-10-30:** a plain `.excalidraw` file plus an image of it; no Obsidian plugin format (standard Markdown goal).
6. **Image sizes:** Obsidian sets a width per image; MetaList sets a size factor on the note. How close counts as close enough on import, and what does export write? (Already open in `docs/future-plans/obsidian-import-export.md`.)
7. **Children that aren't a list** (§6.3): a walkthrough choice (decided 2026-10-30). **Open:** confirm the set (Outline, Document, Plain paragraphs) and the default (Outline proposed). (Replaces the two-folder-tags question, dropped with folders.)
8. ~~Logseq's label at launch~~ **Decided 2026-10-30:** one-way, like Obsidian (§4); the exact wording is still to write.
9. ~~Finding a folder's notes~~ **Decided 2026-10-30: nothing new.** The main search matches tags exactly, but typing `Projects` in the search suggests every subfolder tag (`Projects/Client-A`, ...), so it is easy to find what to type. No prefix search and no added rules.
10. **Visible `#tags` that common apps don't read as tags** (§6.4): how to write tags with `=`, `:`, `.`, `@` or a leading digit; list the cases found. (Replaces super tags as frontmatter properties, dropped 2026-10-30: there is no per-note frontmatter; values go in the hidden metadata.)
11. ~~Embeds in the export~~ **Decided 2026-10-30:** a walkthrough choice, default a link (§6.3).

## 10. Acceptance checks

- An Obsidian vault with folders imports with every file as a root note, each tagged with its folder path, and no folder or container notes.
- The direction label shows before anything is written. The import report lists everything not imported or approximated, and is saved as a note.
- A Logseq graph imports with pages, blocks, nesting, properties, journals and assets.
- The export is one ordered document of standard Markdown (or HTML): root notes in the user's order, children nested, each note with its own `#tags`, in-page links, attachments beside it, the two tag and metadata choices, and one file per root note as an option (§6, §7's export checks).
- The plaintext warning shows before download, and no plaintext temporary files are written.
- The fixtures and edge cases in §7 pass in CI.
