# Tables: `<br>` in cells, uneven rows, escaped pipes, column widths

**Status:** Agreed with the maintainer 2026-10-27. Small; ready to build.

Written from a read-only look at `app/services/markdown_rendering.py`, without running the code. Check every reference before relying on it; build only what's missing.

`@markdown` notes, AI chat answers and footnotes all render through `render_markdown_to_html`, so §1–§3 cover all three. §4 is CSS and applies to `@csv` tables too.

---

## 1. `<br>` renders as a line break

- A Markdown table row is one line of text, so `<br>` is the standard way to break a line inside a cell. GitHub renders it, and AI chats put it in tables all the time.
- **Today:** `_render_inline_markdown` escapes all raw HTML before inline formatting, so `<br>` shows up as the text `<br>`.
- **Change:** `<br>`, `<br/>` and `<br />`, in any case, render as a line break **anywhere inline**, table cells included. Every other tag stays escaped. Code spans and fenced code keep `<br>` as literal text.
- **Why only `<br>`:** it's common in pasted Markdown and harmless. Raw HTML in general stays off. The note HTML policy already allows `br`.
- This is a line break inside one cell. It is not a cell spanning rows; Markdown has no way to express that.

## 2. Rows with too few or too many cells

- **Today:** in `_render_table_block`, a body row whose cell count differs from the header's ends the table, and the remaining rows show as plain text.
- **Change, as in GFM:** keep the row. Fill missing cells with empty cells and drop extra ones. AI-written tables sometimes miss a cell.

## 3. Escaped pipes (proposed; confirm against the GFM spec)

- **Today:** `_split_table_row` splits on every `|`, so `a \| b` in a cell splits the row.
- **Proposed, as in GFM:** `\|` is a literal `|` inside a cell, including inside a code span in a cell. A bare `|` still separates cells, in a code span too.

## 4. Columns at least as wide as their longest word

- **Reported by a user:** in a three-column `@markdown` table, the short first column broke its header "State" into "Stat" / "e". To work around it, they padded a cell with `- -`.
- **Likely cause:** `.note-content` sets `overflow-wrap: anywhere` (in `main.css`, from the rule that text never runs out of its note), and table cells inherit it. With `anywhere`, a column's smallest width is one character, so automatic table layout squeezes short columns when other columns hold long text. `.meta-markdown th, .meta-markdown td` and `.meta-csv-table td` don't override it.
- **Change:** in Markdown and CSV table cells, use `overflow-wrap: break-word`. It still breaks a word that can't fit at all, but doesn't count letter-by-letter breaks when sizing columns, so every column is at least as wide as its longest word.
- **When the longest words can't all fit side by side** (a narrow window, or a long token in a cell), **the table scrolls sideways** instead of breaking words mid-column. This is a deliberate, small exception to "text never runs out of its note": a table broken mid-word is unreadable. Only the table scrolls, not the note.
- Applies to `@markdown` tables (headers and body cells) and `@csv` tables, in the app and in HTML export and print.

## 5. Not in scope

- No raw HTML beyond `<br>`.
- No "Markdown flavor" setting. `@markdown` aims at one flavor: CommonMark plus GFM plus the extras it already has (Mermaid, math).
- Obsidian syntax (`[[wikilinks]]`, `![[embeds]]`, `==highlight==`, `%%comments%%`) is for Obsidian import later, converted into MetaList's own references and embeds. It isn't part of `@markdown` rendering.

## 6. Tests

- `| Install | Run the script<br>then restart |` renders one cell with two lines; so do `<br/>`, `<br />` and `<BR>`.
- `` `<br>` `` in a code span, and `<br>` inside a fenced block, stay literal.
- `<b>x</b>` and `<script>` stay escaped.
- In a 3-column table, a body row with 2 cells renders with an empty third cell, and the rows after it are still in the table. A row with 4 cells renders its first 3.
- `| a \| b | c |` renders two cells, the first holding `a | b`.
- The same `<br>` table in an AI chat answer renders the same way.
- A table with headers `State | What the hardware is doing | Entry action` and long text in the last two columns: "State" stays on one line at a normal note width. Same for an `@csv` table.
- A table whose words can't all fit at a narrow width scrolls sideways inside the note; no word is broken mid-column, and the note itself doesn't scroll sideways.

## 7. Checked 2026-10-27 (filed from the inbox)

- Confirmed in `app/services/markdown_rendering.py`: `render_markdown_to_html`, `_render_table_block`, `_split_table_row` and `_render_inline_markdown`.
- Confirmed §4's cause: `.note-content` sets `overflow-wrap: anywhere` (`main.css`), and `.meta-markdown th, .meta-markdown td` and `.meta-csv-table td` don't override it.
- Not built: `<br>` in cells, uneven rows, escaped pipes, column widths.
- **Open (§3, marked proposed):** check `\|` against the GFM spec before building.
