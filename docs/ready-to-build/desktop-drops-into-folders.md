# Dropping files and folders from the desktop

**Status:** Agreed with the maintainer 2026-11-02. Ready to build. Builds on the folder tree (`docs/ready-to-build/virtual-folders.md`), the folder-of-files import (`docs/ready-to-build/folder-import-and-file-previews.md`), the import prefix folder, and dragging a note into a folder (`drag-note-into-folder`, handed over the same day).

Written from a read-only look at the repo. Check the code references before relying on them.

---

## 0. Today (from the code)

- Dropping files on the notes column makes a root note per file holding it, with a preview where its type has one (`keyboard-events.js`, `handleDropEvent`).
- Nothing reads a dropped folder: no `webkitGetAsEntry`, `getAsFileSystemHandle` or `webkitdirectory` in the front end.
- The tree takes drops only of its own folders (`virtual-folders-service.js`, `DRAG_TYPE`).
- The folder-of-files import picks its folder with a dialog on the server's machine, so hosted and self-hosted have no way to choose a folder yet (`folder-import-and-file-previews.md` §4 and its open point on uploading from the browser).

## 1. Files dropped on a folder in the tree

- **The same as a drop on the notes column:** one root note per file, with its preview. **Each new note also gets that folder's tag.**
- **No walkthrough:** a file drop is deliberate and small, as already decided for drops.
- The folder's count updates at once, as for a note dragged into it.
- The per-file size limit applies as for any drop.

## 2. A folder dropped on a folder in the tree

- **It's an import: it opens the import walkthrough on Any folder, already filled in,** as a dropped bookmarks file opens it on Browser bookmarks.
- **The prefix defaults to the target plus the dropped folder's name:** `Photos` dropped on `Projects/` gives `Projects/Photos/`. Editable as always.
- **The file-type checklist and size check come first:** a desktop folder can hold gigabytes, or a `node_modules`.
- Importing the same folder again follows `importing-again`.

## 3. A folder dropped on the notes column

- The same walkthrough, the prefix set to the folder's name alone (`Photos/`).
- Files dropped on the column are unchanged.

## 4. Hosted gets folder import

- A dropped folder is the browser handing the folder over. The browser lists its files, names and sizes before uploading anything (`DataTransferItem.webkitGetAsEntry`, or `getAsFileSystemHandle` where available), so the checklist and Summary work before anything is sent; then the ticked files upload one by one.
- The same reading can serve a "Choose Folder…" button on hosted (`<input type="file" webkitdirectory>`), so the walkthrough's Folder step works there without a drop.
- *Check* folder drops in Chrome, Safari and Firefox, and how each copes with a very large folder (directory readers return entries in batches).

## 5. Invariants

1. A dropped file never needs the walkthrough, except a browser's bookmarks export, which asks Import Bookmarks or Keep as File first (§8); a dropped folder always goes through it.
2. Nothing from a dropped folder is uploaded before the user has seen the checklist and the Summary.
3. Files dropped on a folder end up in exactly that folder.
4. A drop holding a folder and anything else brings nothing in; a floating message says to drop the folder on its own.

## 6. Done when

1. Files dropped on a tree folder come in as a column drop does, tagged with that folder.
2. A folder dropped on a tree folder or the column opens the walkthrough on Any folder with the right prefix, and imports through it.
3. On hosted, the walkthrough can take its folder from a drop or a browser folder picker.
4. `docs/ready-to-build/virtual-folders.md` and `folder-import-and-file-previews.md` describe it; tests cover files on a folder, a folder on a folder, a folder on the column, and an empty folder.

## 7. Still open

- ~~Several files and a folder dropped together.~~ Decided: refused (§8).

## 8. Checked against the code (2026-11-02, when filed)

- **§0 holds.** `handleDropEvent` (`keyboard-events.js`) makes the per-file notes; nothing in the front end reads a dropped folder (no `webkitGetAsEntry`, `getAsFileSystemHandle` or `webkitdirectory`); the tree takes only its own folders (`DRAG_TYPE`). The file limit is 100 MiB (`MAX_ATTACHMENT_BYTES`).
- **A dropped folder can't reach today's import on any deployment, the personal one included.** The import reads a folder by its path on the server's machine (`imports.py`, `folderPath`, from `pick_folder`). A browser never gives a page a dropped folder's path, only its files. So §2 and §3 need §4's browser upload (listing, checklist, then the ticked files sent one by one) everywhere, not only on hosted. That is the larger part of this work, and §4 of `folder-import-and-file-previews.md` (with its resume rule) is the same piece.
- **`importing-again` was dropped** the same day: an import only adds (`import-export-launch.md` §5). Importing a dropped folder again brings all of it in again beside the earlier import.
- **Invariant 1 meets the bookmarks rule.** A browser's bookmarks export dropped alone asks Import Bookmarks or Keep as File wherever it is dropped (`docs/ui/references.md`). Dropped on a tree folder, which folder would its import go under?

### Open (ask the maintainer)

- ~~A bookmarks export dropped on a tree folder.~~ **Decided 2026-11-02 (the maintainer): it follows the target both ways.** Import Bookmarks opens the walkthrough with the folder field at the target plus `Bookmarks` (`Projects/Bookmarks`), editable; Keep as File files it in the target folder like any file dropped there. Dropping on a folder always means "put it here".
- ~~§7: several files and a folder dropped together.~~ **Decided 2026-11-02 (the maintainer): any mix is refused.** A drop holding a folder and anything else (files, or another folder) brings nothing in, and a floating message says to drop the folder on its own. One rule, no exceptions. Several files with no folder among them are no mix: they come in as §1 says, one note each, in the folder they were dropped on.

