# Clicking a folder opens the folder context

**Status:** Agreed with the maintainer 2026-11-07. Ready to build. **Replaces `docs/ready-to-build/folder-tab-switch.md`** (same day, not built) and changes the folder tree's click rule in `docs/ready-to-build/virtual-folders.md` ("clicking a folder never changes the search context").

Written from a read-only look at the repo. Check the code references before relying on them.

---

## 0. Today (from the code)

- Clicking a folder narrows the current search context to the folder and the folders below it (`command-palette-controller.js`, `setVirtualFolder`). The typed search stays, so a folder often shows nothing.
- Each search context's folder is kept with the search contexts and survives a server restart (`app/services/tab_state.py`, `c07a50a5`).
- A reference view keeps the context it was opened from on the server (`referenceViews`, `originScope`); its × goes back there, or to the context before it if that one was closed.

## 1. The problem

With tags or text in the search, clicking a folder very often shows zero notes. To someone new that reads as an empty folder. The maintainer: clicking a folder should go to the folder, blank, and leave the search they were in one click away.

## 2. One folder context

- **Clicking a folder opens the folder context:** a search context with an empty search and that folder chosen. The context you were in stays in the list, untouched.
- **At most one.** The first folder click makes it; later clicks reuse it and switch its folder.
- **Named after its folder** (`Projects/Client-A/`); the name follows the folder.
- **It remembers where you came from:** the context the folder was clicked from, updated each time a folder is clicked from another context. Keep it on the server with the search contexts, as `referenceViews` keeps a reference view's origin.
- **Clicking a folder always starts from an empty search,** in the folder context too.
- **Typing still narrows the folder:** `@todo` in the folder context shows the to-dos in that folder.
- **The top, `/`,** opens the folder context with no folder: every note.
- **The chip's `×`** clears the folder; the folder context then shows every note.

## 3. Closing and reopening the folder tab

- **Closing the folder tab closes the folder context** and goes back to the context it came from, its search as left; if that was closed, to the one before it, as a reference view does.
- **If another context is showing when the tab closes,** the folder context still closes and the view stays where it is.
- **Reopening the tab goes back into the last folder** in a new folder context, its origin the context showing then. If that folder is gone, or none was chosen, the tree opens and the view stays where it is. Remember the last folder where the tree's shown state is kept.
- **Closing the folder context from the context list** goes back to its origin; the tree stays open, nothing chosen.

## 4. What stays as it is

- **Other search contexts never have a folder.** Their folder counts under a narrowing search, `(0/17)`, stay as information.
- Notes opened from the tree, drag and drop, renaming and New Folder are unchanged.
- The per-context folder kept today is only needed for the folder context; existing contexts with a folder can drop it (no outside users yet, so no migration).

## 5. Invariants

1. Clicking a folder never shows it narrowed by a search typed elsewhere.
2. There is at most one folder context.
3. Closing the folder tab never leaves a folder choice behind, and returns you where you were.
4. Folders never change tags or another context's search.

## 6. Done when

1. A folder click from any context opens or reuses the one folder context, search empty, that folder chosen; the clicked-from context is unchanged.
2. Closing the folder tab returns to the origin (or the context before it) and removes the folder context; reopening restores the last folder.
3. `folder-tab-switch.md` is removed from `docs/ready-to-build/` as replaced; `virtual-folders.md` describes the folder context.
4. Tests cover: a folder click with a search typed, a second folder click (reused), typing in the folder context, closing and reopening the tab, a closed origin, closing the folder context from the list.

## 7. Checked 2026-11-07 (filed from the inbox)

- Filed as ready to build, as its status asks. Nothing of it built.
- **Conflicts with what was just built.** `folder-tab-switch.md` was built the same day, after this note was written, and the maintainer tried it and approved it: closing the tree turns every search context's folder off, opening it turns each back on, each context keeping its own folder (`docs/ready-to-build/virtual-folders.md`; `app/api/folder_tree_switch.py`, `X-Metalist-Folders-Shown`). That note is removed as built, not as replaced. Building this note replaces that behavior: §3's closing and reopening, and §4's "other search contexts never have a folder".
- Confirmed: a folder click narrows the current context (`command-palette-controller.js`, `setVirtualFolder`); each context's folder saved in tab state (`app/services/tab_state.py`, `folderFilters`, `c07a50a5`); a reference view's origin kept on the server (`tab_state.py`, `referenceViews`, `originScope`).
- §4's "existing contexts with a folder can drop it": the folders are in tab state's encrypted blob, not a table, so dropping them is no schema change and needs no version bump.
- **Open, for the maintainer:**
  1. Build this, replacing the folder tab switch you approved today (closing the tab then closes the one folder context instead of pausing every context's folder), or keep the switch?
