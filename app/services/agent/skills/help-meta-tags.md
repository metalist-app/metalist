# @ tags (meta tags)

Use this reference to explain MetaList accurately. It describes user capabilities,
not permission or tools for you to execute every operation. You can answer and
request one supported menu/dialog opening. You cannot submit a form, change
settings, run a shell command, or mutate notes through this help response. Do not
claim that you inspected current notes or settings: none are supplied here.
Prefer user-facing steps over implementation details. If the reference does not
answer a question, say what is unknown; do not invent syntax or controls.

Sources: docs/ui/tag-bar.md, docs/ui/content-formatting.md

Typing tags (tokens, scopes such as `{{@red}}`, super tags) is in the tags help topic;
suggestions of `@` tags are in the tag-suggestions topic.

## Meta Tags (Formatting)
- Tags starting with `@` are reserved for server-side behaviors.
- Global meta tags apply to the whole note when unwrapped (e.g. `@red`).
- Scoped meta tags apply only to regions of note content wrapped with the same bracket type + depth.
  - Example: tag bar `{{@monospace}}` applies monospace styling to `{{...}}` regions in the note.
  - Depth must match exactly: `[[...]]` matches `[[@tag]]`, not `[@tag]` or `[[[@tag]]]`.
  - Scopes may cross multiple editor blocks/lines; visual styles are rendered as valid per-block spans across the full selected range.
- Basic formatting tags:
  - `@heading` increases font size and weight.
  - `@quote` draws a quote as Markdown does: indented with a grey bar at its left. Scoped (`((@quote))`), each region is a quote block on lines of its own, even one written mid-line.
  - `@bold`, `@italic`, `@strikethrough` apply basic text styling.
  - `@serif` switches to a serif font.
  - `@red`, `@green`, `@blue`, `@grey` (or `@gray`) apply text colors.
  - `@highlight` adds a fluorescent-yellow, slightly irregular marker stroke behind the text.
  - `@copyable` makes the rendered content click-to-copy: clicking it copies its raw text to the clipboard.
  - `@size=0.1`, `0.25`, `0.5`, `0.75`, `1.0`, `1.25`, `1.5`, `2.0`, or `3.0` scales a whole note or scoped region non-destructively in view mode.
  - Ontology implication rules can add these formatting tags implicitly (e.g. `bug => @red`).
- List meta tags:
  - `@bullets` renders the note's immediate children with bullet markers.
  - `@numbered` renders the note's immediate children with numbered markers.
  - Only the **direct** children are affected (grandchildren are not).
- Credential meta tags:
  - `@username` renders a view-only user-icon row with its value; clicking it copies it.
  - `@password` renders a view-only lock-icon row: `••••••••` and an eye that shows the value until the next click or key; clicking the dots copies it.
- Email meta tags:
  - `@email` renders a view-only envelope row with a mailto link.
- Status meta tags:
  - `@todo` renders an unchecked box icon; pressing the icon toggles the tag to `@done` on mouse down.
  - `@done` renders a checked box icon; pressing the icon toggles the tag to `@todo` on mouse down.
  - If another note is being edited, pressing a status icon saves and exits that edit session before toggling, without selecting the toggled note for editing.
- Date meta tag:
  - `@datetime=2026-10-24` or `@datetime=2026-10-24T08:30` (local time) says which date a note belongs to; a date alone means that whole day.
  - The search box suggests `@datetime` itself, which finds every dated note (typing `journal @date` offers it when journal notes have dates); a tag bar suggests it with a date.
  - The Created date range uses a top-level note's own `@datetime` instead of when it was created. Last Updated stays the real last edit, and sorting by Created still uses when the note was typed. A `@datetime` on a note below the top level dates nothing yet.
  - A value that is not a real date or time shows `@datetime needs a date: YYYY-MM-DD or YYYY-MM-DDTHH:MM` and is not saved; a second one on a note is refused (`@datetime is already on this note`).
  - The tag bar suggests it with the date the note's text names, else now (tag-suggestions topic).
- Image meta tag:
  - `@image` is inferred dynamically for search when note content contains inline image markup, a Markdown image link, or an embedded file reference whose attachment metadata is an image.
  - The tag is search-only; it is not persisted in the note's tag bar and does not change note rendering.
- Markdown meta tags:
  - `@markdown` renders note content as Markdown on the server in view mode.
  - Fenced `mermaid` blocks inside Markdown render locally as responsive SVG diagrams in the app; the Mermaid runtime is lazy-loaded only when needed, and invalid syntax preserves the source with an inline error badge.
  - Standard LaTeX regions inside Markdown render automatically: `\(...\)` or `$...$` for inline math, and `\[...\]` or `$$...$$` for display math.
  - LaTeX delimiters inside inline code or fenced code blocks remain literal.
- LaTeX meta tags:
  - `@LaTeX` renders note content as LaTeX on the server in view mode.
  - The server emits final MathML directly; the browser does not finish a second LaTeX rendering pass.
  - Use `$...$` for inline math and `$$...$$` for display math.
  - If no `$` delimiters are present, the entire note is rendered as display math.
  - Scoped LaTeX works with wrappers (e.g. `{{@LaTeX}}` renders only `{{...}}` segments) and can be combined with `@markdown`. Explicit scoped regions and automatically detected Markdown math can coexist; the scoped region is rendered once and its wrapper delimiters are still consumed normally.
- Shell meta tags:
  - `@shell` renders note content as a terminal-style script block in view mode.
  - Clicking the block starts a background shell session on the server and updates stdout/stderr inline while the command is still running.
  - Completed/error/timeout shell feedback can be dismissed with the inline `Close` button in the output header.
  - The transport is cross-platform, but note scripts still need to match the connected server host's shell and OS conventions.
- JSON meta tags:
  - `@json` pretty-prints note content as JSON under a `JSON` label; invalid JSON shows an error badge and raw text.
- CSV meta tags:
  - `@csv` renders note content as a CSV table; invalid CSV shows an error badge and raw text.
  - `((@csv))` renders only the wrapped content as a CSV table.
- Chess meta tags:
  - `@chess` draws the note's FEN chess position as a board (White at the bottom, with a caption for side to move, move number, castling and en passant); an invalid FEN shows an error badge saying what to fix.
  - `((@chess))` draws a board for only the wrapped FEN, inside the surrounding text.
- Diff meta tags:
  - `@diff` colours a unified diff (git diff / diff -u): added lines green, removed red, `@@` section starts and file headers marked; `((@diff))` colours only the wrapped content.
- Mermaid meta tags:
  - `@mermaid` draws the note content as one Mermaid diagram (no Markdown fence needed); `((@mermaid))` draws only the wrapped content.
- Pasting JSON, a chess FEN, a unified diff, Mermaid or a pure LaTeX block adds the matching tag at once (`@json`, `@chess`, `@diff`, `@mermaid`, `@LaTeX`): the plain tag into an otherwise empty note, `((...))` and `((@json))` into a note with content. ⌘Z right after removes it with the paste; ⇧⌘V pastes without detection.
- Code meta tags:
  - `@code=<language>` (for example `@code=python`, `@code=sql`) highlights source code; any language name the highlighter knows works, and an unknown one shows an "Unknown language" badge; `((@code=python))` highlights only the wrapped content.

Wrapper regions in note content are always allowed (e.g. `((foo))`), but they are only consumed/hidden in view mode when there is a matching scoped wrapper tag in the tag bar (meta tags like `{{@red}}` or regular tags like `{{foo}}`). Otherwise the wrappers remain literal text.

Wrapper tokens can contain multiple tags separated by spaces (e.g. `{{@red @monospace}}`).

Notes:
- Multiple tags inside a wrapper are still stored as a single wrapper token in the tag bar (i.e., the internal whitespace does not “split” it into separate top-level tokens).
- Non-meta tags inside wrapper tokens are allowed (e.g. `{{foo bar}}`) for future semantic uses; currently only `@...` meta tags affect formatting.

If a wrapper is opened but not closed:
- It does not immediately warn on a bare opener like `(`.
- Once there is content (e.g. `(tag`), the tag bar shows a warning and the incomplete token is omitted from the saved tag string.
- When you leave the tag bar, the incomplete token is removed from the input.

## Add Style Context Menu
- Right-clicking the actively edited note adds **Add Style**. Hovering or selecting it opens a connected flyout submenu containing the supported visual and renderer meta tags.
- **Remove Formatting** appears directly beneath Add Style and performs the same selection-aware operation as `Cmd/Ctrl+U`. For example, selecting `baz` in content `foo {{bar baz}}` with tag `{{@red}}` rewrites the content to `foo {{bar }}baz` and keeps `{{@red}}` for the remaining red range.
- With no selected range, the chosen unwrapped meta tag is added to the tag bar and applies to the entire note. **Footnote** is selection-only and is hidden without a selection.
- With a selected range, the text is wrapped and the matching scoped meta tag is added to the tag bar.
- Scope allocation prefers single `{}`, `[]`, and `()` delimiters in that order, then depth-two and depth-three forms. A candidate is skipped when its delimiter already occurs in the note content or tag bar.
- Basic styles can overlap. Applying a second style to a partially overlapping selection uses another delimiter pair, and view rendering splits the overlap into valid nested HTML.
- Renderer tags (`@markdown`, `@LaTeX`, `@json`, `@csv`, and `@shell`) can be added globally or to a scoped selection.
- Add Style also exposes fixed `@size=...` presets. Right-clicking an inline image in edit or view mode provides stepwise **Make Bigger**, **Make Smaller**, and **Reset Size** actions; stored image-file embeds expose those actions in view mode. Reset removes the size tag rather than retaining `@size=1.0`.
- `@gallery` shows the pictures in a note and in every note under it as a grid under its text, captioned with each note's first line, and hides the children; `@gallery=image` or `@gallery=pdf` narrows it; typing `@gal` in the tag bar offers the kinds of picture under the note, most first. A PDF shows its first page. A click on a picture shows it full screen, where the arrow keys step through the gallery, Go to note shows that picture's note, and Open shows a PDF whole; a click on a drawing opens it in the diagram editor. The switch below the fold arrow of an open gallery flips the note between grid and outline (its children shown), remembered per note; folded, a gallery shows one row of thumbnails either way. With a search on, it shows only the pictures of the notes the search finds (and the notes above them).
