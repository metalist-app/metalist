# Obsidian ⇄ MetaList: every feature, both directions, and where it loses

**Status:** Draft for review (2026-10-30). No code is written against it yet. Decisions marked **Open** are the maintainer's.

**Goal changed 2026-10-30 (the maintainer):** the export is **standard Markdown**, not an Obsidian vault, and nothing has to round-trip (`import-export-launch.md`, top and §6). **And (2026-10-30): the import makes normal MetaList.** Obsidian content becomes MetaList's ordinary HTML content in MetaList's structure, not Markdown kept for its own sake; where an option below keeps Obsidian syntax only so the export could write it back, the MetaList-natural option wins. So this page is now the **import** mapping: what each Obsidian feature becomes in MetaList and what the import loses. The **Back out** column below was written for an Obsidian round trip and no longer applies: the export writes standard Markdown from MetaList's own notes (§6 of the plan), whatever their origin. Sections K, L and M are superseded; section N lists what is still open.

**Sources:**
- **Obsidian:** its official help (`obsidianmd/obsidian-help`, commit 4aa30a3, 2026-10-28; pages at `https://help.obsidian.md/…`), the JSON Canvas spec, the plugin API typings, and each community plugin's own docs. *Unverified* marks what those don't settle; check it against a real vault.
- **MetaList:** read in the code on 2026-10-30, with file references.

**How to read the tables:**
- **Into MetaList** lists the options; ★ marks the one proposed.
- **Back out** is what the export writes.
- **Loss** is one of:
  - **None:** comes back the same.
  - **Form:** same meaning, written differently, for example `__bold__` comes back as `**bold**`.
  - **Lossy:** something is lost; the import report says what.
  - **Kept as file:** not converted, but stored as an attachment and written back unchanged.

The **split modes** are the three import choices in `import-export-launch.md` §2.2:
1. **No splitting:** one `@markdown` note per file.
2. **Headings and lists:** headings and list items become notes.
3. **Headings, lists and paragraphs** (the default): every paragraph is a note too.

Where a row differs by mode, it says so.

---

## A. Findings that change the plan

Each was confirmed in the code.

1. **Links and embeds break inside `@markdown` notes.** **Fixed 2026-10-31** (step 1b; `docs/ui/content-formatting.md`), except in a `((@markdown))` region inside another note.
   - Why: references are drawn into the note's HTML first (`embedded_references.py:375`). The `@markdown` renderer then strips every HTML tag and renders the plain text (`structured_note_renderers.py:130`, `_extract_plain_text`).
   - Effect: in an `@markdown` note, `[[UUID]]` shows the target's title as plain text, not a link, and `![[UUID]]` shows nothing.
   - **"No splitting" as planned would lose every link and embed on screen.**
   - Mitigation: make `@markdown` notes keep references. Carry the tokens through the Markdown pass as placeholders, the way scoped regions already are (`content-formatting.md`, "Any other scoped region in a Markdown note"), and draw them after. **Open:** build that first, or drop "No splitting".
2. **MetaList's Markdown renderer is its own, and narrower than Obsidian's** (`markdown_rendering.py`, no library). Inside an `@markdown` note:
   - **Shown:** headings, paragraphs, bold, italic, strikethrough, inline code, backtick fences, blockquotes, lists, tables, rules, links, math, Mermaid.
   - **Shown wrongly:** ~~nested lists come out flat~~ (fixed 2026-10-31); ~~`![alt](src)` images show as `!` plus a link~~ (fixed 2026-10-31 for web addresses; a vault's own image paths are the import's to turn into file embeds).
   - **Shown as literal text:** ~~`- [ ]` tasks~~ (clickable boxes since 2026-10-31), `==highlight==`, footnotes, callouts, `%%comments%%`, `~~~` fences, setext headings, reference-style links, raw HTML (except `<br>`).
   - This only matters for "No splitting". The split modes convert to MetaList's own formats, which don't go through this renderer.
3. **A note has one renderer, and it overrides everything else** (`content_formatting.py:534-659`, 1212). For example, `@todo @markdown` shows no checkbox. Mixing formats in one note fails.
   - So the split modes convert content to **rich text** (MetaList's HTML) rather than tagging notes `@markdown`.
   - Inline math and other formats go in scoped regions (`(((@LaTeX)))`), which work inside rich text.
4. **The server doesn't check tag syntax.** On save it only normalizes Unicode and drops invisible characters (`tag_characters.py`). The browser rejects the rest: forbidden characters, unknown `@` tags, a super tag written twice, a bad `@datetime` (`tag-syntax-service.js:38-111`). **The importer writes on the server, so it must apply the tag bar's rules itself.** Otherwise it creates tags the tag bar would refuse.
5. **Images can each have their own size.** `docs/future-plans/obsidian-import-export.md` says otherwise.
   - A wrapper with `{@size=1.25}` sizes one image (`image_size_formatting.py:94-112`), and any positive factor works.
   - An inline `<img width="300">` keeps its pixel width (the sanitizer allows `width`).
   - A file embed `![[UUID]]` takes only a factor, not pixels (row E3).
6. **Notes can't be created with a given time through the app**, only through the database layer. `notes_sql.insert_note` takes `created_at`/`updated_at`, and `convert-from-legacy.py` already uses it. The importer goes through that layer.
7. **Inside a note, MetaList has no anchors.** A reference points at a whole note (`[[UUID#…]]` stays literal text). The split modes make this mostly moot, since a heading or paragraph *is* a note. Under "No splitting", heading and block links fall back to the whole note (the after-launch "links into part of a note" idea, `import-export-launch.md` §8).

---

## B. Vault, files and folders

| # | Obsidian | Into MetaList | Back out | Loss |
|---|---|---|---|---|
| B1 | A `.md` file | ★ A root note. Its first line is the file name; the rest comes in by the split mode | One `.md` file per root note | None |
| B2 | The file name as title | ★ The first line, as plain text. If the file starts with a heading that repeats the name, that heading becomes the title line instead of a second one | File name from the first line (`import-export-launch.md` §6.2) | **Form** when the name had characters MetaList dropped; the original name is kept for export (B9) |
| B3 | Folder `Projects/Client A/` | ★ The folder tag `Projects/Client-A` (decided, §2.1). No folder notes | The file goes back into the folder, under its original name | **None**, given B9 |
| B4 | Files at the vault's top | No folder tag | Top of the export | None |
| B5 | Created / modified times (from the file system) | ★ `created_at` / `updated_at` through the database layer (A6) | The zip entry's modified time. Creation time can't be set portably | **Lossy:** the created time doesn't come back as a file time. Mitigation: also write a `created` property (F) when the file had none |
| B6 | Daily notes (`2026-10-30.md`, maybe in `YYYY/MM/` folders) | ★ An ordinary file, plus `@datetime=2026-10-30` on the root (a name matching a date). Folder tags as usual | Same name and folder | None. `@datetime` is removed on export when it only came from the name |
| B7 | Template folder (`{{title}}`, `{{date}}` placeholders) | Options: (a) ★ import as ordinary notes, placeholders as text, with the folder tag; (b) skip the template folder | As imported | None, with (a) |
| B8 | `.obsidian/` (settings, themes, plugins, workspace) | ★ Not imported. Read only for the settings listed in row B10 | Not written | **Lossy, by design:** the report says it's left out |
| B9 | Original names (a file name or folder name MetaList had to change) | ★ Kept in an **import record**: original path, heading level, block ID, link style, per note (section M) | The export restores them | None |
| B10 | Vault settings: new link format, `[[wikilinks]]` on/off, attachment folder, strict line breaks | ★ Read from `.obsidian/app.json` if present. *Unverified:* the docs don't name its keys; check them in a real vault. Used to resolve links and decide line breaks | The export writes links in the same style | **Form** if unreadable: defaults to shortest-path wikilinks |
| B11 | `.trash/`, sync conflict copies `… (Conflicted copy …).md` | ★ `.trash/` skipped. Conflict copies imported as ordinary files, and the report names them | — | Reported |
| B12 | Several config folders (`.obsidian-mobile`) | Skipped, like B8 | — | — |

---

## C. Properties (frontmatter)

MetaList has **tag values** (`name=value`, which may repeat) and **super tags** (`tag:prop=value`). Neither allows spaces, lists or nesting in a value.

| # | Obsidian | Into MetaList | Back out | Loss |
|---|---|---|---|---|
| C1 | `tags: [a, b]`, or a single string (1.9.3+) | ★ Tags `a b` on the root note | `tags:` list | None. A single string comes back as a one-item list (**Form**) |
| C2 | `aliases: [AI, Artificial Intelligence]` | MetaList has no note aliases. Options: (a) ★ use them to resolve links at import, and keep them in the import record for export; (b) also as tag values `alias=AI` (spaces become dashes); (c) as a tag-bar comment `/* aliases: AI, Artificial Intelligence */`, which is searchable | `aliases:` from the record | None for export. **Lossy in MetaList:** you can't link to a note by an alias. With (c) they're at least searchable |
| C3 | `cssclasses` | ★ Kept in the import record only | Written back | None for export. No effect in MetaList |
| C4 | Text `title: A New Hope` | Options: (a) ★ tag value `title=A-New-Hope`, with the original in the import record; (b) a tag-bar comment `/* title: A New Hope */` | From the record, or dashes back to spaces | **Form** with the record. Without it, dashes stay dashes (**Lossy**) |
| C5 | List `authors: [Le Guin, Tolkien]` | ★ Repeated tag values `authors=Le-Guin authors=Tolkien` | List | Same as C4 |
| C6 | Number `year: 1977` | ★ Tag value `year=1977`; MetaList reads it as a number | `year: 1977` | None |
| C7 | Checkbox `favorite: true` / empty | ★ `favorite=true` / `favorite=false`. An empty value is kept in the record | `true`/`false` | None. Empty comes back empty through the record |
| C8 | Date `date: 2020-08-21`, date-time `2020-08-21T10:30:00` | ★ Tag value `date=2020-08-21`; MetaList reads it as a date. A key named `created` also sets the note's created time | Same | None. Seconds are dropped if MetaList's date-time parser takes only `HH:MM` (**check**) |
| C9 | A link in a property `"[[Episode IV]]"` | No place for a reference in a tag. Options: (a) ★ the record keeps the link, the tag value holds the title with dashes, and the link resolves at export; (b) add a `[[UUID]]` line at the top of the content | Quoted wikilink | **Lossy in MetaList:** not clickable. Export is exact |
| C10 | Nested YAML, objects | ★ Kept whole in the import record; the report lists it | Written back | None for export. Invisible in MetaList |
| C11 | Property types (vault-wide; `types.json`, *unverified*) | ★ Read if present and kept with the import | Written back | None |
| C12 | Publish keys (`publish`, `permalink`, `description`, `image`, `cover`) | Like C4–C8 | Same | Same |
| C13 | Legacy `tag:`, `alias:`, `cssclass:` (dropped by Obsidian 1.9) | ★ Read as their current names | Written as the current names | **Form** |
| C14 | Dataview inline fields `Key:: value`, `[key:: value]`, `(key:: value)` in the body | ★ Kept as text in the content. A whole-line `Key:: value` *also* becomes a tag value `key=value`, so it's searchable | As written | None (the text is kept) |

---

## D. Links

| # | Obsidian | Into MetaList | Back out | Loss |
|---|---|---|---|---|
| D1 | `[[Note]]` | ★ `[[UUID]]` | `[[Note]]`, in the vault's link style (B10) | None |
| D2 | `[[Note\|alias]]` | ★ `[[UUID\|alias]]` | `[[Note\|alias]]` | None |
| D3 | `[[Folder/Note]]`, relative paths | ★ Resolved by Obsidian's rule (relative to the source first, then any path ending that way; *unverified*: the exact order and case-sensitivity). The record keeps the written form | The written form, from the record | None |
| D4 | `[[Note#Heading]]`, `[[Note#H1#H2]]` | Split modes: ★ `[[UUID of the heading note]]`, exact. No splitting: `[[UUID of the file]]` (A7) | `[[Note#Heading]]`, rebuilt from the heading note's file and text | None in split modes. **Lossy** under no splitting (lands at the top) |
| D5 | `[[#Heading]]` in the same note | Same as D4 | `[[#Heading]]` | Same |
| D6 | `[[Note#^blockid]]` | Split modes: ★ the paragraph's or list item's note. No splitting: the whole note | `[[Note#^blockid]]`, with the ID kept (E8) | Same as D4 |
| D7 | Markdown `[text](Note.md)`, `[text](My%20Note.md#Details)` | ★ `[[UUID\|text]]`; the record keeps the Markdown form | Markdown form, from the record | None. **Form** if the record is lost |
| D8 | Reference-style `[google]` + `[google]: https://…` | ★ An ordinary link where it's used | Inline link | **Form** |
| D9 | `[[Missing note]]` (not yet created) | Options: (a) ★ literal text `[[Missing note]]`, which MetaList shows as text, listed in the report; (b) create an empty note and link it | As written | None with (a) |
| D10 | External `[text](https://…)`, bare URLs | ★ A rich-text link | As written | None |
| D11 | `obsidian://open?…` | The sanitizer drops the scheme. Options: (a) ★ resolve it to `[[UUID]]` when it names a file in this vault, else keep it as text; (b) allow the scheme | As written, from the record | None for in-vault links |
| D12 | PDF selection `[[x.pdf#page=1&selection=…\|label]]` | ★ `[[UUID\|label]]` to the file; the subpath is kept in the record | As written | **Lossy in MetaList:** it opens the file, not the page |
| D13 | Links inside Mermaid (`class A internal-link`) | Kept as diagram text | As written | Inert in MetaList |
| D14 | `[[## heading search]]`, `[[^^block]]` (unfinished typing) | Literal text | As written | None |

---

## E. Embeds and attachments

| # | Obsidian | Into MetaList | Back out | Loss |
|---|---|---|---|---|
| E1 | `![[Note]]` | ★ `![[UUID]]`: the note with its children, drawn in place | `![[Note]]` | None. In MetaList it shows the subtree, as Obsidian shows the note |
| E2 | `![[Note#Heading]]`, `![[Note#^block]]` | Split modes: ★ `![[UUID of that part]]`. No splitting: the whole note | As written | None in split modes. **Lossy** under no splitting |
| E3 | `![[photo.png\|300]]`, `\|100x145` | Options: (a) ★ file plus `![[UUID\|300]]` (the embed's text is kept but unused today), shown at full width, with the size coming back exactly; then make MetaList read `\|300` as a width; (b) convert to a `{@size=…}` factor of the note width, which is approximate | `![[photo.png\|300]]` | None with (a). Today it shows **unsized** until the follow-up is built |
| E4 | `![alt\|300](url)`, `![alt](local.png)` | ★ A local file becomes a file plus `![[UUID]]`. A remote image becomes a rich-text `<img src width>` (shown through the image proxy) | Markdown image | **Form** (it may come back as `![[ ]]`; the record keeps the form) |
| E5 | `![[x.png#interface]]` (help-vault styling hook) | ★ As E3, with the subpath in the record | As written | None |
| E6 | PDF `![[doc.pdf#page=3&height=400]]` | ★ File plus `![[UUID]]` (a file card, no viewer); the subpath is kept | As written | **Lossy in MetaList:** no PDF viewer or page. Export is exact |
| E7 | Audio / video `![[a.ogg]]`, `![[v.mp4]]` | ★ File plus `![[UUID]]` (a card that downloads) | As written | **Lossy in MetaList:** no player |
| E8 | Other attachments (`[[report.xlsx]]`) | ★ File plus `[[UUID]]` | As written | None |
| E9 | Attachment folder and file names | ★ Files keep their original names. The folder isn't recreated in MetaList, but the record keeps the path | Same path as in the vault (not a flat `attachments/` folder, unlike plan §6.5) | None. **Open:** an imported vault goes back to its own attachment layout; a vault built in MetaList uses `attachments/` |
| E10 | `<iframe>` web pages, YouTube `![](https://youtube…)` | The sanitizer drops iframes. ★ Keep the URL as a link and the original HTML in the record | As written | **Lossy in MetaList:** a link, not a player |
| E11 | Canvas `![[x.canvas]]`, the `.canvas` file | ★ Stored as a file (JSON), embed shows a card | The file as it was | **Kept as file**. Its paths to notes still work if notes keep their file paths (B9) |
| E12 | Base `![[x.base]]`, `.base` files, `base` code blocks | ★ Stored as a file / kept as a code block (`@code=yaml`) | As it was | **Kept as file**. No views in MetaList |
| E13 | `query` code blocks (embedded search) | Options: (a) ★ kept as code text, reported; (b) translate to a MetaList search link (syntax differs a lot) | As it was | **Kept as text**. Inert |

---

## F. Block IDs and headings

| # | Obsidian | Into MetaList | Back out | Loss |
|---|---|---|---|---|
| F1 | `text ^37066d` at a paragraph's end; `^id` on its own line after a list, quote, callout or table | ★ Removed from the text; the ID goes in the import record for the note it names (split modes), or the file's note (no splitting) | Written back where it was | None |
| F2 | Headings `#`–`######` | Split modes: ★ a note whose content is an `<h1>`–`<h6>` element (kept by the sanitizer), so the level survives, with its section under it. No splitting: kept in the Markdown | `## Heading` | None |
| F3 | Setext headings (`===`/`---` underline; *unverified* in Obsidian) | As F2 | ATX `#` | **Form** |
| F4 | A heading containing `# \| ^ : %% [[ ]]` | ★ As written | The heading as written. Links to it use Obsidian's stripped form (`stripHeadingForLink`) | None |

---

## G. Tags in the text

| # | Obsidian | Into MetaList | Back out | Loss |
|---|---|---|---|---|
| G1 | Inline `#meeting` | Options: (a) ★ keep `#meeting` in the text **and** add the tag `meeting` to the note it's in: the paragraph's note in split modes, the file's note in no splitting; (b) move it from the text to the tag bar | (a): the text is written as is, with no duplicate in `tags:` | None with (a). In split modes the tag lands on the exact paragraph, finer than Obsidian |
| G2 | Nested `#inbox/to-read` | ★ The plain tag `inbox/to-read` (decided: no rule `inbox/to-read => inbox`) | As written | **Lossy in MetaList:** searching `inbox` doesn't find `inbox/to-read`, though the search suggests it (decided) |
| G3 | Unicode and emoji tags, `#y1984` | ★ As written (Unicode tags, built 2026-10-30). `#1984` is no tag in Obsidian and stays text | As written | None |
| G4 | Case: Obsidian ignores it and shows the first-seen spelling | MetaList ignores case too and keeps each note's spelling | Each note's spelling | None |
| G5 | A tag with characters MetaList forbids (`, ; ~ * …`) | Obsidian forbids most of them too. ★ Anything left over is dropped, and the report lists each rename (A4) | The original name, from the record | None |
| G6 | `#` inside code, URLs, headings (`# Title` is a heading) | ★ Not tags (match Obsidian; *unverified* edge cases: what may precede `#`) | — | — |

---

## H. Blocks and formatting

Split modes convert to rich text (A3). "No splitting" keeps the Markdown, and is subject to A1 and A2.

| # | Obsidian | Into MetaList (split modes) | Back out | Loss |
|---|---|---|---|---|
| H1 | Paragraph | ★ Mode 3: a note per paragraph. Mode 2: consecutive paragraphs in one note, separated by blank lines | Paragraphs | None |
| H2 | A line break inside a paragraph (two spaces, or a single newline, depending on the strict line-breaks setting, B10) | ★ `<br>` | A newline, or two spaces then a newline, matching the vault's setting | **Form** |
| H3 | `**bold**`/`__bold__`, `*it*`/`_it_`, `***both***` | ★ `<strong>`, `<em>` | `**`, `*` | **Form** (`__`/`_` come back as `**`/`*`) |
| H4 | `~~strike~~`, `<s>`, `<u>` | ★ `<s>`, `<u>` | `~~x~~`, `<u>x</u>` | None |
| H5 | `==highlight==` | ★ `<mark>` | `==x==` | None |
| H6 | `==🔴colored==` | ★ `<mark>` with the emoji kept as text | `==🔴x==` | None. MetaList shows one highlight colour with the emoji in it |
| H7 | Inline code | ★ `<code>` | `` `x` `` | None |
| H8 | Fenced code with language (backticks or `~~~`, nested fences) | ★ Its own note tagged `@code=<lang>`, or `@markdown`/`@mermaid`/`@json`… when MetaList has a renderer for it. No language means `@code=text` | A fence with the language | **Form:** `~~~` comes back as backticks; indented code comes back fenced |
| H9 | Blockquote `>` | ★ `<blockquote>` | `> …` | None |
| H10 | Horizontal rule | ★ A note containing `<hr>`. Mode 2: inside the text | `---` | **Form** (`***` comes back as `---`) |
| H11 | Escapes `\*`, `1\.` | ★ The literal character | Escaped again where needed | None |
| H12 | HTML in notes (`<span style>`, `<div class>`, `<details>`) | ★ Through the sanitizer: `<u>`, `<s>`, `<mark>`, `<sub>`, `<sup>`, `<details>` survive. Colours, classes, `style` other than a few properties, and iframes are dropped. The original is kept in the record | The original, from the record | **Lossy in MetaList** (looks); export is exact |
| H13 | Comments `%%inline%%`, `%%` block, `<!-- -->` | MetaList has no hidden text. Options: (a) ★ keep the comment as a child note tagged `obsidian-comment` and collapsed, so it's hidden until opened; (b) keep it in the record only, invisible in MetaList; (c) visible text with a grey scoped style | `%%…%%` where it was | None for export. With (a) it's findable and out of the way |
| H14 | Math `$…$` | ★ A scoped region `(((…)))` with `(((@LaTeX)))` in the tag bar; works in rich text | `$…$` | None. Note: Obsidian's rules for when `$` opens math are *unverified* (`$5 and $10`) |
| H15 | Math `$$…$$` | ★ Its own note tagged `@LaTeX` | `$$…$$` | None |
| H16 | Mermaid fence | ★ Its own note tagged `@mermaid` | A `mermaid` fence | None |
| H17 | Tables (alignment `:--:`, links and embeds in cells, `\|` escaped) | ★ A rich-text `<table>`; links and embeds as references | GFM table | **Lossy:** alignment is dropped (the sanitizer allows no `text-align`). Mitigation: allow `align`/`text-align` on table cells |
| H18 | Footnotes `[^1]` + `[^1]: …`, inline `^[…]` | ★ MetaList's footnotes: `{{@footnote}}` in the tag bar and `text{{the note}}` in place (scoped) | `^[…]` inline, or `[^n]` with definitions, from the record | **Form** without the record (named footnotes become numbered). Multi-paragraph footnotes: **check** that MetaList's footnote holds line breaks |
| H19 | Callout `> [!warning]- Title` with body | **Decided 2026-10-30:** plain HTML, like any pasted content: `<blockquote><strong>Warning: Title</strong><br>body</blockquote>`; a folded one (`-`) as `<details><summary><strong>Warning: Title</strong></summary>body</details>` (*check* how MetaList shows `<details>`). No tags, notes or emoji table. Colours aren't kept: the sanitizer drops `color` and `background`, as for any pasted page | An ordinary Markdown quote | **Lossy:** no coloured box or icon. The type survives as the word in the title |
| H20 | Nested callouts | As H19, nested as children | Nested | Same |
| H21 | Slides (`---` separating slides) | ★ As H10 | `---` | None |

---

## I. Lists and tasks

| # | Obsidian | Into MetaList (split modes) | Back out | Loss |
|---|---|---|---|---|
| I1 | Bullets `-`, `*`, `+` | ★ The paragraph or heading before the list gets `@bullets`; the items are its children | `- item` | **Form** (`*` and `+` come back as `-`) |
| I2 | Numbered `1.`, `1)`, a start number | ★ `@numbered`; the start number goes in the record | `1.`, with the start from the record | **Form** (`1)` comes back as `1.`) |
| I3 | Nested lists, tabs or spaces | ★ Deeper children | Tabs or 4 spaces, matching the vault's indent setting (B10) | None |
| I4 | A list item with more paragraphs | ★ The item's note holds them (mode 2), or they become its children (mode 3) | Indented continuation | None |
| I5 | Task `- [ ]` / `- [x]` | ★ The item's note tagged `@todo` / `@done`, with a clickable checkbox | `- [ ]` / `- [x]` | None |
| I6 | Other statuses `- [?]`, `- [-]`, `- [>]` (all count as done) | ★ `@done` plus `task=?` (the character; one a tag can't hold, such as `>`, goes in the import record) | `- [?]` | None |
| I7 | A task with a renderer (code, math) in its line | `@todo` and the renderer can't share a note (A3): the code goes into a child note | Rebuilt as one item | **Form** |
| I8 | Tasks plugin emoji (`📅 2026-11-01 ⏫ 🔁 every day`), Dataview `[due:: …]` | ★ Kept as text. `📅 date` *also* becomes `due=2026-11-01`, so it's searchable | As written | None |
| I9 | List items with a block ID | F1 | F1 | None |
| I10 | A list item whose only content is a link or embed | ★ A note holding the reference (MetaList's "holder") | As written | None |

---

## J. Plugin formats

| # | Obsidian | Into MetaList | Back out | Loss |
|---|---|---|---|---|
| J1 | Dataview query blocks (`dataview`, `dataviewjs`), inline `` `= expr` `` | ★ Kept as code text (`@code=text`), reported | As written | **Kept as text**. Inert |
| J2 | Tasks plugin `tasks` query blocks | Same | Same | Same |
| J3 | Templater `<% … %>` | ★ Kept as text (mostly in templates) | As written | None |
| J4 | Excalidraw `.excalidraw.md` (Markdown, then `## Text Elements`, then `## Drawing` as compressed JSON) | Options: (a) ★ a MetaList Excalidraw diagram from the decompressed scene, so it's editable, plus the original file in the record; (b) stored as a file. Embed fragments (`#^area=`, `\|100x100\|left`) go in the record | (a): the original `.excalidraw.md` if the drawing didn't change; if it did, the plugin format rebuilt (**check** the plugin accepts it) or a plain `.excalidraw` file | **Open:** what export writes after an edit in MetaList |
| J5 | Legacy `.excalidraw` JSON | ★ A MetaList diagram (same format) | `.excalidraw` | None |
| J6 | Other plugins' data and syntax | Text and files as found | As found | Reported |

---

## K. MetaList → Obsidian for things that never came from Obsidian

These rows are from `import-export-launch.md` §6, repeated so this page has every lossy spot.

| # | MetaList | Back out | Loss |
|---|---|---|---|
| K1 | A note tree built in MetaList | One file per root note, flat (no folders invented). Children per §6.3: under `@bullets`/`@numbered` a list, otherwise paragraphs; long children embedded from their own files | **Form** |
| K2 | Meta tags (`@red`, `@bold` on a whole note, `@size`, `@copyable`…) | Not written (§6.4). `@highlight` becomes `==…==`; `@heading` a heading; `@code=x` a fence; `@todo`/`@done` a task | **Lossy:** colours and styling (Obsidian has none without CSS) |
| K3 | Inherited and proposed tags, collapse state | Not written (§6.4) | **Lossy** (the backup keeps them) |
| K4 | Super tags `jogging:miles=3` | Properties `jogging-miles: 3`? **Open:** how a super tag's properties are named in frontmatter | **Open** |
| K5 | Ontology rules | `MetaList rules.md` (§6.4) | Readable, not active |
| K6 | Reminders | Not written | **Lossy** |
| K7 | Credentials `@password` | Plan §9 item 1 (open) | **Open** |
| K8 | References with a whole subtree (`![[UUID]]`) | `![[Root/Child]]` (§6.5) | None |

---

## L. Round trip at a glance

**Exact, with the import record (M):** files, folders, names, times except creation, every link and embed form, headings, block IDs, tags, properties (including lists, links and nested YAML), callouts, comments, footnotes, tasks with any status, tables except alignment, math, Mermaid, code, attachments, Canvas, Bases.

**Form changes only:** `__`/`_` emphasis, `*`/`+` bullets, `1)` numbering, `~~~` fences, setext headings, reference-style links, `***` rules, single-string tags.

**Lossy:**
- **In MetaList** (export is still exact): note aliases, links in properties, nested tags, PDF pages, audio and video players, iframes, callout looks, coloured highlights, HTML styling, sized images (until E3's follow-up), hidden comments (shown as collapsed notes), and query, Dataview and Bases views.
- **Both ways:**
  - Table alignment, unless the sanitizer is extended.
  - File creation times as file times.
  - Under "No splitting": heading and block links land on the whole note, and on screen it hits A1 and A2.

**Not written by the export:** MetaList-only styling, collapse state, inherited and proposed tags, reminders.

---

## M. The import record (needed for most of the above)

Most "None" results above depend on remembering what Markdown can't hold. Per imported note, it would store:
- the original path
- the kind of block: file, heading with its level, paragraph, list item with its marker and start number, callout with its type and fold
- block IDs
- link forms
- the original frontmatter (including nested YAML, link properties, property types)
- original names
- subpaths of embeds and links
- comments' original text

Options:
- **(a) ★ A table in the notes database,** encrypted like note fields, keyed by note id. It's a schema change: a version bump and a migration (`AGENTS.md`). It survives backups, and the export reads it.
- **(b) Hidden tags or comments on each note.** No schema change, but they clutter the tag bar and are fragile when the user edits.
- **(c) Kept only for the export run,** never stored. Then an export later loses everything above.

**Open:** (a) is what makes "round-trip" honest. It's the after-launch `.metalist/` sidecar's in-database twin, and it also makes the export after an edit exact for everything the user didn't change.

## N. Decisions for the maintainer

1. ~~A1~~ **Decided 2026-10-30:** make `@markdown` notes keep links and embeds, before the import (build step 1b). The other renderer gaps (A2: nested lists, `![alt](src)` images, `- [ ]` tasks, `==highlight==`, footnotes, callouts) are planned fixes too; until each is built, the import report lists it under "No splitting".
2. ~~M, the import record~~ **Dropped 2026-10-30:** with no round-trip promise there is nothing to remember for the export, and a vault built in MetaList could never have such a record anyway. MetaList adds nothing just to mirror Obsidian.

Still open, for the import only (what MetaList keeps of each, and what the import report says is lost):

3. **Obsidian syntax with no MetaList counterpart** (callouts are decided, H19: plain HTML; still open: comments H13, block IDs F1, aliases C2, nested YAML and `cssclasses` C3/C10, table alignment H17, embed subpaths and image widths E3/E6): kept as text in the note (a callout as Markdown in an `@markdown` note, an image's `|300` in the embed's text), or dropped and reported.
4. ~~Property values with spaces~~ **Decided 2026-10-30 (C4–C5):** quoted tag values (`author="Ursula Le Guin"`), built 2026-10-31 (`docs/design/tag-properties.md`, Quoted values). This replaced the first answer, dashes (`author=Ursula-Le-Guin`), which lose information (`Jean-Paul Sartre` and `Jean Paul Sartre` would both become `Jean-Paul-Sartre`).
5. **Excalidraw** (J4): import an `.excalidraw.md` drawing as an editable MetaList diagram, or keep it as a file.
