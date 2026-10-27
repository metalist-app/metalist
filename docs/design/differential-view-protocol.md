# Differential View Protocol

Agreed, not built (2026-10-26): several views on one vault at once, each signed in, with editing locked per root note (`docs/ready-to-build/multi-view-editing.md`). Moves and saves from other views reach a view live, and the edited root keeps its place on its editor's screen, as `keep_edited_root_in_place` does for sorted tabs.

## Overview
- `POST /api2/notes/view` now serves two flows:
  - **Bootstrap**: the server returns a compact `structure` chunk for initial load.
  - **Incremental**: after bootstrap, the server diffs against the tab’s warm view and returns `diffOps` (insert/move/remove instructions) plus sparse payloads.
- The server keeps a **warm view** per `(clientId, tabId)`: the last view it sent that tab (hierarchy, per-note hashes, locks). The browser therefore sends no hashes or structure, only which roots it can currently see.
- The loaded roots form a **band** around the visible roots, so the DOM, the warm view, and per-request render work stay bounded however far the user scrolls.
- Legacy `/api/*` routes remain blocked.

## Request Shape
```json
{
  "clientId": "client-uuid",
  "editingNoteId": null,
  "undoContext": "tab:tab-uuid|search:optional query",
  "search": "optional query",
  "tabId": "tab-uuid",
  "tabViewEmpty": false,
  "visibleTopRootId": "root-uuid-13",
  "visibleBottomRootId": "root-uuid-15",
  "isUntaggedView": false
}
```

### Notes
- Keys above are required.
- `visibleTopRootId` / `visibleBottomRootId`: the first and last root notes the browser can see (`null` when unknown, e.g. on first load). The server builds the band from them:
  - The band spans `ROOT_BAND_MARGIN` (75, `app/services/snapshot.py`) roots beyond each visible root.
  - An existing band edge stays put while it lies between half and twice the margin from the visible roots, so ordinary scrolling changes nothing and roots load or unload far from the viewport.
  - With no viewport report (a refresh after an action) the band is kept; a note being edited always lies inside it (if it is outside, the band is re-centred on it).
  - **Sorted tabs freeze the edited root.** While a note is edited in a non-normal sort, `keep_edited_root_in_place` puts its root right after the nearest earlier root of the tab's previous view (the warm view's root order), or right before the nearest later one, instead of its new sorted place; in date-bucketed sorts it takes that neighbour's timestamp for `rootSortBuckets`. A root the tab never showed keeps its sorted place. So saving never moves the edited note far away and never re-centres the band away from the screen. This, and the client's limits on new root notes in sorted tabs (`rootNoteCreationBlockMessage`), prevent the band being re-centred on a far-away note: that left the viewport at a band edge whose band-move requests the server kept re-centring, failing `Infinite scroll blocked`.
  - Leaving edit mode in a sorted tab holds a `sorted` viewport reference (`captureSortedExitAnchor`): the caret/reading-line anchor while the edited root keeps its neighbours, otherwise the root that was below it (or above it, at the end), so the surrounding notes stay on screen while the note moves to its sorted place.
  - The response's `rootWindowStart` and `rootBandMargin` tell the client where the band starts, for scroll metrics.
- `tabViewEmpty`: `true` when the browser holds nothing for this tab (a fresh tab, or one reset locally). The server then ignores its warm view and bootstraps.
- `isUntaggedView`: restricts the view to notes without tags.
- The warm view is kept for the tab's lifetime. It is dropped only when the tab is deleted or the session ends (login, passwordless claim, logout, lock, restore); a duplicated tab starts from a copy of its source's warm view.
- `search` and `editingNoteId` are passed through for server-side rendering/flagging.
- `undoContext`: a client-computed context boundary (currently tab+search). When this changes, the server clears the undo/redo stack for that client so `Cmd+Z` never crosses tab/search contexts.
- `tabId`: client-maintained active tab UUID; the server keeps one warm view per `(clientId, tabId)`. Search, sort, and untagged changes simply diff against it.
- A companion `/api2/notes/tab-state` + tab create/delete endpoints keep each tab's search + scroll metadata in the namespace SQLite DB so reconnects and server restarts can hydrate the same contexts before the next `/notes/view` call.
- When the namespace is password-protected, the persisted tab-state payload is encrypted at rest with the active DEK; passwordless namespaces keep the same row in plaintext.

## Response Shape (Bootstrap)
```json
{
  "snapshot": {
    "structure": [
      {
        "id": "note-uuid-1",
        "parentId": null,
        "prevId": null,
        "nextId": "note-uuid-2",
        "hash": "expandedHashWithFlags"
      }
    ],
    "notes": {
      "note-uuid-2": {
        "content": "<div>rendered html</div>",
        "tags": "tag1 tag2",
        "proposedTags": "suggested-tag",
        "flags": {
          "isEditing": false,
          "isCollapsed": false,
          "proposalCount": 1
        },
        "hash": "expandedHashWithFlags"
      }
    },
    "locks": {
      "note-uuid-1": "client-uuid"
    },
    "rootIds": ["root-uuid-1", "root-uuid-2"],
    "updateUUID": "sync-token",
    "version": "app-version",
    "currentClientId": "client-uuid",
    "searchQuery": "optional query",
    "editingNoteId": null
  },
  "updateUUID": "sync-token"
}
```

### Notes
- `snapshot.structure` includes every visible node in the current band. This path is only used when the server has no warm view for `(clientId, tabId)` or the request sets `tabViewEmpty`.
- `snapshot.notes` holds every note in the band on bootstrap; incremental responses are sparse (see below).
- Each note payload includes:
  - `content`: HTML that is **rendered for view mode** unless the note is actively being edited by the current client.
    - When `flags.isEditing` is true (and the lock owner is the current client), the server sends **raw editable HTML** so wrapper delimiters like `{{...}}` remain visible.
    - Otherwise the server may apply view-only transforms (e.g. meta-tag formatting that consumes matching wrapper delimiters).
    - Embedded references (`![[UUID]]`) are resolved in this view-only content rendering path; hashes include the rendered embed output so host notes can update when embedded targets change.
  - `tags`: tag-bar string: whitespace-separated tokens outside `/* ... */` comments.
  - `proposedTags`: the note's direct unresolved proposal tokens; inherited and ontology-derived terms are not duplicated here.
  - `flags.proposalCount`: direct proposal count for an expanded note, or the current visible branch's rolled-up count for a collapsed note.
  - `hash`: covers `content` + `tags` + `proposedTags` + flags + structural pointers.
- The client sanitizes invalid/incomplete tokens (e.g. unclosed wrappers/comments) before saving.
- `rootIds` lists the visible root ordering so the client can refresh infinite-scroll metrics without the full structure.
- `updateUUID` mirrors `snapshot.updateUUID` for convenience.

## Response Shape (Incremental)
```json
{
  "snapshot": {
    "diffOps": [
      {"type": "remove", "noteId": "a", "parentId": null, "fromIndex": 0},
      {"type": "insert", "noteId": "b", "parentId": null, "toIndex": 0},
      {"type": "move", "noteId": "c", "parentId": "a", "fromIndex": 2, "toIndex": 0}
    ],
    "notes": {
      "b": {"content": "<div>rendered html</div>", "tags": "tag1 tag2", "proposedTags": "", "flags": {"isCollapsed": false, "proposalCount": 0}, "hash": "..."}
    },
    "locks": {"c": "client-uuid"},
    "lockDiffs": {"c": "client-uuid", "d": ""},
    "rootIds": ["root-uuid-1", "root-uuid-2"],
    "updateUUID": "sync-token",
    "currentClientId": "client-uuid",
    "editingNoteId": null,
    "version": "app-version"
  },
  "updateUUID": "sync-token"
}
```

### Notes
- `diffOps` is an ordered list of DOM operations generated by diffing the warm view with the latest store state:
  - `remove`: delete the note (and its subtree) at `fromIndex` under `parentId`.
  - `insert`: create a new note at `toIndex` under `parentId` (payload supplied via `snapshot.notes`).
  - `move`: reparent/reorder an existing note under `parentId`.
- `notes` remains sparse: only notes whose hash differs from the warm view, plus newly inserted notes.
- Roots leaving the band arrive as ordinary `remove` ops and roots entering it as `insert` ops.
- `lockDiffs` only lists locks that changed since the warm view. `locks` still contains the full visible lock map for reference.
- `rootIds` keeps infinite-scroll metrics in sync without re-sending the full structure array.
- Every response becomes the tab's new warm view, so it must be applied: the client never discards a view response, and tab switches wait for an in-flight view request.

## Reconciliation Efficiency
- Snapshot construction uses a request-local traversal cache for note records, ordered child lists, ancestor paths, and descendant counts. A hierarchy branch is read once even though rendering and per-note metadata both need it.
- Rendered view HTML is cached per note for notes without references, and for link/reference notes keyed on what they reference, so an unchanged band re-renders almost nothing. Notes with remote images are never cached because their proxy tokens are random and expire.
- If the cached and current `children_by_parent` maps are identical, the server skips branch-by-branch structural diffing and only computes sparse note/lock updates.
- An incremental response with no structural, note, or lock changes returns from client reconciliation immediately. Lock-only and structure-only responses also skip media hydration unless note content was actually replaced.

## Client Reconciliation
- Tab switch optimization: clients may detach/cache the `#notes-container` subtree per tab and restore it instantly on return, then call `/notes/view` to reconcile diffs.
- If a persisted tab is restored after a server restart but its detached DOM cache is gone, the tab reports `tabViewEmpty` and the next `/notes/view` round-trip bootstraps it from server state.
- Bootstrap path: diff against `snapshot.structure`, update the DOM and the tab's note-id tracking, reset root tracking.
- Incremental path:
  - Apply `diffOps` in order (remove/move/insert) directly to the DOM.
  - Removed notes animate through an identity-free placeholder clone: the live note node is removed from `[data-note-id]` lookup and the tab's note tracking immediately, while the clone collapses out of the layout before being discarded.
  - For each affected note id present in `snapshot.notes`, refresh the DOM content and flags.
  - When roots enter or leave the band above the viewport, the client keeps the top visible root at the same screen position (`viewport-hold-service.js`), re-checking briefly while images and diagrams settle, and stops as soon as the user scrolls.
  - **Principle:** whatever the user is interacting with stays where it is on screen when a note changes mode; a fallback never moves the view.
  - A hold ends on user input, on a user scroll, and when the app scrolls on purpose: `scrollWindowToYFastAnimated` announces `DELIBERATE_SCROLL_EVENT` first (e.g. scrolling up to a new top note), so a hold never scrolls back against it.
  - Entering edit mode by clicking holds a click anchor (`captureClickAnchor`, taken at the click before anything changes): the clicked text, re-found by exact surrounding-text match in the editable source, stays under the pointer and the caret is placed there (`placeCaretAtClickAnchor`, no scrolling); text matching falls back to the longest run of text right after, then right before, the click when the source adds markup (list markers, heading marks). Mermaid diagrams use their structure instead of text hit-testing (unreliable inside SVG): a click on a box is a `source` anchor for its label in the source (`[label]`, `{label}`, …), whose line goes under the pointer; elsewhere in a diagram it is the diagram's ```` ```mermaid ```` line, held at the diagram's top. Text positions carry an affinity, because line breaks add no text and the end of one line equals the start of the next: a click at a line's start keeps that line, a caret left at a line's end keeps that end. Rendered formulas carry their TeX source as `data-latex-source` (exactly as written: the inner source of `$$…$$`, or the whole scoped region); a click on one is a `source` anchor for that text (counting repeats of the same source), and an exit anchor whose caret lies inside a formula's source (found in `editText`, the text as edited) holds that formula where the source line was. The attribute exists only in the live view: clipboard and HTML export remove it (`strip_latex_source_attributes`), and saving drops it as an unknown attribute. Any other click not on text holds the note's top and puts the caret under the pointer.
  - Leaving edit mode holds the user's place instead (`captureNoteAnchor` → `viewportHold` on the refresh): a text anchor at the caret when it is on screen, otherwise at the reading line (a third down the usable viewport), otherwise the note's top. After re-rendering, the anchored text is found again by its surrounding text (falling back to the same proportion of the note's text) and kept at the same screen height. A collapsed note that was edited is saved expanded when edit mode ends (`persistExpandedEditSessionIfNeeded`, called only on exit, never by saves, so it does not unfold mid-edit) and is held like any expanded note; one left unchanged shows collapsed again and keeps its first line of text where its first line was while editing (exit anchors record `contentTop`; the collapsed row is a server preview, so its text is not matched), just below the sticky search controls if that line had scrolled above them. Switching to another note holds the clicked note's top instead. Only an exact surrounding-text match places a text anchor; when the text did not survive rendering (Markdown syntax, Mermaid source) the proportional guess is not used and the note's top is held (Phase 3's source mapping will place these exactly). Nothing is highlighted on leaving edit mode (the former position cue was removed: the user knows where they are). Late content keeps its space so corrections are rare: the server stamps `width`/`height` on inline data-URI images (`inline_image_dimensions.py`, applied in `_render_note_view_html`), and the browser reuses per-session sizes for Mermaid diagrams (by source hash and width), image attachments (aspect ratio by file id) and Excalidraw previews.
  - Holds run as a session: corrections happen in a `ResizeObserver` callback (after layout, before paint, so no visible jump), the browser's own scroll anchoring is disabled while a hold is active, and the hold ends on any user input or scroll, after the layout has been still for 700 ms, or after 4 s.
  - Apply `lockDiffs` by toggling lock styling/editability without re-rendering content.
  - Update `ModeContext`’s root tracking via the provided `rootIds` array.
- Active editor preservation: when a note is being edited by the current client and the edit session has user edits, `/notes/view` refreshes may update flags, locks, collapse state, and the snapshot hash, but must not replace the note content DOM. The DOM content hash remains tied to the actual rendered editor content until the client intentionally saves or exits editing.
- The server's warm view, not the browser, is the diff baseline. Because it is tab-scoped, a tab switch needs no invalidation.

### Scroll State Note
- When caching/restoring the notes DOM during a tab switch, the browser can temporarily clamp `window.scrollY` if the page height changes. Scroll persistence should be suppressed during the switch so per-tab `scrollY` snapshots are not overwritten.
- Prefer storing a content-based `scrollAnchor` (anchor note + neighbor belt + intra-note offset) via `/api2/notes/tab-state` so restoration survives insertions/deletions/reorders across overlapping tab result sets.
- Undo/redo responses additionally return a `scrollRestore.focusNoteId` so the client can scroll the affected note into view (below the sticky search controls) even when the viewport anchor is root-based.
- Undo/redo scroll restoration identifies the affected saved mutation through `opType`, `focusNoteId`, and `viewAnchorRootId`; selection-only edit-mode transitions are not part of application history.

## Manual Verification Checklist
- CRUD sequences: create, edit, delete and confirm only changed nodes rerender.
- Structural mutations: move across parents/siblings and verify order updates without full redraw.
- Collapse/expand toggles: child containers + flags stay accurate.
- Undo/redo flows: structure diff realigns with no stale nodes.
- Search: query round-trips per tab and updates `undoContext` boundaries.
- Search filtering: server-side and banded by root notes (scrolling moves the band of matching roots).
- Lock acquisition/release: lock icons/styling update without full refresh.
