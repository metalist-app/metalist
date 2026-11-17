# Several views at once: one editor per root note

**Status:** Built 2026-11-14 and 2026-11-15, all five steps (§10; each step's cases and what was built under "Step N's cases"); moved from `docs/ready-to-build/` to the design docs then. Agreed with the maintainer 2026-10-26; the build order (§10) approved 2026-11-14. **Decided 2026-11-14:** the list of search contexts is shared by every tab and device (§2, §10), and so is the AI conversation, one per vault (§5; replaces one per view).
**Scope:** let MetaList be open in several places on one vault at the same time (two browser tabs, a browser tab and the phone, later apps) instead of one session per vault. Each place has its own independent screen; editing is locked **per root note**. Update the permanent docs (`docs/ui/state-handling.md`, `docs/design/differential-view-protocol.md`, `docs/ui/ai-chat.md`, `docs/security/README.md`, `docs/ui/phone.md` and wherever "one active session" is stated) with the result.

Written without running the code. Every code reference below came from reading it and must be checked before relying on it; build only what's missing.

---

## 0. Terms used in this note

- **View:** one client looking at a vault: a desktop browser tab, a second browser tab, the phone, a future app. Several views can be open on one vault at once. *The code already uses "reference view" for something else (Source note / Reference / All references tabs); choose code names that don't collide, for example "client".*
- **Search context:** what the interface calls a **tab** (a search plus its sort and other options). This note uses "search context" to keep it apart from browser tabs. Renaming the interface's "tabs" is **not** part of this change.

## 1. Today (to verify)

- **One active session per vault.** Issuing a token clears the vault's earlier tokens, so signing in in a second browser tab or on the phone logs the first one out (`docs/security/README.md`, `tokens.py`, "one active browser tab/session per namespace").
- **Tab state is per vault:** `app/services/tab_state.py` stores one `activeTabId`, `tabOrder`, and per-tab search, scroll and sort.
- **Browser identity:** each browser tab keeps an opaque ID in `sessionStorage` that survives a reload (`docs/ui/state-handling.md`).
- **Per-note lock machinery exists but looks unused:** `acquire_note_lock` / `release_note_lock` / `get_all_locks` in `app/services/sync.py` (a note→client map that views already receive as `locks`); a client unheard from for `CLIENT_IDLE_SECONDS` (30 minutes by default) is forgotten and its locks dropped. Outside `sync.py` only a unit test calls `acquire_note_lock`.
- **Collapse is saved on the note** (`is_collapsed`), shown in embeds and exports.
- **AI chat transcript** lives in server memory, keyed by the session token hash (`docs/ui/ai-chat.md`). With one session per vault, that is one conversation per vault.
- **Order** is a linked list (`parent_id` / `prev_id` / `next_id`); writes run one at a time.
- **Sorted tabs keep the edited root in place** (`keep_edited_root_in_place`, `docs/design/differential-view-protocol.md`).
- **Leaving a note saves it and ends edit mode** (switching search context, opening a modal).

## 2. Views are independent

- **Every view stays signed in.** Signing in on one no longer logs out another. *Not decided here:* what locking the vault, signing out or changing the password in one view does to the others. Propose it, keeping it at least as safe as today.
- **Shared across views:** the **set** of search contexts (create, rename, reorder, delete), so a new view starts with all of them, never blank. *Reopened 2026-10-28; decided shared 2026-11-14, every browser tab and device alike (§10).*
- **Per view, surviving a reload of that view:**
  - which search context it is showing
  - its scroll position (never synced: layouts differ)
  - the selected note and edit mode
  - **its reference pages** (decided 2026-11-14): following a link is moving around, "almost akin to scrolling" (the maintainer). Each view has its own path of pages and its own ◀ ⏮ ▶; a search context's row reads `miscellaneous > Source note` only in the view that is on that page. Another view showing `miscellaneous` is not pulled along.
  - **whether the folder tree shows** (decided 2026-11-14): a panel, not what the notes are; the phone never starts on it, and opens it as a screen of its own (`phone-same-app.md` §5a).
- **Shared by every view** besides the list of search contexts: each search context's search, sort order, date range, Files filter and Untagged setting, which decide what notes it shows.
- **A brand-new view starts on the search context used most recently.**
- **How a view keeps its identity:** the existing per-tab ID in `sessionStorage` (separate per browser tab, survives a reload, cleared when the tab closes); the installed phone app uses its own storage the same way. **Only the random ID is stored on the client;** the view's state (search terms reveal tag names) stays on the server, encrypted like tab state today. State for views not seen again expires after a period of inactivity.
- **Shared, live on every view:** the notes as each save lands (the server already pushes small updates), and collapse state (§4).

## 3. Editing: one editor per root note

- **The lock is per root note.** Entering edit mode anywhere inside a root note (the root or any descendant) locks **that whole root** for every other view. No reasoning about which children or siblings an action touches: the root is the unit.
- **The lock covers the root's own content and tags, its children at any depth, and its collapse state** (§4). Every change to those from another view is refused while the lock is held, including small ones such as ticking a checkbox. **Deleting a locked root** from another view is refused too.
- **Moving a locked root is allowed** from another view (drag, move up or down, to the top or the end). *Why:* position is relative: with A locked, moving B in front of A and then C in front of B puts A at the end anyway, so blocking A's own moves protects nothing and blocking neighbour moves would freeze the list.
- **Neighbours of a locked root can change:** adding a root next to it, or moving a note next to it, rewrites its `prev_id` / `next_id`; that is not an edit of the locked root.
- **The editing view never sees its note jump.** When another view moves the locked root or changes its neighbours, the editing view applies the change live but keeps the edited root at the same height on screen while the list rearranges around it (as `keep_edited_root_in_place` does for sorted tabs); when editing ends, the note shows in its new place.
- **Everything else is open:** different views edit different roots at the same time, add notes, and see each other's saves live.
- **Ordering is unchanged:** linked lists, with the server applying changes one at a time in arrival order. Do not replace the linked-list ordering.

### 3.1 Lock lifecycle

- **Taken** when a view enters edit mode inside a root.
- **Released** when edit mode ends (leaving a note always saves and ends editing, as today, so no lock is left behind in a search context nobody is looking at).
- **Lease:** a lock lasts **while its view stays connected**, and lapses **shortly after the view stops being heard from** (a closed tab, a phone asleep, a lost connection): about a minute or two, matched to how often views check in; tune it. **No idle timer** for "no typing for N minutes": it would pull the lock from someone pausing mid-sentence.
- **Marker:** a root locked elsewhere shows a small marker on that note only, for example "Editing on your phone." It names where (desktop, phone, another tab). Nothing else on the page freezes or moves.
- **Takeover: one click, no button** (maintainer, 2026-11-15; first built as a second tap on a **Take Over** button). Clicking a root locked elsewhere takes it over: whoever clicks it wants it. The other view saves its typing and leaves edit mode (anything it couldn't save is shown there for copying, never lost), then the click does what it would have done: a click in the text edits there; a click on the fold arrow, a checkbox and so on makes that change, and neither view edits the root afterwards.
- A forgotten open edit (a tab left in edit mode overnight) is still connected and keeps its lock; a click takes it over.

## 4. Collapse is shared

- **Collapse stays saved on the note, shared by every view** (as today). Collapsing something on the phone folds it on the desktop too, live; the desktop holds its reading position through the update, so the screen doesn't jump.
- **Collapsing or expanding inside a root locked by another view is refused,** like any other change: collapsing the parent of the note being edited would fold away the text under the other person's cursor. The marker says why.

## 5. The AI conversation: one per vault, shared by every view

**Decided 2026-11-14** (replaces "one per view", decided 2026-10-28; §10 keeps both). "View" means a browser tab or the phone, never a search context.

1. **One conversation per vault,** as since 2026-11-11 (`docs/ui/ai-chat.md`, "Saved with the vault"): saved in the vault, kept through a restart, an upgrade, logging out and locking. **Only Clear Chat ends it,** from any view, for every view.
2. **Every view shows it,** live: a question or an answer from one view appears in the others as it is written (build step 3's live changes).
3. **Each Send uses the scope of the view that sent it:** its search and the notes it shows at that moment, as today. A conversation follows no search context; the search may change between questions (the maintainer refines the search partway through, 2026-10-28).
4. **One answer at a time.** A Send from another view while an answer is being written waits its turn; its question shows in every view meanwhile. Stop stops the answer being written, from any view.
5. **No conversation history list** (unchanged). Keeping an answer is still Copy Response and pasting it as a note. A future option: several kept conversations to choose from, as chatbots' web versions have (`docs/future-plans/ai-conversations.md`, 2026-11-14).

**Why** (the maintainer, 2026-11-14, the same reason as the shared search contexts, §10): a browser tab lives too briefly to own a conversation. Open tab X and start a conversation, open tab Y and start another, then close Firefox: both are lost, worse than losing one to an upgrade, which the conversation is saved to prevent. Kept conversations tied to tabs would need a history list to reach them again, since a new tab has no identity to find its own by.

**The change:** the transcript is already the vault's (`app/services/ai_chat.py`); what the change adds is views seeing it live and answers queuing across views. Clear clears it for every view. Lock, sign out and restart keep it, as today.

## 6. Security review

Removing "one active session per vault" changes assumptions recorded elsewhere. For example, `docs/security/cloud-privacy-boundary.md` relies on "signing in ends every other session" to argue that nothing can make a note private while the export dialog is open in another session. **Find every argument that relies on a single session, and re-check each one** under several views (a note made private in one view while another view has a dialog open, a bulk run in one view while another edits, and so on). Record the outcome in `docs/security/`.

## 7. Invariants

1. Two views never edit the same root note at once; the root note is the unit of locking. A locked root can be moved but not deleted.
2. Every view is independent in where it is (its search context, scroll and selected note); the notes, collapse state, the list of search contexts and the AI conversation are shared.
3. A lock never expires under a connected view, and taking one over never loses typing.
4. Linked-list ordering is unchanged; the server applies changes in arrival order.
5. The note being edited never jumps on its editor's screen.

## 8. Tests (at least)

- Two browser tabs signed in together; neither logs the other out.
- Each tab keeps its own search context and scroll across a reload; a new tab opens on the most recently used context with every context present.
- Editing a child in tab 1 locks its whole root in tab 2: the marker shows there; moving the root and adding neighbours succeed, and tab 1's edited note stays at the same screen height.
- The lock lapses shortly after tab 1 closes or disconnects, and never while it stays connected and idle.
- A click in that root in tab 2 takes it over: tab 1's typing is saved and it leaves edit mode, then tab 2 edits where clicked, or makes the change clicked (collapse, a checkbox tick).
- AI (§5): two tabs show one conversation, and a Send in one appears in the other as it is written; a new tab opens on it; closing every tab and the browser keeps it; each Send uses the scope of the tab that sent it; a Send from a second tab while an answer is being written waits its turn and shows in both meanwhile; Stop from either tab stops it; Clear Chat in one clears it for both.
- Order stays consistent under interleaved adds and moves from two tabs.

## 9. Checked 2026-10-27 (filed from the inbox)

- Confirmed: token issuance clears the vault's earlier tokens (`app/services/tokens.py`, `self.tokens.clear()`; `docs/security/README.md`, "one active browser tab/session per namespace"); `app/services/tab_state.py`; the per-tab ID kept in `sessionStorage` (`docs/ui/state-handling.md`); `acquire_note_lock`, `release_note_lock` and `get_all_locks` in `app/services/sync.py`, the client forgotten after `CLIENT_IDLE_SECONDS`, with `acquire_note_lock` called only from `tests/unit/test_next_batch.py`; views already receive `locks` (`app/api/routes/notes.py`); `keep_edited_root_in_place` (`app/services/snapshot.py`); the AI transcript keyed by the session token hash (`docs/ui/ai-chat.md`); `docs/security/cloud-privacy-boundary.md` exists.
- **Correction:** "the installed phone app" is a home-screen web app (`app/static/manifest.json`, `display: standalone`; `docs/ui/phone.md`), not a native app. It keeps a `sessionStorage` of its own, but the phone may clear it when the system ends the app, so the phone could come back as a new view, on the most recently used search context rather than its own.
- **The installed phone app keeps its view ID in `localStorage`** (maintainer, 2026-10-27):
  - Only when running standalone: detect it with `matchMedia('(display-mode: standalone)')`, plus `navigator.standalone` on iOS, and verify both on the phones tested. It has one window, so no two views share the ID, and a phone ending the app in the background should not lose the user's place.
  - Browser tabs, on the desktop or the phone, keep the per-tab ID in `sessionStorage` as now: `localStorage` is shared by every tab of the site, and closing a tab is deliberate.
  - One view ID per vault, so switching vaults keeps each vault's own state.
  - An inactive view's state expires after weeks, not hours; once it has expired, starting on the most recently used search context is fine.
  - Only the random ID is on the device; the state stays on the server, encrypted.
  - Tests: end the installed app from the app switcher and reopen it: same search context and scroll. Two desktop tabs get different IDs. A phone browser tab closed and reopened starts on the most recently used context. Switching vaults in the installed app keeps each vault's context.
- **Lock, sign out and password change across views** (maintainer, 2026-10-27):
  - **Locking the vault locks every view.** Lock ends access to the vault's key, so each view saves its typing first (acknowledged saves, as for any shutdown), then shows the lock screen; every edit lock ends with it.
  - **One Log Out command, with a "Sign out every device" checkbox** (decided 2026-11-14, replacing a separate Lock Vault): unticked, it signs out this device; ticked, every device, which in a vault with a password locks it (the last sign-in gone, the key goes).
  - **Signing out is per device, not per tab.** Every tab in that browser (or the installed app) signs out, since they share the sign-in; other browsers and the phone stay signed in. Typing is saved first and that device's edit locks are released. The vault stays unlocked for the other devices.
  - **Changing the password signs out every other device** and keeps the one it was changed on: a common reason to change it is suspecting someone else has it. Their typing is saved first, then they show the sign-in screen.
  - Tests: lock in tab 1, and tab 2 and the phone save their typing and show the lock screen, with no edit locks left. Sign out in tab 1, and tab 2 in the same browser signs out while another browser and the phone keep editing. Change the password in tab 1, and tab 1 stays signed in while every other browser and the phone save and sign out.
- **The phone will edit** (maintainer, 2026-10-27), so the lock, the marker and taking over (§3.1) cover it like any view. Today it is read-only plus capture (`docs/ui/phone.md`); the design that makes it edit is `docs/ready-to-build/phone-same-app.md`, built with or after this note. Edits from the phone are refused only for a root another view has locked; the server refuses phone clients only the routes that note trims (the ontology editor, rules, vaults, reminders, AI settings).
- As the note asks: propose a build order before starting.

## 10. Discussed 2026-10-28

### The AI conversation: one per view (2026-10-28), replaced by one per vault (2026-11-14, §5)
- **One conversation per vault (§5) is in doubt.** A conversation only makes sense with the search it was asked in, and a different view usually shows a different search.
- **One conversation per search context: rejected.** The maintainer often refines the search partway through a conversation and keeps asking; tying the conversation to a search context breaks that.
- **Leaning towards one conversation per view,** as today's one per sign-in but per view: it follows that view as its search changes or it switches search contexts, and each Send uses what the view shows then. Views never share a conversation, so "one answer at a time" across views (§5) would go, and so would continuing a conversation on another device.
  - The trade-off: a browser tab's view is forgotten when the tab closes (its ID is in `sessionStorage`), so closing a tab would end its conversation; a reload keeps it. Today the transcript is keyed by the browser's sign-in (`token_service.get_session_key`), so it survives closing the tab. The installed phone app keeps its view (§9), so its conversation survives the app being ended.
- Build the AI step last (step 5).
- **Replaced 2026-11-14 by one conversation per vault, shared by every view** (§5). The tab-local conversation contradicted keeping the conversation with the vault (agreed 2026-11-08, built in 0.28.0: "customers would be furious to lose a conversation to an upgrade"), and the maintainer's example settled it: tab X starts a conversation, tab Y another, Firefox closes, both are gone.

### The list of search contexts: shared (decided 2026-11-14)
- The maintainer wasn't sure the set of search contexts had to be shared; a new view should still open on the one used most recently.
- For keeping it shared: a browser tab's view is forgotten when the tab closes, so search contexts set up in a tab would disappear with it, and the phone wouldn't see those made on the desktop. Each view still shows its own search context either way.
- **Decided 2026-11-14: shared by every browser tab and device.** The hard case was never desktop against phone but two browser tabs. The maintainer's example: two tabs, their lists diverged, both closed; the next day a new tab signs in. It has no identity of its own (a tab's ID dies with it), so it could only take the most recently used tab's list (the other's contexts silently gone), merge both (the lists were never really separate) or ask which (a question about forgotten tabs at every sign-in). Each loses work or turns back into one shared list: a browser tab lives too briefly to own anything worth keeping, and a list of search contexts is kept.
- **So:** shared and kept per vault, the list of search contexts (create, rename, reorder, delete anywhere shows everywhere). Per view and short-lived, only its place: which search context it shows, its scroll, the selected note; losing that with a closed tab costs nothing, and a new view opens on the search context used most recently. Two tabs can still show different searches side by side, chosen from the same list. The phone follows the same rule, with no special case.

### Proposed build order (not yet approved)
Checked against the code first: the browser's sign-in is a per-vault cookie (`app/api/request_auth.py`), one tab at a time claims it (`claim_token_for_tab`, `X-Metalist-Claim`; a second tab shows "Session locked / Take Over"), and `create_token` clears every other token (`app/services/tokens.py`). Views learn of no change made elsewhere: the status poll (`polling-service.js`) refreshes only for sign-in, connectivity and link-title revisions, and hidden tabs skip it. Warm views (`(clientId, tabId)`) and undo stacks (`undo_state.py`, per client) are already per browser tab. The per-note locks in `sync.py` are unused.

1. **Several sign-ins:** every tab and device stays signed in; the session Take Over screen goes; lock, sign out and password change as in §9; the security review (§6). Until step 4 two views could edit the same note: for trying, not real work.
2. **Each view its own screen:** its own search context, scroll and selection across a reload; a new view on the most recently used context; the installed phone app's ID in `localStorage` (§9).
3. **Live changes from other views:** saves, moves and collapse arrive without a reload, and what the user is looking at doesn't move. A case list is agreed first (`docs/ui/interaction-principles.md`).
4. **Root-note edit locks:** server-side refusals, moves allowed, the marker and Take Over (§3). A case list is agreed first.
5. **The AI conversation,** one per vault, shared live by every view, one answer at a time (§5).

Step 3 comes before 4 because markers and Take Over need views to see each other's changes live.

### Step 2's design (2026-11-14)
- **The view is the browser tab's ID** (`X-Metalist-Tab-Id`, kept in `sessionStorage`); the installed phone app keeps its own in `localStorage` (§9). Every tab-state call names it.
- **One store, two parts** (`tab_state.py`): shared, the search contexts (their order, search, sort, date range, Files filter, Untagged); per view, a place: the context shown, the scroll in each context, its reference pages, whether the folder tree shows, and when it was last used. A new view starts on the context used most recently by any view. A view not seen for weeks is forgotten with its pages.
- **Reference pages belong to the view that opened them:** created as pages (`isPage`), never listed or sent to another view.
- **A view's save changes only what it changed:** for each shared field the store remembers what it last told that view; a value equal to that is no change (another view may have changed it since), a different one is this view's change. So a view's scroll save never puts back a search another view changed.
- **State saved by 0.30.0** (one place, no views): its place goes to the first view that asks, so the one device used before keeps its context, scroll and pages. A tab of note ids no record claimed (an orphaned page 0.29.0 left) is that view's page too, and when every tab is a page an empty search context is added in front of them.
- **Known limit:** a browser's Duplicate Tab copies `sessionStorage`, so the copy starts as the same view and the two share a place. Not handled yet.

### Step 3's cases (agreed 2026-11-14)
Principles 1, 2 and 5 (`docs/ui/interaction-principles.md`). Each case gets a browser test of exact positions; cases that work today are tested against the unchanged code first.
1. Another view's save, add, delete, move, collapse or expand shows at once in a tab of the same browser (the tab that changed it tells the others, `views-in-this-browser.js`, 2026-11-15), within a second from another browser and within 2 seconds on a phone (the status check, `status-check-interval.js`: the maintainer, 2026-11-15; first 5 s, then 2 s); a hidden tab catches up when shown.
2. A change above the window (a note grows, shrinks, is added, removed or folds): nothing on screen moves; the note at the window's top keeps its height.
3. A change to a note in view: it redraws in place, its top fixed; the notes below shift by its change in height.
4. A change below the window: nothing visible.
5. The note at the window's top deleted or moved elsewhere: the note below it takes its place at the same height.
6. While editing: the edited note, caret and typing never move; everything else changes around it. Moved by another view (step 4), it keeps its height here and takes its new place when editing ends.
7. A note that stops matching this view's search leaves and the notes below close up; one that starts matching appears in its place in the order.
8. No highlight, flash or extra animation: it is the user on another device.
9. While scrolling, a change waits until the scroll stops.
10. While dragging a note, or a menu, a dialog or Find (Cmd+F) is open, a change waits and applies when it closes.
11. Another view adds, deletes, renames or reorders a search context: the tab row updates at once; the context shown stays.
12. Another view deletes the context shown here: this view moves to the neighbour, as a delete here does; typing is saved first.
13. Another view changes the search, sort, date range, Files filter or Untagged of the context shown here: the search box shows it and the list shows the new results from the top, as if typed here. **Amended by the maintainer:** whichever view starts editing a context's search locks that context's search for the other views (built with step 4's locks). Why: otherwise two views typing in one search have no sensible result. Agreed 2026-11-14: taken by the first keystroke that changes the text; the other views showing that context can't type in their search boxes, see a marker naming where the search is being typed, and follow the typing live (a search runs as it is typed); released 5 seconds after the last keystroke that changed the text (the maintainer: not only when the cursor leaves the box), or at once when it leaves the box or the view stops being heard from. With a 5-second release it needs no Take Over. Sort, date range, Files and Untagged stay unlocked (one click each, shown everywhere at once).
14. A change to a context not shown here only updates its label in the tab row.
15. The folder tree, when shown, updates as tags change.
16. Reference pages follow the same rules as any list.
17. Undo after another view's change: "Nothing to undo: notes were changed on another device." (step 1).
18. The phone follows the same rules.

**Built 2026-11-14.** The status a view polls carries `notes_revision` and `search_contexts_revision` (`tab_state.py`, `shared_revision`: it rises only for what every view shares, not a view's scroll or place; counted per view since 2026-11-15, with only the searches the other views are typing, because a view's own search lock made it take the contexts again a second after each click into or out of its search box); each view answer carries the `notesRevision` it shows. `live-changes-service.js` refreshes the notes holding the note at the window's top (`captureWindowTopNote`, a `window-top` hold: moved away or deleted, the note below it takes its place, no higher than just under the search controls) or the edited note's caret, with no animation, and takes the contexts again (`adoptSharedSearchContexts`, `keyboard-events.js`). It waits for a command, a dialog, a menu, Find, a drag, a search being typed and 300 ms after the last scroll, and a save of the view's tabs that leaves a tab out keeps that tab (`tab_state.py`, `update`: the tabs are the server's, and only `delete_tab` takes one away; 2026-11-15, a save raced the view's own new tab and was refused, and 2026-11-17, a save after a typed search left out another view's new context). What stays still is captured when the refresh lands, so a scroll made while it fetched stays; a search typed into the box while the contexts were fetched stands too, and runs as typed (`adoptSharedSearchContexts`; 2026-11-15, the box was cleared while they were fetched after an AI answer and the list kept the old search under an empty box); and it moves no focus: when the edited note does not hold it (a floating note, the search box), focus stays where the user put it (`leaveFocusElsewhere`). Browser suite `live-changes` (Chrome and Firefox) checks cases 2, 3, 5, 6, 7, 9, 10 (a dialog), 11, 12 and 13; `tests/unit/live_changes_service.test.mjs` the revisions and waits.
- **Not yet:** case 6's second half (the edited note moved by another view keeps its height until editing ends) comes with step 4, where moving a locked root is allowed. The search lock (case 13's amendment) comes with step 4 too.
- **Found while building:** step 2 marked a blank search context as a page and a reference page as a search context (`duplicateTabContext` / `openBlankSearchContext` passed `isPage` the wrong way round); and the store took a save's answer as what the browser holds, so a view's second save put back a search another view had changed (`tells_searches`, `tests/unit/test_view_places.py`).

### Step 4's cases (agreed 2026-11-14)
"Mac" is the view editing, "phone" any other view (another tab alike).
1. Clicking into any note inside root R on the Mac (R or anything under it) locks all of R for every other view; ending the edit releases it (Escape, a click elsewhere, switching contexts, opening a dialog). Switching to a note under another root moves the lock.
2. Lease: the lock holds while the Mac keeps checking in, even with no typing; hidden tabs check in about once a minute; it lapses about 3 minutes after the Mac was last heard from.
3. Marker: R shows a pencil on its top-left corner (moved from the top right and enlarged, 2026-11-15: seen sooner there); its tooltip says where it is being edited ("in another tab", "on your phone", "on another computer"). Nothing else moves.
4. A tap anywhere in R takes it over at once (changed 2026-11-15: at first the tap opened the marker into "Editing on your Mac · Take Over", and only that button took it over).
5. Taking over waits for the Mac to save the typing and leave edit mode (R at the same height, a floating "Editing moved to your phone"; anything it could not save stays there for copying), then starts editing where tapped.
6. A change to R from the phone is refused by the server, which takes R over and sends the change again: editing R or anything under it, a checkbox tick, collapse or expand, accepting tags, deleting, pasting, dragging a note into or out of R, indenting into R, an undo that would change R. Once made, the phone does not edit R either: neither view holds it, and the Mac says "Editing ended: changed on your phone" (not "moved"). Refused again (a third view took it meanwhile): a calm message says where R is being edited.
7. Allowed: moving R itself (drag, up or down, top, bottom), adding notes next to it, moving other notes beside it, reading, scrolling, searching, copying.
8. Changes to many notes at once that would touch R (deleting what the view shows, Rename Tag, Alphabetize, AI tagging) are refused as a whole: a message names where R is being edited and says to try again after.
9. On the Mac: the phone moving R keeps R at the same height while the list rearranges; when editing ends R goes to its new place and the note that took its spot stays where the user looks.
10. Search lock (case 13 of step 3): the first keystroke that changes a context's search locks it for the other views showing that context: their search boxes cannot be typed in, show a marker and follow along live; it ends 5 s after the last keystroke, or at once when the box is left.
11. Lock Vault, Sign Out, Change Password: each view saves its typing first, then its locks end (§9).

**Built 2026-11-14.** Server: `app/services/edit_locks.py` holds the locks (in memory); every note write checks them (`require_writable`, `require_links_writable`, `require_parent_writable` in `app/db/notes_sql.py`), so every route, undo included, is covered with no route of its own; a refused request is rolled back whole (`request_recovery.py`), which is case 8's "refused as a whole". A view says what it edits in each status check (`X-Metalist-Editing`; a hidden tab editing a note keeps checking) and each view request; `lockedRoots`, `editLockRefused` and `editedRootMovedElsewhere` come with every view answer; taking over is `POST /notes/edit-lock/take-over`, asked again until the other view has saved and left (or 5 s passed): a click in the text asks it before editing (`takeOverInsteadOfEditing`, `edit-lock-service.js`), and a refused change asks it and is sent once more (`api-client.js`; changes to the whole view are not, case 8), then the view's status check lets the root go. A root moved by another view while edited is kept in place by `keep_edited_root_in_place`, as in sorted tabs. The search lock is taken by a view's tab-state save that changes a search and released by `POST /notes/tab-state/search-lock/release` when the box is left; `searchLocks` comes with every tab-state answer and is part of the shared contexts' revision, so the others see it start and end. Browser suite `edit-locks` (Chrome and Firefox): cases 1, 3 to 10; `tests/unit/test_edit_locks.py` the rules, the lease, the handover and sign-out.
- **Where:** "on another computer" covers another browser on the same computer too (the server cannot tell them apart).
- **Not yet:** case 11's "saves its typing first" for the other views when the vault locks or the password changes is as before step 4 (they find themselves signed out); their locks end. Changes an AI answer makes while it streams are not checked (the request's view is gone by then): step 5.
- **Found while building:** the server forgot what each view held of the searches whenever it loaded its state again (after a refused change, a restart), so a view could not change a search until it loaded its tabs; it is now saved with the place, and a view with no record takes its change (`tests/unit/test_view_places.py`).

### Step 5's cases (agreed 2026-11-14)
"Mac" sends, "phone" is any other view (another tab alike).
1. The Mac's question and its answer appear on the phone as they are written: within about half a second while an answer is coming, otherwise at the 2-second check. The phone's chat panel never opens by itself (principle 2).
2. The phone scrolled to the end of the chat follows the answer as it grows, as the sending view does.
3. The phone scrolled up, reading: nothing moves; new text goes below (principle 1).
4. The compact Working indicator (phase, time) shows in every view while an answer is written; with the eye on, the detail panels too.
5. ~~The composer's typing stays in its own view.~~ Replaced by case 11.
6. A Send from the phone while the Mac's answer is written: the phone's question shows at the end in every view, marked waiting, and is answered as soon as the first answer ends, in the order sent, with the phone's scope at Send.
7. Stop, from any view, stops the answer being written; a waiting question then starts.
8. Clear Chat, from any view, stops the answer being written, drops waiting questions and empties the chat everywhere.
9. A question the AI asks (a confirmation card, which notes to tag) can be answered from any view; the first answer counts.
10. The AI's working state is the vault's, not each sign-in's: a key entered for the session (vaults without a password), the web pages it opened, summaries, the debug trace. Signing out one device no longer clears them; the last sign-in's end does, as today.
11. **Composer lock** (the maintainer, 2026-11-14, as the search lock): typing a question on the Mac locks the AI message box for the other views: they show the Mac's text as it is typed and cannot type in it. The lock holds while the Mac's cursor is in the box, however long it pauses, and ends on Send, on leaving the box, or when the Mac stops being heard from.

**Step 5 built 2026-11-15.** `GET /ai/chat/live` (every half second while an answer is written, a question waits or is typed, or the AI asks one; every 2 s otherwise; not while hidden) gives each view the chat's mark (`ai_chat.live_mark`: it changes with what the chat shows; a chat nobody used yet has an empty chat's mark, so the history meter's read, which starts it, changes none: 2026-11-15, every view loaded the chat again a second after it opened), the questions waiting, whether an answer is written, the AI's question and another view's typing; a changed mark loads the chat again, keeping the Thinking and References opened here, and a view whose own question waits keeps it at the end. A Send joins the queue (`ai_chat_live.py`) once its answer is streamed (`{"type": "waiting"}` while behind another), so a response never read leaves nothing in front. `POST /ai/chat/stop` (with `drops_waiting` for Clear Chat) cancels the answer's task, which ends as `{"type": "stopped"}` and is saved as cancelled; Clear is refused while an answer runs, so the browser stops first. The AI's question is shown in every view from the live state (`showConfirmationCard`, `showScopeQuestionCard`); answered anywhere, the other cards go. The composer lock is `PUT /ai/chat/composer` and `POST /ai/chat/composer/release`, held with the edit locks (same lease and "where"). The AI's working state is the vault's (`tokens.get_session_key`, `VAULT_AI_SESSION_KEY`). The scripted AI used by tests takes `chunk_pause_seconds`, so an answer takes time to write. Tests: `tests/unit/test_ai_chat_live.py`, `test_ai_routes.py` (a second Send waits and the first is written whole), `test_edit_locks.py` (the composer), browser suite `shared-ai-chat` (Chrome and Firefox): cases 1, 6, 7, 8, 11.
- **Not covered by a browser test:** case 9 (the AI's question in another view) is built but checked only in its parts; a browser test needs a scripted AI run that asks for a confirmation.
- **Found while building:** a question queued at Send whose answer stream never ran would have blocked every later answer (queued when the stream starts now); a live reload landing after this view's own Send replaced that turn on screen (dropped now); the stream checker refused the new event types.

### Undo across views (decided 2026-11-14)
- **Each view's undo history builds from its own edits; any change to the notes from another view empties it,** whatever note it touched, as switching search contexts does today. Counted: edits, adding, moving, deleting, collapsing or expanding (collapse is saved on the note). Not counted: MetaList's own background work (a link's title, a file's text) and anything done in this view, its AI actions included. Undo or Redo then changes nothing and a floating message says why: "Nothing to undo: notes were changed on another device."
- Why: undo put back a step's "before" state blindly, so after another device's change it would overwrite that change, or stop with a red error on a move. MetaList is not for collaborators; editing on two devices at once is the exception (the maintainer), so losing undo then is fine. Built with step 1, since it costs nothing there.

### Not in the note, proposed
- **Idle timeout:** each sign-in times out on its own (as each token does today), so one idle device signs out without touching the others.
- **Hidden tabs:** they need a light heartbeat so their edit locks don't lapse; browsers slow hidden tabs' timers to about once a minute, so the lease must outlast two or three missed beats.
