# Several views at once: one editor per root note

**Status:** Agreed with the maintainer 2026-10-26. Ready to build. A large change: please propose a build order (and a split into steps, if that helps) before starting.
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
- **Shared across views:** the **set** of search contexts (create, rename, reorder, delete), so a new view starts with all of them, never blank.
- **Per view, surviving a reload of that view:**
  - which search context it is showing
  - its scroll position (never synced: layouts differ)
  - the selected note and edit mode
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
- **Takeover: two taps, no dialog.** Clicking or tapping a root locked elsewhere does **not** start editing; it shows the marker with a **Take Over** button. Taking over makes the other view save its typing and leave edit mode; anything it couldn't save is shown there for copying, never lost. *Why two taps:* phone taps are often meant to read or scroll, and a stray tap must not throw another screen out of edit mode. *Why no dialog:* the button sits on the note's own marker, so nothing interrupts and nothing moves.
- A forgotten open edit (a tab left in edit mode overnight) is still connected and keeps its lock; Take Over covers it.

## 4. Collapse is shared

- **Collapse stays saved on the note, shared by every view** (as today). Collapsing something on the phone folds it on the desktop too, live; the desktop holds its reading position through the update, so the screen doesn't jump.
- **Collapsing or expanding inside a root locked by another view is refused,** like any other change: collapsing the parent of the note being edited would fold away the text under the other person's cursor. The marker says why.

## 5. The AI conversation: one per vault

- **One conversation per vault, shared live across views.** Start a question at the desk, continue it from the phone. It must not be tied to one view, since a view's ID is cleared when its browser tab closes. (Today the transcript is keyed by the session token hash; with several sessions it needs a vault-level key.)
- **Each Send uses the search context of the view it was sent from,** exactly as a Send captures the active search context today.
- **One answer at a time.** While an answer is being written, other views can type, but **Send waits**, with a status in the chat's status line saying where the answer is being written (for example "Answering from your desktop…"); nothing in the layout moves. When the answer finishes, Send works again and the typed message is still there. *Why not a queue:* a queued question would be answered after an answer its sender hadn't read, against a context captured earlier.

## 6. Security review

Removing "one active session per vault" changes assumptions recorded elsewhere. For example, `docs/security/cloud-privacy-boundary.md` relies on "signing in ends every other session" to argue that nothing can make a note private while the export dialog is open in another session. **Find every argument that relies on a single session, and re-check each one** under several views (a note made private in one view while another view has a dialog open, a bulk run in one view while another edits, and so on). Record the outcome in `docs/security/`.

## 7. Invariants

1. Two views never edit the same root note at once; the root note is the unit of locking. A locked root can be moved but not deleted.
2. Every view is independent in what it shows; the notes, collapse state and AI conversation are shared.
3. A lock never expires under a connected view, and taking one over never loses typing.
4. Linked-list ordering is unchanged; the server applies changes in arrival order.
5. The note being edited never jumps on its editor's screen.

## 8. Tests (at least)

- Two browser tabs signed in together; neither logs the other out.
- Each tab keeps its own search context and scroll across a reload; a new tab opens on the most recently used context with every context present.
- Editing a child in tab 1 locks its whole root in tab 2: edits, checkbox ticks, collapse and delete are refused there with the marker; moving the root and adding neighbours succeed, and tab 1's edited note stays at the same screen height.
- The lock lapses shortly after tab 1 closes or disconnects, and never while it stays connected and idle.
- Take Over: first click shows the button and doesn't edit; the second takes the lock; tab 1's typing is saved and it leaves edit mode.
- AI: a Send from tab 2 while tab 1's answer is being written waits with the status; the conversation shows in both; each Send uses its own view's context.
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
  - **Signing out is per device, not per tab.** Every tab in that browser (or the installed app) signs out, since they share the sign-in; other browsers and the phone stay signed in. Typing is saved first and that device's edit locks are released. The vault stays unlocked for the other devices.
  - **Changing the password signs out every other device** and keeps the one it was changed on: a common reason to change it is suspecting someone else has it. Their typing is saved first, then they show the sign-in screen.
  - Tests: lock in tab 1, and tab 2 and the phone save their typing and show the lock screen, with no edit locks left. Sign out in tab 1, and tab 2 in the same browser signs out while another browser and the phone keep editing. Change the password in tab 1, and tab 1 stays signed in while every other browser and the phone save and sign out.
- **The phone will edit** (maintainer, 2026-10-27), so the lock, the marker and Take Over (§3.1) cover it like any view. Today it is read-only plus capture (`docs/ui/phone.md`); the design that makes it edit is `docs/ready-to-build/phone-same-app.md`, built with or after this note. Edits from the phone are refused only for a root another view has locked; the server refuses phone clients only the routes that note trims (the ontology editor, rules, vaults, reminders, AI settings).
- As the note asks: propose a build order before starting.
