# Renaming files

**Status:** Agreed with the maintainer 2026-10-28. Ready to build. Small. Filed here from `docs/inbox/` on 2026-10-28 (see "Found when filed").

Written from a read-only look at the repo. Check the code references before relying on them.

---

## 1. Today

- An attached file can't be renamed; it keeps the name it had when it was added.
- The name is stored twice, set equal at upload (`create_file` in `app/services/file_storage.py`): the encrypted **title** column, which the file card shows and search finds (`file_registry.title_of`), and `original_filename` inside the encrypted metadata JSON, which the download's `Content-Disposition` uses (`app/api/routes/files.py`, `download_file_endpoint`; also `app/api/routes/notes.py`).
- `thumbnail_kind` is derived from the name at upload; text files' badges come from the extension (`docs/ui/references.md`, File targets).
- Pictures and diagrams (`![[UUID]]`) already have a right-click menu (`app/static/js/modules/context-menu/context-menu-registry.js`). File cards (`[[UUID]]`) show a badge and the name (`.note-file-reference-name`).

## 2. The rule

1. **Renaming changes both names**: what the card shows (and search finds) and what the file downloads or saves as. The name belongs to the file, so every note showing it shows the new name.
2. **Right-click → `Rename File…`** on a file card, and on pictures and diagrams beside their existing items. Every kind of file can be renamed.
3. **The extension can't be changed.** The dialog shows the name without its extension in an editable field, the extension fixed beside it (`Q3 report` `.pdf`), the name selected so typing replaces it. Enter renames; Escape or `Cancel` does nothing. A name with no extension is edited whole.
4. **A blank name is refused** (the Rename button is dimmed). **Characters a file name can't hold** (`/`, `\`, `:` and the like) become `-`, as export file names already do.
5. **Nothing else changes:** not the extension, the kind (`thumbnail_kind`), the content, its revision or its previews.

## 3. Implementation notes (your call)

- A server endpoint (for example `PUT /files/{file_id}/name`) that re-encrypts the title and the metadata's `original_filename` together, refuses a changed extension, and updates `file_registry`'s cached title.
- Refresh the views showing the file, as other file changes do.
- Check the other readers of the name: search's file names, HTML export, file text previews (`create_file_preview_child`), AI context.
- Backups and vault password changes carry the new name like any other field (verify).

## 4. Done when

1. Renaming a PDF card from `scan_0042.pdf` to `Lease 2026` shows `Lease 2026` on every card showing that file, search finds it as `Lease 2026`, and downloading saves `Lease 2026.pdf`.
2. A picture renamed through its right-click menu saves under the new name with its original extension; the same for a diagram's `Save Diagram File`.
3. The extension can't be edited, and a request that changes it is refused by the server.
4. A blank name can't be submitted; `a/b:c` becomes `a-b-c`.
5. After locking and unlocking the vault, and after a backup and restore, the new name is still there.
6. Tests cover 1–5; `docs/ui/references.md` describes `Rename File…`.

## Found when filed (2026-10-28)

- The code references hold: `create_file` in `app/services/file_storage.py` sets the title and the metadata's `original_filename` from the same basename; `file_registry.title_of`; both `Content-Disposition` headers (`files.py` `download_file_endpoint`, `notes.py`); `.note-file-reference-name` (rendered in `app/services/embedded_references.py`); `create_file_preview_child` (`notes.py`); `Save Image` and `Save Diagram File` in `context-menu-registry.js`. Not built: `files.py` has no name endpoint (`/upload`, `/{file_id}/content`, `/{file_id}/previews`, edit sessions, `trim-unused`).
- No schema change: both names are existing fields (the title column, the metadata JSON), so no database version bump.
- `docs/ui/references.md` says "Attachments are immutable except Excalidraw diagrams"; once built, the name is changeable too. Update that line.
