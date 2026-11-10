# Galleries (`@gallery`)

**Status:** brainstormed with the maintainer 2026-11-10 and being built. The first slice is built (2026-11-10, `app/services/note_gallery.py`, `docs/ui/content-formatting.md`): decisions 1, 2, 3 (without PDFs) and 6, children hidden, a tile's picture full screen through Zoom Image. Still to build: folded (one row), the grid/outline switch (5), previous/next and Go to note (7), value suggestions (4), search narrowing (8), PDF first pages.

A note tagged `@gallery` shows the pictures in it and in every note below it as a grid of thumbnails, opening full screen on a click.

## Decided

1. **The tag is `@gallery`**, one word like the other built-in tags (`@csv`, `@mermaid`, `@todo`), and not only for photos: drawings and PDFs belong in it too. It joins the built-in tags MetaList knows (`is_known_meta_tag_term()` in `app/services/content_formatting.py`; until then saving drops it and nothing offers it), so typing `@gal` offers it, and `gal` too, as built-in tags are offered without the `@`.
2. **What it holds:** the files in the note and in all its descendants, in outline order (depth first), each file once. A note embedded below it (`![[...]]`) adds nothing, as embeds pass no tags (`docs/ui/references.md`): only real children count. A big tree loads as it scrolls.
3. **Which files:** plain `@gallery` shows everything that can be drawn as a picture: images, PDFs (their first page, below) and Excalidraw drawings. `@gallery=image`, `@gallery=pdf` or several (`@gallery=image,pdf`) narrow it, with the kind names "Notes with Files" uses (`app/static/js/modules/mode-manager/services/file-filter-kinds.js`: `image`, `pdf`, `markdown`, else the extension).
4. **Suggestions for the value:** the tag bar offers the kinds actually found below the note, with how many (`@gallery=image (34)`, `@gallery=pdf (5)`), even before one was ever typed; kinds with nothing below are not offered.
5. **In the list:** the note shows its own text, then the grid; folded, one row of thumbnails. Its children are hidden while the grid shows: a switch beside its fold arrow flips the note between **grid** and **outline** (a normal tree, for editing and reordering), remembered per note, as deliberate choices persist (`docs/ui/interaction-principles.md`).
6. **A tile:** the picture, captioned with its note's first line when that is text; a note that is only the picture has no caption, and file names (`IMG_4031.jpg`) are not shown.
7. **Full screen:** a click opens the item full screen (the file viewer, with previous and next added): arrow keys move through every item of the gallery, `Escape` closes, and **Go to note** shows that item's note in the outline (switching the gallery to outline for it).
8. **Search narrows it:** with a search on, the grid holds only the files of the descendants the search shows, so it always matches the list; searching `beach` inside a trip gallery narrows its pictures.

## PDF first pages

PDFs have no picture today: an embedded PDF shows a `PDF` badge (`app/services/embedded_references.py`, `_format_thumbnail_badge`). The parts are there:

- PDFium already reads every PDF's text for search (`pypdfium2`, `app/services/file_text_worker.py`), in the background, at drop, import and login; it can draw page 1 as well.
- Files have a previews store (`file_previews`, `app/db/file_schema.py`), used today for Excalidraw's light and dark previews.

So: draw page 1 when the text is read (about 400 px wide, one size for thumbnails and tiles), keep it as the file's preview, and show it wherever a PDF is shown as a picture, the note's embed included, not only a gallery. PDFs already stored get theirs in the background, as their search text did. A password-protected PDF can't be drawn and keeps its badge.

## Open

- Whether a PDF preview fits `file_previews` as it is: its `variant` allows only `light` and `dark` (a PDF is the same in both). Any new column or kind is a schema change: version bump, migration, encryption audit (AGENTS.md).
- Audio, video and other files in a gallery: left out, shown as tiles with their badge, or a video's first frame.
- How many columns, and whether the grid follows the note's width or a fixed tile size.
