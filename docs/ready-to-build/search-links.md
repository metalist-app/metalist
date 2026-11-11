# Links that open a search

**Status:** Agreed with the maintainer 2026-11-10. **Built 2026-11-11** (`app/services/search_links.py`; `docs/ui/references.md`, "Search Links"), but for the Markdown export, which doesn't exist yet: when it is built it writes search links as §6 says. Once it is, this note's content is in the permanent docs and it can go.

Written from a read-only look at the repo; filed from `docs/inbox/` on 2026-11-11, with the references checked (§9). `docs/ready-to-build/folder-tags-in-search.md` changes §4: folder contexts' searches are offered too.

---

## 0. Today (from the code)

- **No search links exist.** `docs/ready-to-build/obsidian-mapping.md` (E13) lists "translate to a MetaList search link" as an option for Obsidian `query` blocks and keeps them as text because there is none.
- **`[[…]]`** (`docs/ui/references.md`): `[[UUID]]` is a link, `[[UUID|text]]` a link with fixed text (no `[`, `]` or line break in it; a blank one isn't a reference). `[[…]]` holding exactly a UUID is always a link even under a scoped wrapper tag such as `[[@LaTeX]]`; any other `[[…]]` text is formatted by that wrapper. `[[@` starts a wrapper and opens no suggestions.
- **A word and a colon in the brackets is already a pattern:** the AI chat's web citations, `[[web:…]]` (`app/services/agent/citation_tokens.py`, `app/services/ai_chat_rendering.py`).
- **Scanners that take any `[[…]]` as a reference:** `app/services/backlinks.py` and `app/services/embedded_references.py` (`!?\[\[[^\[\]\n]+\]\]`). `file_registry.py` and `parse_reference_inner` take only UUIDs.
- **`|` means nothing in search syntax** (`docs/ui/search-syntax.md`).
- **Rename tag seems not to rewrite saved searches.** `apply_rename_tag_everywhere` (`app/usecases/rename_tag.py`) changes notes' tags and the tag bar. The only caller of `TabState.rename_search_terms` (`app/services/tab_state.py`) is the one-time built-in tag rename (`app/services/content_cache.py`). Folder renames move folder contexts. Check this.

## 1. The idea

A link inside a note that, when clicked, opens a search context with its search filled in. A note becomes a dashboard: a "Projects" note with one link per project, each opening that project's search. A long query is written once and clicked after, on the phone too.

## 2. Syntax

```
[[search:work -archive -journal]]
[[search:work -archive -journal|Current work]]
```

- **`[[` with a `search:` prefix.** One family of links, already taught; `[[web:…]]` already uses the shape; a UUID never starts with `search:`.
- **`|text` is optional link text,** exactly as for note links: fixed, plain, from the first `|` to the `]]`.
- **The search is everything between `search:` and the `|` or `]]`,** as it would be typed in the search box.
- **A search holding `[` or `]` can't be written this way.** It's rare; such a search context isn't offered (§4). No escaping for now.
- **`[[search:]]`** with nothing after the colon is text as typed.
- **`![[search:…]]` is reserved** for live results inside the note, later (§8). Until then it is text as typed, and `![[` suggestions don't offer searches.

## 3. Clicking one

- **Reuse a matching search context.** If one already has exactly this search, switch to it. Otherwise create a new one with the search filled in.
- **"Exactly this search"** means the same terms (decided 2026-11-11): runs of spaces, leading or trailing space, the order of the terms (and of `OR` clauses) and capitals don't count, as such searches find exactly the same notes (`work -archive`, `-archive  work` and `Work -archive` are one search). Compare the parsed searches, not the text; the words inside a quoted phrase keep their order. Sort, date range and other view options don't count: the link carries only the search.
- **A new one is an ordinary search context,** kept in the list like any other, not a temporary view like Source note or the folder context, and named by its search as every search context is.
- **The context you were in is untouched.**
- Phone: a tap does the same.

## 4. Making one

- **Typing `[[` offers search contexts too,** beside notes, each as a magnifier and "Search: work -journal". Choosing one writes `[[search:…]]`.
- **Which:** only search contexts with a typed search. Not the folder context (its folder is a chip, not search text), not reference views (note IDs), not a search holding `[` or `]`.
- **Where in the list:** search contexts whose search matches what's typed after `[[`, above the notes (decided 2026-11-11: there are few, and a matching one is likely what's wanted; below the notes it could be pushed off screen). With nothing typed, the current search context first, then the notes as today (linking the view you're looking at).
- **Typing the markup by hand works too.**

## 5. How it looks

- **A link reading its text, or its search if it has none,** with a small magnifier in place of the reference icon, so it doesn't read as a link to a note.
- **Hovering shows the search** when the link has text (decided 2026-11-11): a tooltip (`Current work` shows `work -archive -journal`), not the note preview card and not a card of results. A link without text already reads its search, so it has none.
- **Editing shows the markup,** as for note links.

## 6. What must keep working

- **It is not a reference.** Backlinks (the Referenced by badge), embeds, the reference index (Trim Unused Files), AI citations and the reference parser all skip `search:`.
- **Scoped wrapper tags don't format it,** as with a UUID link.
- **Renaming a tag rewrites the tag inside search links,** in the rename's single undo step, without changing notes' updated times (as Rename tag treats notes now). Only the search's tags change, never quoted text.
- **The same for search contexts' own searches.** If Rename tag leaves them alone today (§0), fix both together. The one-time built-in tag rename covers search links too.
- **Exports:** the HTML export keeps the markup. Markdown writes the link's text, then its search (decided 2026-11-11): `Current work (search: `work -archive -journal`)`, and `recipes (search: `recipes`)` for a link with no text. Other apps have no MetaList searches; the markup would read as a link to a note named `search:…` (Obsidian makes an empty one on click), and the text alone loses what was searched.
- **Search** finds a note by the words in its search links, as for any text.
- **The AI** reads the markup as written; it is note text.

## 7. Invariants

1. Following a search link never changes the search context you were in.
2. Clicking the same link twice never makes two search contexts.
3. A search link is never counted as a reference to a note or file.
4. A tag rename never leaves a search link or a saved search pointing at the old name.

## 8. Not now

- **Live results inside a note** (`![[search:…]]`, like Obsidian's query blocks): later, and much bigger.
- **Obsidian `query` blocks** stay as text unless mapping them to search links turns out simple; the syntax differs a lot.

## 9. Checked against the code (2026-11-11, when filed)

- Every reference in §0 holds: `obsidian-mapping.md` E13; `[[web:N]]` in `citation_tokens.py` and `ai_chat_rendering.py`; the same any-`[[…]]` pattern in `backlinks.py` and `embedded_references.py` (`_REFERENCE_TOKEN_RE`); `parse_reference_inner` in `embedded_references.py`.
- **Rename tag does not rewrite saved searches (confirmed).** `apply_rename_tag_everywhere` (`app/usecases/rename_tag.py`) touches no search context; `TabState.rename_search_terms` (`app/services/tab_state.py`) is called only by the one-time built-in tag rename (`content_cache.py`). Fixing it is part of this note (§6) and of `folder-tags-in-search.md` §4, which depends on it: build the shared rewrite once.
- `embedded_references.py` also has `_BRACKETED_SPAN_RE` (`!?\[\[[^\]]+\]\]`), used to keep bracketed spans whole; check it when `search:` is added.

**Decided 2026-11-11** (once marked "proposed"): matching a search context by its terms (§3), matching search contexts above notes in `[[` suggestions (§4), a tooltip with the search (§5), the Markdown export writing the text and the search (§6). Nothing is open.

## 10. Found while building (2026-11-11)

- **Rename tag has no undo step at all** (its confirmation says it can't be undone), so §6's "in the rename's single undo step" can't hold: search links and saved searches are renamed the same way as tag bars, for good.
- **No Markdown export exists yet** (`import-export-launch.md` plans it); §6's rule waits for it.
- **The one-time built-in tag rename** (`meta_tag_renames.py`) ran before search links existed, so no link holds an old built-in name; it is not extended.
- **The browser keeps its own copy of the search contexts** and posts it back; a copy read before a rename would bring the old name back. The server keeps a renamed search over such a copy, as it keeps the sort order, and the browser reloads its search contexts right after a rename.

