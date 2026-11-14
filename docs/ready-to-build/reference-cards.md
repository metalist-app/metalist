# Reference pages

**Status:** agreed with the maintainer 2026-11-13; ready to build. Replaces the stacked cards this note first described, which were built, tried and dropped the same day (§11). The on-screen cases (§10) need the maintainer's agreement before code.
**Replaces:** reference views as search contexts with a chip (`docs/ui/references.md`, "Reference views").

Following a reference stops opening a search context. It turns to a **reference page**: the notes column slides off to the left and the page slides in from the right, as today, under a header that says what it is, not a search bar.

## How it works today (as the note found it, read-only)

- Four kinds of reference view (`app/static/js/modules/mode-manager/services/reference-source-navigation-service.js:8–24`):
  - **Source note:** reached by a link, an embed's reference icon, Go to Source Note, a floating window's title, or the password audit.
  - **Backlinks** (called Referenced by until 2026-11-13): from the count badge.
  - **Reference:** one AI citation.
  - **All references:** every citation in an AI answer.
- Each one is an ordinary search context whose search is a hidden note-ID query (`reference-source-navigation-service.js:47`), kept in tab state `referenceViews` on the server.
  - **Effect 1:** every link followed adds an entry to the list of search contexts. The maintainer had six "Source note" entries after clicking around.
  - **Effect 2:** a new note takes the search's positive terms as tags (`docs/ui/search-semantics.md`, new notes), so a note added in one of these views is **tagged with the linked note's UUID**. An outdent there probably does the same through "Moving Notes During Search".
- The view shows the linked note, its ancestors and its descendants; other sibling branches are redacted to grey bars.
- The search input is replaced by a chip (label, `←`, `×`, a magnifier). Escape goes back one level. Following a link already on the path returns to it (`findReferenceLevelOnActivePath()`). The view takes the origin search's sort mode (`copyOriginScope`).

## Why change it

Every way of showing a non-search in the search bar misleads:
- **Keep the search:** it isn't what's on screen.
- **Grey it:** unclear whether you can type, or what happens if you do.
- **Empty it:** empty means every note.
- **Remove it** (today): honest, but your main way of getting around is gone. A few links deep you feel stranded, not knowing how many Backs lead home.

## 1. A reference page

- **Following a reference slides the column off to the left and the page in from the right** (today's slide; a quick fade with Reduce Motion, nothing with Animated Transitions off). Going back slides the other way.
- **No search bar on a reference page.** Nothing suggests a search: the black bar is replaced by the page's header.
- **The header, left to right:**
  - `⏮` (double back): straight back to the search the reference was followed from, in one step. Shown only from the second page on: on the first, `◀` already goes there.
  - `◀` (back): back one page.
  - **The page's kind,** large, bold and grey, much larger than the notes' text: `Source note`, `Backlinks` (the maintainer, 2026-11-13: more commonly understood than Referenced by), `Reference` or `All references`. Not the note's first line: two kinds hold several notes.
  - `▶` (forward): forward again along the way just come back, one page at a time. Shown only after going back, as Redo is only there after an Undo.
  - **The number of notes on the page,** where the search's count sits.
- **Only the arrows that can act show** (the maintainer, 2026-11-13: like an undo and redo stack). One page: `◀`. Two or more: `⏮ ◀`. After going back: `▶` too. A hidden arrow keeps its place, so the others never move under the pointer (`is-unavailable`, `reference-source-navigation-service.js`).
- **The arrows are white outlines** in the black bar, like its search-context icon.
- **A reference page is not a search context.** Nothing is added to the list of search contexts.
- **All four kinds are reference pages and behave the same way.**

## 2. Moving between pages

1. **`◀`, and Escape outside editing, go back one page;** `⏮` goes back to the search. Each lands exactly as it was left (scroll, open notes).
2. **`▶` is like a browser's Forward:** after going back, it goes forward again along the same path, one page at a time, to each page as it was left. **Following another reference drops what was forward,** as a browser does. Back at the search there is no forward: the path ends there.
3. **A note being edited on a page that is left is saved first.**
4. **Following a reference to a page already on the path** goes back to it (today's path-return rule), as `◀` would, and the pages after it become forward. A reference to the page shown does nothing.
5. **A later AI reference replaces an AI page shown** instead of adding a page, as today.
6. **The browser's Back button does not touch reference pages** (decided 2026-11-13): Back means going to another page, and MetaList is one page.
7. **The path survives a reload, per view** (decided 2026-11-13): each device or browser tab keeps its own; another one opening the vault shows its own search. What was forward is not kept.
8. The chip, its `←` and `×`, and the magnifier go.

## 3. What a page shows

**Each linked note as a root, with its whole subtree, fully editable; nothing above it and nothing beside it** (the maintainer, 2026-11-13, after going back and forth: "if I link to a child, Baz, then Baz is what I shall see and it will appear to be a root note"). It is how an embed of the note shows it. A linked note under another linked note shows inside it, once. Built 2026-11-13: a search made only of note IDs lists them so (`note_page_root_ids`, `app/services/snapshot.py`; `tests/unit/test_reference_page_notes_as_roots.py`).

Dropped the same day: greyed, read-only ancestors and grey bars for siblings, with a click on the grey opening the whole root note. They made a page hard to read and allowed edits outside the linked note.

**The AI cites the note that makes sense on its own** (§5), since that note is all the page shows.

**No sort or filter controls on a page.** A page is a fixed set of notes, not a query. Pages with several notes use a fixed order:
- **All references:** citation order in the answer (decided 2026-11-13).
- **Backlinks:** most recently edited first (decided 2026-11-13).

## 4. Editing on a page

**Anything inside a linked note's subtree can be edited** as anywhere else: text, tags, children, delete, reorder.

**Nothing may end up outside it.** These are refused:
- adding a root note
- adding a sibling of the linked note or of any ancestor
- outdenting a note out past the linked note
- moving, pasting or dropping a note outside it

**Each refusal shows a short message** in the style of the existing "New notes cannot be added in this search" banner: "Only notes inside the linked note can be added here." (built; `reference-page-edit-guard.js`, which also refuses a child added under a note outside the linked note, `tests/unit/reference_page_edit_guard.test.mjs`).

**Enter at the end of the linked note does nothing but show that message.** It would make a sibling, so it's refused. It must not make a child instead: a key never changes meaning on a page, it only refuses.

**A page never adds tags to a note.** It has no search, so nothing is copied, which ends the UUID tags.

Why: notes added inside the linked note are there the next time the link is followed; notes added outside it wouldn't be, which is confusing.

## 5. What the AI cites

Added to the agent's instructions (2026-11-13; `prompts/agent.md`, `final-response.md`, `system.md`): **cite the note that makes sense on its own,** since a citation shows the cited note alone. If what it found is a grandchild that means nothing without its parent, cite the parent (or the level that carries the context). This is the rule a person follows when writing a link. The note-reading tools already return whole trees (`app/services/agent/agent_tools.py`, `read_view_notes` and `search_view_notes`), so the model can see the right level.

## 6. Existing data

No conversion (decided 2026-11-13): nobody has added notes inside a reference view, so there
are no note-ID tags to remove, and leftover reference-view search contexts are few. Building
reference pages needs no clean-up step.

## 7. Invariants

1. Following a reference never adds a search context.
2. A reference page never looks like a search: no search bar, no search text.
3. Every way back lands on a page, or the search, exactly as it was left.
4. A page never gives a note a tag.
5. Every note that can be added or moved on a page stays inside a linked note's subtree, so it shows the next time that reference is followed.
6. A page shows only the linked notes and what is under them, each as a root.
7. A key does the same thing on a page as anywhere else, or nothing with a message.

## 8. Still open

- **The phone:** the header has to fit a phone's width.

## 9. Checked when filed (2026-11-13)

Filed from the inbox; the `×` addendum is folded into §2 rule 8.

- **Confirmed:** the four kinds and their labels (`REFERENCE_VIEW_KINDS`, `TAB_LABEL_BY_VIEW_KIND`, `reference-source-navigation-service.js:8–24`); the hidden note-ID query (comment at line 47–48, `NOTE_ID_PATTERN`); tab state `referenceViews` (`app/api/note_requests.py`, `app/services/tab_state.py`); `findReferenceLevelOnActivePath()` (used by `keyboard-events.js` `returnToReferenceLevel()`); `copyOriginScope`; `read_view_notes` and `search_view_notes` (`app/services/agent/agent_tools.py`); the "New notes cannot be added in this search" banner (`root-note-creation-service.js`).
- **Not where the note says:** "Reference views" in `docs/ui/references.md` is a bullet list under "Search Semantics", not a heading. It now points here.
- **Not reproduced:** Effect 2 (a new note in a reference view tagged with the linked note's ID). Nothing read stops a note-ID term from being copied as a positive search term (`findUnfillableSearchTerm` skips only property terms), so it is likely. No conversion is needed for it (§6).
- **Replaces built behaviour** documented in `docs/ui/references.md` (the chip, its `←` and `×`, the magnifier that turns a view into an ordinary search, the slide transitions, path return) and tested by `scripts/browser-reference-view-regressions.mjs` (`BROWSER_TEST_SUITE=reference-views`) and `tests/unit/reference_path_return.test.mjs`. Those tests change with it.
- **Interaction principles:** cards opening, closing and landing move things on screen, so before code the cases (open, close by each way out, return along the path, reload, short and tall notes, the phone) and their exact positions are agreed with the maintainer (`AGENTS.md`, "On-screen Behavior Follows the Interaction Principles").
- **Decided with the maintainer 2026-11-13:** Back leaves cards alone (§2 rule 7); the stack survives a reload, per view (rule 9); citation order for All references and most recently edited first for Backlinks (§3); the refusal wording (§4); no conversion (§6); the `×` tooltip `Close` (rule 8).
- **Still open:** how a deep stack looks (§8); not needed to start.

## 10. Cases on screen (proposed 2026-11-13, for agreement before code)

Each case names the interaction principle it follows (`docs/ui/interaction-principles.md`) and
gets a browser test that checks exact positions.

| # | Case | Expected result |
|---|---|---|
| 1 | Follow a reference from the search | The column slides off left and the page slides in from the right (today's slide); the header replaces the search bar in the same place. The page lands scrolled to its top. |
| 2 | Follow a reference from a page | The same slide; the page left is kept as it was (its scroll), for `◀`. |
| 3 | `◀`, or Escape when not editing | Slides back (right); the page or search before it is exactly as it was left (1, 4). |
| 4 | `⏮` | Slides back to the search, exactly as it was left; every page on the path closes. |
| 5 | `▶` | Slides forward (left) to the page come back from, exactly as it was left. Dimmed, and does nothing, when nothing is forward. |
| 6 | Follow a reference after going back | Drops what was forward; then as case 2. |
| 7 | Follow a reference to a page already on the path | As `◀` to that page; the pages after it become forward. A reference to the page shown does nothing. |
| 8 | A later AI reference with an AI page shown | Replaces it (slides in from the right), no new page. |
| 9 | Leave a page while editing a note on it | The note is saved first (6). |
| 10 | Reload | The same page and path come back, in this device or tab; forward is gone. |
| 11 | The list of search contexts | Never lists a reference page; with a page shown, the search it came from is the one marked in use. |
| 12 | Narrow window and phone | Open (§8). |

## 11. Tried and dropped: stacked cards (2026-11-13)

Cards stacked over the search, each a step down and right, as wide as the column, their tops
staying put while the front card's notes scrolled under them; what each card covered stayed in
sight around and below it as a still copy. Built and tried in the maintainer's MetaList the same
day: "visually difficult to parse and cluttery looking". The cards' edges, the copies' notes and
fold arrows, and the list beneath all competed. Reference pages keep one column of notes on
screen, and the header says where you are and how to get back.
