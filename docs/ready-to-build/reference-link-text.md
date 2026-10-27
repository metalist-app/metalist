# References: custom link text with `[[UUID|shown text]]`

**Status:** Agreed with the maintainer 2026-10-26. Small; ready to build, not started; filed here from `docs/inbox/` on 2026-10-26 (see "Found when filed").
**Scope:** let a reference display text the user chooses instead of the referenced note's first line. Update `docs/ui/references.md` with the result.

Written without running the code. Check every reference before relying on it; build only what's missing.

---

## 1. Syntax and behavior

- **`[[UUID|shown text]]`** links to the note or file with that UUID and displays `shown text` instead of the target's first line. Same syntax as Obsidian's `[[target|alias]]`.
- **Fixed text:** unlike a plain `[[UUID]]`, which follows the target's first line live, the shown text stays exactly as written.
- **Always a link, never an embed:** a note whose only content is `[[UUID|shown text]]` renders as a link (specific text was asked for). Plain `[[UUID]]` keeps its current embed/link rules.
- Reference icon, click behavior, and the temporary reference-source context are as for any link.
- **Parsing:** the UUID comes first; the first `|` separates it from the text; the text may contain further `|`; it can't contain `]]`. The text is plain (no nested references or formatting) and goes through the same sanitization as note text.
- Copy Reference (⌘R) and Paste Reference keep writing plain `[[UUID]]`; the user adds `|text` by hand.
- Everything that scans references (AI citation rendering, backlinks when they return, exports, link-title handling, search) must accept the `|` form and treat it as the same reference.

## 2. Import and export (Obsidian)

Attracting Obsidian users is a priority.
- **Obsidian import:** `[[Note|alias]]` becomes `[[UUID|alias]]`, keeping the alias.
- **Obsidian-flavored export:** `[[UUID|text]]` becomes `[[Note title|text]]` (or the child/promoted forms the exporter already uses, with `|text` appended), so aliases round-trip.
- Plain Markdown export (if it drops wiki links) shows `text` as the link text.

## 3. Tests

- `[[UUID|Hello]]` renders a link reading "Hello", unchanged when the target's first line changes.
- A note containing only `[[UUID|Hello]]` renders a link, not an embed; a note containing only `[[UUID]]` still embeds.
- `[[UUID|a|b]]` shows `a|b`; malformed forms render as plain text, as today.
- Text with HTML is shown as text, never rendered.
- AI citations, exports and any reference scanner treat `[[UUID|text]]` as a reference to UUID.
- Obsidian round trip: import `[[Note|alias]]`, export, and get `[[Note|alias]]` back.

## Found when filed (2026-10-26)

1. **No Obsidian import or export exists:** nothing in the code mentions Obsidian, so §2's importer and "the forms the exporter already uses" are not there to extend. §1 can be built on its own. **Open:** is §2 part of this or a separate, larger feature (an Obsidian importer and exporter)?
2. **⌘R pastes, it doesn't copy:** `⌘ + R` pastes a reference to the note copied last as a sibling, `⇧ + ⌘ + R` as a child (`docs/ui/controls.md`); there is no "Copy Reference". §1's point stands: both keep writing plain `[[UUID]]`.
3. **Backlinks are off for now** (`docs/ui/references.md`), matching "when they return".
4. **Reference scanners:** `_REFERENCE_TOKEN_RE` in `app/services/embedded_references.py` and `app/services/backlinks.py` and `_EMBED_TOKEN` in `app/services/html_export.py` already match `[[UUID|text]]` as a token; each must take the UUID before the first `|`. AI citations match a bare UUID only (`_BRACKETED_NOTE_CITATION_RE` in `app/services/ai_chat_rendering.py`). The embed rule (a note whose only content is the reference embeds it) is in `docs/ui/references.md`.
5. **Settled by the Obsidian-style references change (built 2026-10-26, `docs/ui/references.md`):** `[[` always links and `![[` embeds, so a lone `[[UUID|text]]` is a link like any `[[UUID]]`. §2 here moved to `docs/future-plans/obsidian-import-export.md` (with `|number` on an embedded image as a size). **Open:** link text typed in the markup as here, or edited in place on the link with the markup kept behind it (raised by the maintainer 2026-10-26).
6. **More scanners found when starting to build (2026-10-26):** `_FILE_REFERENCE_TOKEN_RE` in `app/services/file_registry.py` (file names in search), `_REFERENCE_TOKEN` in `app/services/agent/export_title_suggestions.py`, `_OUR_CITATION_TOKEN_RE` in `app/services/ai_chat_rendering.py`, and `referenceToken()` in `viewport-hold-service.js` (keeps a click after a reference in place on entering edit mode), which rebuilds the token as `[[UUID]]` and would not find `[[UUID|text]]`. Link text can't hold `[` or `]` unless the reference parser changes (it rejects either inside `[[…]]`). Branch `feature/reference-link-text` exists with no changes.
