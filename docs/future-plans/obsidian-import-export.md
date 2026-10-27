# Obsidian import and export

**Status:** Agreed with the maintainer 2026-10-26, not scheduled. Split off from the Obsidian-style references change (built 2026-10-26: `![[UUID]]` embeds, `[[UUID]]` links, anywhere in text; `docs/ui/references.md`), which made MetaList's references read as Obsidian's do. Attracting Obsidian users is a priority.

## What it maps

- **Import:** `![[Note]]` → `![[UUID]]` (an embed), `[[Note]]` → `[[UUID]]` (a link), `[[Note|alias]]` → `[[UUID|alias]]`, keeping the alias.
- **Careful:** in Obsidian, `![[image.png|300]]` is an image **width**, not link text. `|number` on an embedded image maps to MetaList's image size; `|text` on a link maps to link text.
- **Export** reverses these: `[[UUID|text]]` becomes `[[Note title|text]]` (or the child/promoted forms the exporter uses, with `|text` appended), so aliases round-trip. A plain Markdown export that drops wiki links shows `text` as the link text.
- **Test:** import `![[Note]]`, `[[Note|alias]]` and `![[image.png|300]]`, export, and get them back.

## Found when filed (2026-10-26)

1. **Nothing exists to extend:** MetaList has no Obsidian importer or exporter (nothing in the code mentions Obsidian). Both are new work.
2. **Image sizes don't map exactly:** MetaList sizes an image by a factor in an `@size=` tag on the note (0.1 to 3.0, `app/services/image_size_formatting.py`), not by a width in pixels per image. `![[image.png|300]]` maps only roughly (to the nearest factor for the picture's own width), and two sizes of one picture in one note can't both be kept. **Open:** how close is close enough, and what export writes for a factor.
3. **Link text isn't built yet:** `[[UUID|alias]]` needs `docs/ready-to-build/reference-link-text.md`, still waiting on the maintainer's choice between typed markup and editing the text in place on the link.
