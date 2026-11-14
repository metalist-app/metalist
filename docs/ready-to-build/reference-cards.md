# Reference cards

**Status:** agreed with the maintainer 2026-11-13; ready to build. Only the look of very deep stacks is still open (end of this note).
**Replaces:** reference views as search contexts with a chip (`docs/ui/references.md`, "Reference views").

Following a reference stops opening a search context. It opens a **card** stacked on top of the search context you were in.

## How it works today (as the note found it, read-only)

- Four kinds of reference view (`app/static/js/modules/mode-manager/services/reference-source-navigation-service.js:8–24`):
  - **Source note:** reached by a link, an embed's reference icon, Go to Source Note, a floating window's title, or the password audit.
  - **Referenced by:** from the count badge.
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

## 1. Cards

- **Following a reference opens a card stacked on top of the current search context,** offset slightly down and right of the layer below, like a stack of paper.
- **The search context underneath is unchanged and stays visible:** its search bar and count stay as they were. You can always see where you started.
- **A card is not a search context.** Nothing is added to the list of search contexts.
- **Each card carries a small label with its kind:** `Source note`, `Referenced by`, `Reference`, `All references`. It doesn't use the note's first line, because two kinds hold several notes.
- **All four kinds are cards and behave the same way.**
- **A card is a sheet with a top edge and no bottom** (decided 2026-11-13): as long as its notes, read by scrolling like the regular list, without a scroll bar of its own. **The tops of the cards stay put** under the search controls, each with its label at its step, and the top card's notes scroll up under its top edge the way notes scroll under the search controls today. **Each card keeps its own scroll position:** opening a card on top leaves the one below where it was, and closing the top card shows it exactly as it was left. (Considered and dropped: the whole stack scrolling away with the page, which shares one scroll position, so a new card would drag the one below and the stack would jump with depth.)
- **Each card keeps the notes column's width and steps out past its right edge** (decided 2026-11-13, an exception to staying inside the column): each card sits a small step down and right of the one below, smaller than in the maintainer's sketch, so many cards fit before they run off the screen. How this works on the phone, where the column is the screen's width, is open (§8).

## 2. Moving through the stack

1. **Interacting with any layer below closes every layer above it.** Clicking a lower card brings it to the front. The search context is the bottom layer: clicking it, or typing in its search bar, closes all cards.
2. **Only clicks and typing count.** Scrolling or hovering over an exposed edge never closes anything.
3. **A note being edited in a card that closes is saved first.**
4. **Following a link to a note whose card is already in the stack** returns to that card and closes those above it (today's path-return rule). A link to the top card does nothing.
5. **Escape closes the top card.**
6. **A later AI reference replaces an AI card on top** instead of stacking a new one, as today.
7. **The browser's Back button does not touch cards** (decided 2026-11-13): Back means going to another page, and MetaList is one page. Cards add no browser history.
8. **Each card has a small `×` in its top right corner** (added 2026-11-13, after the note): a second way out, visible on sight. It closes that card and every card above it, landing on the layer below: the same rule as clicking a lower layer. Every card's top right corner shows, since each sits down and right of the one below, so a lower card's `×` closes several cards at once. A note being edited in a closing card is saved first. Tooltip: `Close` (decided 2026-11-13).
9. **The stack survives a reload.** It belongs to the view, like the view's active search context and scroll, and isn't shared with other views (decided 2026-11-13): each device or browser tab keeps its own stack, and another one opening the vault shows its own search with no cards.
10. The chip, its `←` and `×`, and the magnifier go.

## 3. What a card shows

For each note the card holds:
- **The note and its whole subtree,** fully editable.
- **Its ancestors, greyed and read-only:** readable, so the note keeps its context.
- **Siblings, and siblings of ancestors, as the existing thin grey bars.**

**Clicking anything grey (an ancestor or a bar) opens the whole root note as a new card on top,** fully editable. This is the one-click way to see or edit everything around a linked child.

**No sort or filter controls in a card.** A card is a fixed set of notes, not a query. Cards with several notes use a fixed order:
- **All references:** citation order in the answer (decided 2026-11-13).
- **Referenced by:** most recently edited first (decided 2026-11-13).

## 4. Editing in a card

**Anything inside a linked note's subtree can be edited** as anywhere else: text, tags, children, delete, reorder.

**Nothing may end up outside it.** These are refused:
- adding a root note
- adding a sibling of the linked note or of any ancestor
- outdenting a note out past the linked note
- moving, pasting or dropping a note outside it
- editing or adding next to anything grey

**Each refusal shows a short message** in the style of the existing "New notes cannot be added in this search" banner. Wording (decided 2026-11-13): "Only notes inside the linked note can be added here. Click the grey to open the whole note."

**Enter at the end of the linked note does nothing but show that message.** It would make a sibling, so it's refused. It must not make a child instead: a key never changes meaning in a card, it only refuses.

**A card never adds tags to a note.** It has no search, so nothing is copied, which ends the UUID tags.

Why: notes added inside the linked note are there the next time the link is followed; notes added outside it wouldn't be, which is confusing. "Grey means look, don't touch" is one rule with no exceptions. The root-note card is where to edit the rest.

## 5. What the AI cites

Add to the agent's instructions: **cite the note that makes sense on its own.** If what it found is a grandchild that means nothing without its parent, cite the parent (or the level that carries the context). This is the rule a person follows when writing a link. The note-reading tools already return whole trees (`app/services/agent/agent_tools.py`, `read_view_notes` and `search_view_notes`), so the model can see the right level.

## 6. Existing data

No conversion (decided 2026-11-13): nobody has added notes inside a reference view, so there
are no note-ID tags to remove, and leftover reference-view search contexts are few. Building
cards needs no clean-up step.

## 7. Invariants

1. Following a reference never adds a search context.
2. Nothing done in a card changes the search context underneath, until you interact with it.
3. Interacting with a layer closes every layer above it.
4. A card never gives a note a tag.
5. Every note that can be added or moved in a card stays inside a linked note's subtree, so it shows the next time that reference is followed.
6. Grey is read-only; clicking it opens the whole root note as a new card.
7. A key does the same thing in a card as anywhere else, or nothing with a message.

## 8. Still open

- **How a deep stack looks** (seven cards or more). Not needed to start. One idea: fold older levels into thin strips.
- **The phone:** each card steps past the column's right edge, which is the screen's edge on a phone. Not needed to start on the desktop.

## 9. Checked when filed (2026-11-13)

Filed from the inbox; the `×` addendum is folded into §2 rule 8.

- **Confirmed:** the four kinds and their labels (`REFERENCE_VIEW_KINDS`, `TAB_LABEL_BY_VIEW_KIND`, `reference-source-navigation-service.js:8–24`); the hidden note-ID query (comment at line 47–48, `NOTE_ID_PATTERN`); tab state `referenceViews` (`app/api/note_requests.py`, `app/services/tab_state.py`); `findReferenceLevelOnActivePath()` (used by `keyboard-events.js` `returnToReferenceLevel()`); `copyOriginScope`; `read_view_notes` and `search_view_notes` (`app/services/agent/agent_tools.py`); the "New notes cannot be added in this search" banner (`root-note-creation-service.js`).
- **Not where the note says:** "Reference views" in `docs/ui/references.md` is a bullet list under "Search Semantics", not a heading. It now points here.
- **Not reproduced:** Effect 2 (a new note in a reference view tagged with the linked note's ID). Nothing read stops a note-ID term from being copied as a positive search term (`findUnfillableSearchTerm` skips only property terms), so it is likely. No conversion is needed for it (§6).
- **Replaces built behaviour** documented in `docs/ui/references.md` (the chip, its `←` and `×`, the magnifier that turns a view into an ordinary search, the slide transitions, path return) and tested by `scripts/browser-reference-view-regressions.mjs` (`BROWSER_TEST_SUITE=reference-views`) and `tests/unit/reference_path_return.test.mjs`. Those tests change with it.
- **Interaction principles:** cards opening, closing and landing move things on screen, so before code the cases (open, close by each way out, return along the path, reload, short and tall notes, the phone) and their exact positions are agreed with the maintainer (`AGENTS.md`, "On-screen Behavior Follows the Interaction Principles").
- **Decided with the maintainer 2026-11-13:** Back leaves cards alone (§2 rule 7); the stack survives a reload, per view (rule 9); citation order for All references and most recently edited first for Referenced by (§3); the refusal wording (§4); no conversion (§6); the `×` tooltip `Close` (rule 8).
- **Still open:** how a deep stack looks (§8); not needed to start.

## 10. Cases on screen (agreed 2026-11-13, except the phone)

Cards move things on screen, so each case names the interaction principle it follows
(`docs/ui/interaction-principles.md`) and gets a browser test that checks exact positions.
Numbers are proposals: the step between layers is 12 px down and 12 px right, to be tried on screen.

| # | Case | Expected result |
|---|---|---|
| 1 | Follow a link from a note being edited | The note is saved and leaves edit mode first, as before any layer covers it (6). |
| 2 | The first card opens | At once (decided 2026-11-13). Its top edge sits one step below the search controls and one step right of the column's left edge; it is as wide as the column, so its right edge is one step past the column's. The search context underneath does not move (2). |
| 3 | Each further card | One step further down and right than the card below, the same width, so it reaches one step further past the column's right edge. |
| 4 | Length and scrolling | A card is as long as its notes. The tops of all cards and their labels stay put under the search controls; scrolling moves only the top card's notes, which pass under its top edge as notes pass under the search controls today (decided 2026-11-13). The layers below keep their own scroll positions, their left and top edges showing. |
| 5 | Where the linked note lands in a new card | The card opens scrolled to its top: its greyed parents above the linked note. When the parents are so long that the linked note's first line would be below the window, it opens scrolled so that line sits just below the card's top edge, the parents above it by scrolling up (decided 2026-11-13; 3: the note followed is in sight). The card below keeps its scroll position. |
| 6 | Click something grey (an ancestor or a sibling bar) | The whole root note opens as a card on top, scrolled so the clicked note's line stays at the height it was clicked at, when the card can show it there; otherwise the minimum move to bring it into sight (1, 3). |
| 7 | Scroll or hover anywhere, including over a lower layer's edge | Scrolls the top card's notes, as with the regular list; nothing closes and no lower layer moves (§2 rule 2). |
| 8 | Click an exposed part of a lower layer | Every layer above it closes; that layer is exactly as it was left (scroll, open notes), nothing moves (1, 4). The click only closes; it does not also enter a note or follow a link (decided 2026-11-13). |
| 9 | Click or type in the search bar | Every card closes, and the click or the typed letters go into the search bar as they would without cards. |
| 10 | Close the top card: Escape (not editing), its `×` | The card below, or the search context, is exactly as it was left; nothing moves (1, 4). A lower card's `×` closes it and everything above. |
| 11 | Escape while editing in a card | Leaves edit mode only, as anywhere (invariant 7); a second Escape closes the card. |
| 12 | Close a card while one of its notes is being edited | Saved first, then closed (§2 rule 3). |
| 13 | Return along the path (a link to a note whose card is open below) | Cards above that card close; it is exactly as it was left (1). A link to the top card does nothing. |
| 14 | A later AI reference with an AI card on top | Replaces that card in the same place, laid out as case 5 (§2 rule 6). |
| 15 | Back on the search context after editing in cards | It looks exactly as it did, minus the cards (decided 2026-11-13). The one difference: a note edited in a card that also shows in the search shows its new text there, with the first note in view keeping its height (1) and no highlight (5). |
| 16 | Reload | The same cards come back, each at its scroll, in this device or tab only (§2 rule 9). |
| 17 | Narrow window and phone | Open (§8): stepping past the column's right edge runs off a phone's screen. |
| 18 | Short and tall linked notes; parents that do or do not fit in the window | Covered by cases 4 and 5, each tested. |
