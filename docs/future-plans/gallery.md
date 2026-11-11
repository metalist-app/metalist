# Galleries (`@gallery`)

**Status:** brainstormed with the maintainer 2026-11-10 and being built. The first slice is built (2026-11-10, `app/services/note_gallery.py`, `docs/ui/content-formatting.md`): decisions 1, 2, 3 (without PDFs) and 6, children hidden, a tile's picture full screen through Zoom Image. The second slice is built (2026-11-10, `app/static/js/modules/mode-manager/services/gallery-view-service.js`): folded (one row), the grid/outline switch (5), previous/next and Go to note (7); full screen is Zoom Image with ‹ › and Go to note added, not the file viewer, which cannot show pictures. Value suggestions (4) are built (2026-11-10, `_gallery_values` in `app/services/tag_suggestions.py`, `gallery_kinds_found` in `note_gallery.py`): offered from `@gal` on, right after `@gallery`, among the kinds a gallery draws (image, pdf, `.excalidraw`). PDF first pages are built in galleries (2026-11-10, database version 18: `app/services/pdf_first_pages.py`, `pdf_first_page_worker.py`, the `file_first_pages` table): drawn 900 px wide as a JPEG, shown from the page's top with a thin edge, a click opens it full screen with Open. Search narrowing (8) is built (2026-11-10, `is_note_shown` on the render context, `snapshot.py`): under a search the grid, folded row and full screen hold only the pictures of the notes the search shows (its matches and their ancestors), never those of the grey bars. Still to build: a PDF's first page in a note's own embed (below).

A note tagged `@gallery` shows the pictures in it and in every note below it as a grid of thumbnails, opening full screen on a click.

## Decided

1. **The tag is `@gallery`**, one word like the other built-in tags (`@csv`, `@mermaid`, `@todo`), and not only for photos: drawings and PDFs belong in it too. It joins the built-in tags MetaList knows (`is_known_meta_tag_term()` in `app/services/content_formatting.py`; until then saving drops it and nothing offers it), so typing `@gal` offers it, and `gal` too, as built-in tags are offered without the `@`.
2. **What it holds:** the files in the note and in all its descendants, in outline order (depth first), each file once. A note embedded below it (`![[...]]`) adds nothing, as embeds pass no tags (`docs/ui/references.md`): only real children count. A big tree loads as it scrolls.
3. **Which files:** plain `@gallery` shows everything that can be drawn as a picture: images, PDFs (their first page, below) and Excalidraw drawings. `@gallery=image`, `@gallery=pdf` or several (`@gallery=image,pdf`) narrow it, with the kind names "Notes with Files" uses (`app/static/js/modules/mode-manager/services/file-filter-kinds.js`: `image`, `pdf`, `markdown`, else the extension).
4. **Suggestions for the value:** the tag bar offers the kinds actually found below the note, the kind with the most files first (`@gallery=image`, then `@gallery=pdf`), even before one was ever typed; kinds with nothing below are not offered. No counts are shown (decided 2026-11-10): a number in a suggestion reads as if it would go into the tag bar, and no other suggestion shows one.
5. **In the list:** the note shows its own text, then the grid; folded, one row of thumbnails. Its children are hidden while the grid shows: a switch beside its fold arrow flips the note between **grid** and **outline** (a normal tree, for editing and reordering), remembered per note, as deliberate choices persist (`docs/ui/interaction-principles.md`).
6. **A tile:** the picture, captioned with its note's first line when that is text; a note that is only the picture has no caption, and file names (`IMG_4031.jpg`) are not shown.
7. **Full screen:** a click opens the item full screen (the file viewer, with previous and next added): arrow keys move through every item of the gallery, `Escape` closes, and **Go to note** shows that item's note in the outline (switching the gallery to outline for it).
8. **Search narrows it:** with a search on, the grid holds only the files of the descendants the search shows, so it always matches the list; searching `beach` inside a trip gallery narrows its pictures.

## PDF first pages

PDFs have no picture today: an embedded PDF shows a `PDF` badge (`app/services/embedded_references.py`, `_format_thumbnail_badge`). The parts are there:

- PDFium already reads every PDF's text for search (`pypdfium2`, `app/services/file_text_worker.py`), in the background, at drop, import and login; it can draw page 1 as well.
- Files have a previews store (`file_previews`, `app/db/file_schema.py`), used today for Excalidraw's light and dark previews.

So: draw page 1 when the text is read (about 400 px wide, one size for thumbnails and tiles), keep it as the file's preview, and show it wherever a PDF is shown as a picture, the note's embed included, not only a gallery. PDFs already stored get theirs in the background, as their search text did. A password-protected PDF can't be drawn and keeps its badge.

Decided 2026-11-10:

- **Stored in the vault,** encrypted, in backups: drawn once in the background, then always instant. `file_previews` does not fit (its `variant` allows only `light` and `dark`, and its rows come in pairs of SVGs), so the first page gets a table of its own in the files database, a schema step with its version bump, migration and encryption audit (AGENTS.md).
- **Full screen** shows a PDF's first page like any picture, with ‹ › stepping on through the gallery, and an **Open** button opens the whole PDF in the file viewer.
- **Plain `@gallery` shows PDFs** with the images and drawings, as a badge and name until their first page is drawn (a click on that opens the PDF); the page arrives without a reload, through the status check that brings link titles (`first_page_revision`).
- **Still open:** whether a PDF embedded in a note's own text (`![[...]]`, outside a gallery) shows its first page instead of its card. Only gallery tiles do so far.

Acceptance checks:

1. A PDF in a gallery shows its first page as its tile, filling the square cropped about the middle like a photo, open and folded.
2. Full screen shows the first page; ←/→ step through PDFs and pictures alike; Open shows the whole PDF in the file viewer; Go to note works as for a picture.
3. A PDF dropped into a note gets its first page in the background, with no reload; PDFs stored before get theirs at login, as their search text did.
4. A PDF that cannot be drawn (password, damaged) keeps its card, and is not tried again until its file changes.
5. (Dropped: a PDF's content cannot be replaced, only an editable file's. Each first page still records the file revision it was drawn from.)
6. A vault from before (version 17) opens and upgrades; the encryption audit accepts versions 17 and 18.

## Open

- Audio, video and other files in a gallery: left out, shown as tiles with their badge, or a video's first frame.
- How many columns, and whether the grid follows the note's width or a fixed tile size.
