# Tag suggestions read link titles

**Status:** Agreed with the maintainer 2026-10-28. Ready to build. Small. Filed here from `docs/inbox/` on 2026-10-28 (see "Found when filed").

Written from a read-only look at the repo. Check the code references before relying on them.

---

## 1. Today

- Tag suggestions match tag-like text in the note (connectors for spaces, segments, possessives, and so on; `docs/ui/tag-bar.md`). They read only the note's own text, through `note_text_for_tag_matching()` in `app/services/tag_term_matching.py` (called from `app/services/tag_suggestions.py` and `app/services/tag_suggestion_reasons.py`).
- A web address counts only by its site's name: `https://www.youtube.com/watch?v=…` reads as `youtube`.
- A link with its own text (a pasted label, `[text](url)`) already counts, since its text is in the note.
- A bare address shows its fetched page title on screen, but tag matching never sees the title. A note that is only a link gets suggestions from the site name alone.
- Quoted search already matches stored titles of every web address in a note (`list_link_title_urls()` and `append_link_titles_casefold()` in `app/services/search_text.py`; `docs/ui/search-semantics.md`).

## 2. The rule

1. **A link's stored title counts as text of the note** for tag suggestions, matched exactly like typed text (all the existing literal, segment, connector and possessive rules). The site name still counts as today. Use the same titles quoted search uses, so the two never disagree.
2. **Only once the title is known.** A note whose title hasn't been fetched (or failed) is matched as today. When a title arrives, the next suggestions use it.
3. **The typing cache must notice new titles.** The empty-bar ranking reused while typing (`_typing_basis()`, its sensitive memo) is invalidated today when the note's text, tags, the tree, other notes' tags or the tag rules change. A title arriving for one of the note's links (the link-title revision) must invalidate it too.
4. **`Why suggested` says the match came from a link's title,** for example "Named in the title of a link in this note", so the suggestion is explained.
5. **Only the note's own links count,** never titles in its ancestors' or children's text, matching the existing "only the note's own text counts" rule.
6. Titles are unavailable while the vault is locked, as for search.

## 3. Done when

1. A note holding only `https://www.youtube.com/watch?v=…` whose fetched title is "Sourdough Starter From Scratch" suggests an existing `sourdough-starter` tag on the empty bar; before the title is fetched, it doesn't.
2. Typing in the tag bar narrows that list as usual; a title arriving mid-edit appears in the next suggestions without retyping.
3. `Why suggested` for that tag names the link's title as the source.
4. A child note under that link note gets no suggestion from the parent's title.
5. A link with its own label behaves as today (its label counts); the site name still names a `YouTube` tag.
6. Tests cover 1–5; `docs/ui/tag-bar.md` describes the rule beside the web-address bullet.

## Found when filed (2026-10-28)

- Not built: `note_text_for_tag_matching()` (`app/services/tag_term_matching.py`) replaces each address with its site name and reads no title. The other references hold: its three callers (`tag_suggestions.py` twice in ranking plus `_typing_basis()` via `_suggest_tags`, and `tag_suggestion_reasons.py` `ReasonWriter.build`), `list_link_title_urls()` and `append_link_titles_casefold()` in `search_text.py` (titles from `link_title_store.get_ok_title()`), and the web-address bullet in `docs/ui/tag-bar.md`.
- Rule 3 may already hold: `_TypingBasis.is_current()` checks `search_index.revision`, and `SearchIndex.refresh_link_titles()` bumps that revision whenever a fetched title changes a note's searchable text. Verify with a test rather than adding a second invalidation.
- Same titles as quoted search means only addresses with a scheme: `list_link_title_urls()` skips text without `://`, while tag matching also treats a bare `www.` address as an address. A `www.` address without a scheme gets no title in either.
- Tag matching reads the edited, unsaved text (`content_html` from the tag bar), so titles must be looked up from that text, not from the search index's saved copy.
- `Why suggested` builds "Named in this note: …" in `named_line()` (`tag_suggestion_reasons.py`); the title source needs a separate `where` (or line) so the reason names the link's title.
- Decided 2026-10-28: the whole title counts, site name included. Never drop a trailing ` - YouTube` or ` | Reddit`: the maintainer has tags that are site names (`reddit`, `hackernews`, `youtube`, `archive.org`). This also keeps suggestions reading the same titles quoted search does.
