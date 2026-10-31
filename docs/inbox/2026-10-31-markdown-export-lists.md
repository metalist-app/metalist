# Markdown export: lists and indentation (decided)

**Status:** Agreed with the maintainer 2026-10-31. Fills in how the Markdown export writes nesting (`docs/ready-to-build/import-export-launch.md` §6.3) and settles §9 item 7 (the child layouts and their default).

Written from a read-only look at the repo. Check the references before relying on them.

---

## 1. The three child layouts are the complete set

Markdown shows nesting in only two ways: lists (indentation) and headings (size). A plain paragraph can't be indented (four spaces make a code block). So the walkthrough's three choices for children that aren't `@bullets` or `@numbered` stay as planned, and there is no fourth:

1. **Outline** (bullets): every note a list item, nested by indentation, any depth. **The default.** It's the only layout that keeps any depth and reads the same in every Markdown app.
2. **Document** (headings): a note with children is a heading for its depth (`#` to `######`); a note without children is a paragraph; below six levels, Outline.
3. **Plain paragraphs:** nesting not shown.

## 2. Indentation (Outline)

- **4 spaces per level, never tabs.** CommonMark, GitHub and Obsidian accept 2–4; Python-Markdown (MkDocs) needs 4. Tabs parse as 4 but display at the editor's tab width.
- **A note's first line goes on its bullet.** The rest of that note (further paragraphs, code blocks, tables, quotes, its own lists) follows after a blank line, indented 4 deeper than the bullet. Then its children, at the same depth.
- **Indent = the larger of 4 and the marker's width.** `100. ` is five characters; with only 4 spaces its content would fall out of the item.
- **Code blocks are always fenced,** never indented.

```
- Trip to Japan
    - Book flights
    - Hotel in Kyoto

        Ask for a room facing the garden.
- Groceries
```

## 3. List markers carry meaning

| What | Marker |
|---|---|
| A note (Outline, and children of a `@bullets` note) | `-` |
| A bulleted list inside a note's own text | `*` |
| Children of a `@numbered` note | `1.` `2.` … |
| A numbered list inside a note's own text | `1)` `2)` … |

Why: otherwise a note whose text is a list looks exactly like a note with children, and note boundaries are lost unless the hidden metadata is on. CommonMark starts a new list when the bullet character or the number delimiter changes, so both render the same but stay distinct in the raw text for editors, scripts and AI tools. The export rewrites whatever marker the note's text used. The same table applies to lists inside notes in the Document and Plain-paragraph layouts.

Cost: Python-Markdown doesn't recognize `1)`; those lines show as plain text starting "1)", still readable. GitHub, VS Code and CommonMark apps handle it.

## 4. Escaping

Escape a line in a note that would read as syntax: `1990. A great year` → `1990\. A great year` (likewise `1990)` → `1990\)`); a leading `#`, `>`, `-`, `+` or `*` followed by a space; a line of `---` or `===` under text (it would make a heading).

## 5. Known costs, accepted

- One multi-paragraph note makes its whole sibling list "loose" (paragraph spacing) when rendered.
- A note's own list followed by its children renders as two adjacent lists, with a little space between.

## 6. Left to you

- Check that Obsidian renders `1)` lists; if it doesn't, say so in the plan and we'll decide.

## 7. Done when

1. Outline output parses in CommonMark (for example `commonmark` or `markdown-it`) to the same tree as the notes: every note a list item at its depth, every note's other content inside its item, at depths beyond 10.
2. A note with two paragraphs, a fenced code block and a table, three levels deep, keeps all of it inside its item.
3. A note whose text is a bulleted list, with two children: the text list uses `*`, the children `-`. Same for numbered (`1)` and `1.`).
4. A `@numbered` note with 120 children keeps item 100's content and children inside item 100.
5. Lines starting `1990.`, `# `, `> `, `- `, `+ `, `* `, and a `---` line under text, come out as text, not syntax.
6. No tabs anywhere in the output.
7. The plan's §6.3 and §9 item 7 record the layouts, the default and the markers.
