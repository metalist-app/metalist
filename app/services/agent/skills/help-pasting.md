# Pasting into notes

Use this reference to explain MetaList accurately. It describes user capabilities,
not permission or tools for you to execute every operation. You can answer and
request one supported menu/dialog opening. You cannot submit a form, change
settings, run a shell command, or mutate notes through this help response. Do not
claim that you inspected current notes or settings: none are supplied here.
Prefer user-facing steps over implementation details. If the reference does not
answer a question, say what is unknown; do not invent syntax or controls.

Sources: docs/ui/content-formatting.md

The meta tags a paste adds (`@json`, `@mermaid`, `@LaTeX`, `@code=python`, `@csv`) are
explained in the formatting help topic; dictated text in the dictation topic.

## Paste format detection
- Pasting text in an unambiguous format tags the note for it at the moment of the paste (the tag appears in the tag bar; the text renders when the note leaves editing):
  - JSON (a complete object or array) → `@json`
  - a chess FEN position → `@chess`
  - a unified diff (with `@@` section lines, `---`/`+++` headers, or `diff --git`) → `@diff`
  - Mermaid starting with a diagram keyword (`graph TD`, `sequenceDiagram`, `gantt`...) → `@mermaid`
  - a fenced code block naming its language (```` ```python ````, ```` ```mermaid ````), alone or with text around it → `@markdown` (the fence says it is Markdown; a bare ```` ``` ```` or an unclosed fence is not enough)
  - a pure LaTeX block (`$$...$$`, `\[...\]`, or `\begin{...}...\end{...}`) → `@LaTeX`
  - code copied from VS Code (two lines or more) → `@code=<its language>`, from the language VS Code puts on the clipboard (`vscode-editor-data`): `@code=python`, `@code=bash` for shell scripts, `@markdown` for Markdown files; JSON that parses stays `@json`; plain text and unlisted languages get nothing
  - cells copied from a spreadsheet (Excel, Google Sheets, Numbers: an HTML table on the clipboard) → the cells as CSV text (commas, quoting cells that hold commas, quotes or line breaks) and `@csv`
- Into an otherwise empty note (or with all of its text selected), and when pasting creates a new note, the plain tag is added. Into a note with content, the pasted text is wrapped `((...))` and `((@json))` (etc.) is added, so the existing text is untouched.
- Nothing is added at once for anything uncertain (prose, JSON-looking text that does not parse); CSV-like, Markdown-like and code-like text is offered instead (see below). Nothing is added or offered when the note already has a renderer tag, when pasting inside an existing wrapped region, or when `((...))` is already in use in that note.
- `⌘Z` right after the paste removes the added tag together with the pasted text (one undo step, like a normal paste). `⇧⌘V` (Ctrl+Shift+V) pastes as plain text without detection.
- Implementation: `paste-format-detection-service.js` (detection and planning, tests in `tests/unit/paste_format_detection.test.mjs`), wired in `keyboard-events.js`.

## Paste format guesses
- Text that only looks like a format is pasted as plain text, and a small card just below where the paste ended offers it: `Apply as Markdown` (or `Apply as CSV`, `Apply as Python`) and `Skip`. When several languages are close, it reads `Looks like code:` with up to three, best first (`Ruby`, `Python`), then `Skip`. A wrong guess costs nothing.
- What is offered:
  - CSV-like: three or more lines with the same number of comma-separated cells (two or more; commas inside quotes do not count), short cells, no sentences → `@csv`.
  - Markdown-like: two or more different kinds of signs (`#` headings, a list of two or more items, `**bold**`, `` `code` ``, `[text](url)` links, `>` quotes), or two or more headings → `@markdown`. A table (`| a | b |` with its `---` line) or a bare fenced code block (```` ``` ````, opened and closed) settles it: such text is Markdown even when the code inside reads as HTML or Python. (A fence naming its language, ```` ```html ````, is tagged at once; see above.) A lone bullet list or a single heading is an ordinary note and is not offered.
  - Code: mostly code-like lines (ending in `;`, `{`, `)`, `:`..., indented code, assignments and calls, no sentences), or a strong sign of one language → `@code=<language>`, for SQL, Python, Ruby, JavaScript, TypeScript, Shell (`@code=bash`), HTML, XML, CSS, Java, C, C++, C#, Go, Rust, YAML and Dockerfile, each scored on its own signs (`SELECT ... FROM`, `def f():`, `do |x|`, `console.log`, `#!/bin/bash`...). Notes of `key: value` lines are not YAML; a sentence mentioning "select ... from" is not SQL.
- A paste with formatting is checked too; see Formatted pastes below. Nothing is offered where nothing would be added (see above): Markdown into a note that is already `@markdown`, code into `@code=…`, CSV into `@csv`.
- The card moves nothing and never takes the keyboard: the caret stays where the paste ended. `Skip`, `Escape` (which closes only the card, not edit mode), typing on, a click elsewhere, scrolling the page yourself, or leaving edit mode closes it without applying; when MetaList scrolls on its own (a new note settling into view) the card stays with the paste. Near the bottom of the window it opens above the paste instead; the page never scrolls to show it.
- Pasting while no note is edited makes a new note at the top, as before; its paste is checked the same way (certain formats tagged at once, likely ones offered on the card once the new note is in place).
- `Apply` adds the tag as a detected format is added: the plain tag into an otherwise empty note, or the paste wrapped `((...))` with `((@markdown))` into a note with other text. The note stays in edit mode and the text renders when it leaves editing. `⌘Z` right after removes the tag together with the paste, as for a format added at once.

## Formatted pastes
- A paste whose clipboard carries formatting (bold, links, headings, code from a web page or an AI chat) goes in with its formatting, as always. Its text without the formatting is then checked as a plain paste is: Markdown left in it (`##` headings, `**`, fences, as Copilot answers often are), CSV, code, and the formats a plain paste is tagged with at once (JSON, LaTeX, a diff, Mermaid, a chess position). What is found is offered on the same card (`Apply as Markdown`, `Apply as LaTeX`), never applied at once, since applying drops the formatting.
- A fully rendered paste (real headings and bold, no Markdown signs left in its text) offers nothing. Formats the clipboard's plain text already settles (JSON, a fenced block naming its language, spreadsheet cells, VS Code code) are still tagged at once, as before.
- `Apply` replaces the formatted paste with its text and adds the tag, as for a plain paste: the clipboard's plain text when it reads as the same format (it often keeps the source, `**bold**` included), otherwise the text without formatting. `Skip`, or typing on, keeps the formatting.
- Implementation: `formatted-paste-format-service.js` (tests in `tests/unit/formatted_paste_format.test.mjs`), wired in `keyboard-events.js` (`planFormattedPasteOffer`).
