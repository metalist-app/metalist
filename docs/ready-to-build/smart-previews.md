# Smart previews while editing

**Status:** Agreed with the maintainer 2026-10-26. Built in slices, each tried by the maintainer before the next. **Slices 1 (LaTeX), 2 (CSV), 3 (Mermaid), JSON and 4 (references) built 2026-10-29** (documented in `docs/ui/content-formatting.md`, "Previews while editing", and `docs/ui/references.md`, "The preview card"). Left, in order: 5 Insert LaTeX / CSV / Diagram (§5), 6 previews on the "Apply as …" card (§5). Delete this note when the last is built.
**Scope:** a live, rendered preview of the construct being edited (LaTeX, CSV, Mermaid, references) while a note is in edit mode. Document it in `docs/ui/content-formatting.md` and `docs/ui/references.md`.

Written without running the code. Every reference below came from reading it and must be checked before relying on it; build only what's missing.

---

## 0. The philosophy

MetaList's edit mode shows raw text on purpose (precision, plain-text durability, no hidden formatting). But raw text can be awkward: `[[UUID]]`, LaTeX source, CSV, Mermaid. **A core principle: do everything possible to make editing raw text less jarring, without giving up the raw text.** Smart previews are one application of it.

## 1. Today (to verify)

`docs/ui/content-formatting.md`: edit mode shows raw text; view mode shows the result. `@LaTeX` notes and scoped `(((@LaTeX)))` wrappers render server-side as MathML ("Invalid LaTeX" badge); inside Markdown, paired `$…$`, `\(…\)`, `$$…$$`, `\[…\]` render as math; ```` ```mermaid ```` fences render as diagrams in the browser; `@csv` notes and `((@csv))` wrappers render as tables ("Invalid CSV" badge). Pastes that only *look* like a format get a small "Apply as …" card. The editing loop today: leave the note to see the result, go back in to fix a missing `}`.

## 2. The rule: previews only inside a declared, delimited region

- **A preview appears only when the cursor is inside a region already declared as a format:**
  - a note tagged with the format (`@LaTeX`, `@csv`, …): the whole note
  - a scoped wrapper (`(((@LaTeX)))`, `((@csv))`, …): just that region
  - inside a Markdown note, math or Mermaid delimiters: `$…$`, `$$…$$`, `\[…\]`, ```` ```mermaid … ``` ````
  - a reference token `[[UUID]]` or `![[UUID]]` (§4)
- **Both the opening and the closing delimiter must already be there.** Type `$$ $$` (or use an Insert helper, §5), then type inside.
- **Outside a declared region, nothing ever appears.** No guessing while typing.

## 3. How the preview behaves

- **A small floating panel just below the line being edited,** showing only that construct rendered (the formula, the table, the diagram), not the whole note. **It floats; the note's text never moves.**
- **Updated on every keystroke** where rendering is fast enough (LaTeX and CSV in the browser); heavier formats such as Mermaid may update every few keystrokes.
- **Skip uninteresting content:** if the result would look the same as the typed text (`$$x$$`), show nothing. Preview only when the construct contains something that changes appearance (a command such as `\frac`, a superscript or subscript, a brace group, a table, a diagram).
- **Broken mid-typing (`\fra`): keep the last good preview and let it fade** toward a faint ghost (not to nothing) while the text stays broken, snapping back to full strength the moment it renders again. Fading inside a floating panel isn't layout motion (nothing around it moves). An error message appears only when the user pauses or leaves the region. Please build it so the fade timing and floor are easy to tune; the maintainer wants to see it before settling them.
- **No "assumed closers" hint** (like "assuming `}}`"). With both delimiters required, no repair of missing closing delimiters is needed.
- **Escape dismisses it; a setting turns previews off.**
- **The stored text is never changed by a preview.**

## 4. Reference previews: `[[UUID]]` in edit mode

- A `[[UUID]]` (or `![[UUID]]`) token is a declared region, and in edit mode it's the least readable thing in a note.
- **When the cursor is inside the token, or the mouse rests on it,** the floating preview shows its target: the note's first line and a few lines of content; for a file, its picture, diagram or file card. Not on click (a click places the cursor, which triggers it anyway). If the existing reference hover card (`docs/ui/references.md`, the preview card) already does part of this, reuse it rather than building a second one.
- **It shows how the reference will render:** a link or an embed, with its `|text` override if present.
- **`@password` targets** show their protected values hidden.

## 5. Pasting and Insert helpers

- **Pasting:** the existing "Apply as …" card for undeclared text stays, and **can show a preview** of the result, so the user sees the table or formula before applying the format.
- **Insert helpers:** right-click → **Insert LaTeX**, **Insert CSV**, **Insert Diagram** (Mermaid), and so on (also in the command palette). Each sets up the tag or wrapper and the delimiters and puts the cursor inside, so declaring costs nothing. Same pattern as the existing **Add Excalidraw Diagram**. For LaTeX, inline versus block (`$` versus `$$`) stays the user's choice.

## 6. Question for you first: where LaTeX renders

Today LaTeX renders on the server. A round trip per keystroke would lag and load the server. A browser-side renderer (KaTeX, or Temml, which outputs MathML) is fast enough, but **it should be the same renderer the server uses,** or previews could differ from the final note. Find out what the server uses and propose: the same library in the browser, or a switch for both. Don't ship previews that disagree with the rendered note.

## 7. Not decided

- The phone: likely no previews (little space); revisit with the phone work.

## 8. Invariants

1. Previews appear only inside a declared region with both delimiters present (a reference token counts).
2. The preview floats; it never moves the note's text.
3. The stored text is never changed by the preview.
4. Uninteresting content gets no preview.

## 9. Tests (at least)

- Cursor inside `$$\frac{1}{2}$$` shows the formula below the line; outside it, nothing; with only `$$` and no closer, nothing.
- `$$x$$` shows no preview.
- Typing `\fra` keeps the last good preview, faded; completing `\frac{1}{2}` restores it.
- A `((@csv))` region previews as a table; a Mermaid fence previews its diagram.
- Cursor in `[[UUID]]` previews the target; a `@password` target shows its value hidden.
- The note's text never shifts when a preview appears or disappears.
- Escape hides the preview; the setting turns previews off.

## 10. Checked 2026-10-27 (filed from the inbox)

- **§6, where LaTeX renders:** the server uses the Python library `latex2mathml` (`app/services/latex_rendering.py`), which has no browser version, so "the same library in the browser" isn't possible as is. Options: (a) previews ask the server, debounced (a local round trip is a few milliseconds; the same renderer, so no disagreement); (b) switch both to one JavaScript renderer (Temml outputs MathML), which the server can only run through Node, a new runtime dependency; (c) a browser renderer for previews only, which can disagree with the note (ruled out by §6); (d) render LaTeX in the browser everywhere with one JavaScript library (Temml, which also outputs MathML; or KaTeX), as Mermaid diagrams already are, so view mode and previews share one renderer by construction. (d) needs a check of exports and prints, which would carry the rendered math or the library, and of differences from `latex2mathml` in commands and error messages for existing notes. JavaScript LaTeX renderers (Temml, KaTeX, MathJax) are separate implementations from `latex2mathml`, so none matches it exactly. **Decided (maintainer, 2026-10-27): (a), the server renders previews,** with the same `latex2mathml` it uses for the note, so a preview never disagrees with the rendered note. The browser asks once typing pauses briefly (debounced; tune the wait), keeps the last good preview while a request is out or the text is broken (§3's fade), and drops answers to requests a newer keystroke has replaced. CSV can render the same way for one code path; Mermaid already renders in the browser for the note, so its preview does too. **Each format keeps one renderer for the note and its preview, wherever it runs (maintainer, 2026-10-27):** LaTeX on the server (a small Python library, no browser needed), Mermaid in the browser. Server-side Mermaid was considered and set aside: it lays out by measuring text, so it needs a headless browser (Node and Chromium) in every install on three platforms, a slower render than the browser's, and a light and a dark copy of every diagram.
- **§4 is partly built:** resting the pointer on `[[UUID]]` or `![[UUID]]` while editing (its `|text` too) shows the target's preview card, a password hidden (`docs/ui/references.md`, "The preview card", built 2026-10-27; `reference-hover-preview-service.js`, `reference-preview-card-service.js`). Not built: the caret inside the token as a trigger, and a card for a file's UUID (it shows none today). Reuse the card.
- Not built: previews for LaTeX, CSV and Mermaid while editing, and the Insert helpers. Add Excalidraw Diagram exists as their pattern.

## 11. Slice 1 (LaTeX), as built 2026-10-29
- The server finds the formula under the caret by rendering the note twice, without and with a caret mark, and listing the formulas each render meets (`app/services/edit_previews.py`); CSV can reuse the same approach for `((@csv))` regions and `@csv` notes, Mermaid for finding the fence (its drawing stays in the browser).
- Decided with the maintainer while trying it: the panel's left edge is at the caret and follows it as the caret moves (not the formula's start, and not fixed where it first appeared).
- Found: `latex2mathml` draws an unknown command (`\fra`) as its name instead of failing, and its errors carry no message. A half-typed command fades like a broken formula and shows as typed after the pause; the error shown is `Invalid LaTeX`, as the badge.
- Decided while trying it: selecting text (to type over it) keeps the preview where and as it was; it had disappeared, which the first acceptance list asked for.

## 12. Slice 2 (CSV), as built 2026-10-29
- `content_formatting.finding_tables` lists the tables a render meets, each with how to draw it as the render would (`FoundTable.render`), beside the formulas; the one holding the caret mark is drawn and the server sends the caret's row, which the panel scrolls to its middle.
- Found and fixed on the way: in a Markdown note every scoped region but LaTeX lost its drawing to the Markdown pass, so a `((@csv))` table there showed as run-together text (`docs/ui/content-formatting.md`, "Markdown meta tags"). A preview of it would have disagreed with the note.
- Found by the tests: the panel's 40% height left out its padding and border (now `box-sizing: border-box`).

## 13. Slice 3 (Mermaid) and JSON, as built 2026-10-29
- Mermaid: the server finds the diagram (`mermaid_note_rendering.finding_diagrams`, with whether its fence is closed) and sends its source; the browser draws it with the note's runtime and theme, after a 400 ms pause. Decided with the maintainer: a large diagram is scaled down to fit the panel, never up, even though a tall one becomes small. Mermaid's reason for a broken diagram is not shown (it needs an exception boundary to read).
- JSON was added after the slices (maintainer, 2026-10-29) to catch broken JSON while typing: valid compact JSON shows laid out, JSON already laid out shows nothing, broken JSON says why and where. No previews for code (`@code=…`): coloured it looks as typed, and nothing checks it. Checking code's syntax would be a separate feature (Python's own parser could do `@code=python`; most languages have no checker here).
- Found by the tests: the panel was placed with its height rounded to a whole pixel, a fraction off the line above it; it now uses its exact size.

## 14. Slice 4 (references), as built 2026-10-29
- The caret inside `[[UUID]]` or `![[UUID]]` shows the existing preview card, placed as for the pointer, through a third owner of the card (`caret`, `reference-caret-preview-service.js`); a file's UUID gets a card (`note_fullscreen.build_file_preview_markup`), for the pointer too.
- Found on the way: pictures in a preview card never loaded (the loader searched only the page, not the card's shadow root), for note cards too; fixed with a unit test.
- Found while trying it (maintainer): a link to a note showed its first line's LaTeX source. Agreed: a link draws its note's first line as the folded note does, formulas inline, in the link's colour (`docs/ui/references.md`, "Links").
