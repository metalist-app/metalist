# Stream files, then no 100 MB cap

**Status:** Agreed with the maintainer 2026-11-03. Ready to build. **Moves `docs/design/file-storage.md` to ready to build,** for its streaming encryption, then removes the per-file size limit.

Written from a read-only look at the repo. Check the code references before relying on them.

---

## 0. Today (from the code)

- Each file may be up to 100 MiB (`app/upload_limits.py`, `MAX_ATTACHMENT_BYTES`, set 2026-09-12 in `97c06464`), changeable only by `METALIST_MAX_ATTACHMENT_BYTES` at start.
- Reason (`docs/security/README.md`): encryption and decryption require complete per-file buffers, with four transfers admitted at once.
- Folder and Obsidian imports skip larger files with no way to include them (`app/usecases/import_obsidian_vault.py`, `app/services/obsidian_import/file_groups.py`). The maintainer hit this importing a folder: two files over 100 MB left out.
- Files are blobs in one SQLite files database. `docs/design/file-storage.md` (one encrypted file per item, streaming segments) is a future plan; its open points (§10) are tunables.
- Requests have a 30-minute total deadline.

## 1. Why

Streaming encrypts and decrypts a segment at a time, so memory stays small whatever the file's size, on a laptop or a shared server. That removes the cap's reason in every deployment.

## 2. Build per-file storage now

- Per-file storage is built (`docs/design/file-storage.md`); §9 says what of this note is left. Streaming comes with it; adding streaming to the single files database first would be built twice. No outside users yet, so the migration is cheapest now.
- Its §10 tunables are yours to choose, starting from its proposals (64 KiB segments).
- Everything that touches file contents streams: upload, download, backups, export, restore, password changes.
- Downloads and in-note audio/video playback read only the segments they need (HTTP range requests) (decided 2026-11-08).

## 3. Then remove the per-file limit

- No per-file size limit in any deployment (personal, self-hosted, hosted). Hosted is bounded by the plan's total storage, not by file size.
- Imports and drops no longer skip files for size.
- Text extraction for search may keep its own size limit: a file too large to read for text is still stored, opened, downloaded and found by name.
- Remove `METALIST_MAX_ATTACHMENT_BYTES` and the related 413 paths unless you find another reason to keep a limit; if you do, say why in `docs/security/README.md`.

## 4. Until §2 is built

The 100 MiB limit stays as it is. No interim override.

## 5. Not decided

- Multi-gigabyte uploads on slow connections can pass the 30-minute deadline. Resumable uploads or a longer upload deadline come later; until then such an upload fails with a plain message.

## 6. Invariants

1. No file is held wholly in memory to store, read, back up or restore.
2. No per-file size limit in any deployment.
3. A file too large for text extraction is still kept and found by name.

## 7. Done when

1. A file several times larger than 100 MiB imports, drops, downloads, plays (if audio or video), backs up and restores, with memory use that doesn't grow with its size.
2. A folder import with such files includes them.
3. `docs/security/README.md` (attachment limits, buffers), the per-file storage doc moved to its permanent place, the help and the help search skill reflect this.

## 8. Checked 2026-11-06 (filed from the inbox)

- Filed as ready to build, as its status asks; `docs/future-plans/file-storage-per-file.md` moved to `docs/design/file-storage.md` with it, and every link to it updated. Nothing built.
- Confirmed: `MAX_ATTACHMENT_BYTES` (100 MiB) and `METALIST_MAX_ATTACHMENT_BYTES` in `app/upload_limits.py`, set in `97c06464` (2026-09-12); the reason in `docs/security/README.md` (attachment paragraph: "Encryption/decryption still require complete per-file buffers"); the Obsidian/folder import skips in `app/usecases/import_obsidian_vault.py` and `file_groups.py` (`is_over_limit`: "listed, never brought in").
- **More places use the limit** than the note names: `app/main.py`, `app/api/upload_limits.py` (the multipart envelope, the limit plus 1 MiB as `MAX_UPLOAD_REQUEST_BYTES`), `app/api/routes/imports.py` (the dropped-folder uploads, `/import/uploads/{id}/file`) and `app/services/file_storage.py` (downloads' preflight that rejects oversized legacy files with 413). Tests: `tests/unit/test_phase_two_http.py`, `tests/unit/test_obsidian_import.py`. §3 removes all of them.
- **Correction:** the 30-minute deadline (§0, §5) is the HTTPS proxy's only (`app/https_proxy.py`, `MAX_REQUEST_SECONDS`); plain HTTP has no total request deadline. It bounds downloads over HTTPS as well as uploads.
- **Schema:** per-file storage changes the files database, so its §12 applies: a version bump and migration step, the encryption audit, `docs/security/README.md`, and the backup immutability rules.
- **Decided with the maintainer 2026-11-06:**
  1. **Free space bounds an upload, checked first.** Before storing, MetaList compares the file's size with the free disk space less a reserve (*proposed:* 1 GiB or 5% of the disk, whichever is smaller) and refuses a file that doesn't fit with a plain message saying how much space is missing. A disk that fills mid-write (something else wrote to it) deletes the partial `.mlb.tmp` and gives the same message. A full disk would stop notes saving and backups; refusing one upload is far better. Hosted checks the plan's remaining storage instead.
  2. **The four-transfer limit goes.** Its reason was memory; streaming holds one segment per transfer. A server-side 429 makes images and players fail at random, so the browser queues a folder's uploads a few at a time instead (steadier progress too). Hosted limits bandwidth per account at its edge.
  3. **The dropped-folder holding folder is encrypted, and becomes resumable uploads' store.** A dropped folder's files are unfinished uploads like any other (`docs/future-plans/resumable-uploads.md`): encrypted pieces, held apart from the vault until Import; the Summary reads them by decrypting as it streams. One upload path, and per-file storage's rule that plaintext never touches disk holds. A vault without a password stores files unencrypted anyway, so nothing changes there. Until resumable uploads are built, the holding folder stream-encrypts whole files.

## 9. Found while building (2026-11-08)

- **Built:** per-file storage, and `GET /files/{id}/download` streams and answers `Range`, tested over real HTTP. Still to build from §2 and §3: streaming uploads, then removing the limit.
- **Open, needs the maintainer:** in-note playback cannot use `Range` yet. `media-player-service.js` fetches the whole file into a blob because a request needs the tab's header, and a browser's own player cannot send one. The options are a short-lived playback link for one file, valid only while the vault is unlocked, or feeding the player through Media Source Extensions, which only some formats support. A link is a new way to authorize a request, so it needs its own decision and security review.

## 10. Built (2026-11-08)

- **Uploads stream into their blob** as they arrive (`app/api/streaming_upload.py`, `FileUpload` in `file_storage.py`): a parsed form would hold them in a plaintext temporary file. The body is read in a context of its own: reading can resume the connection's reader, the event loop keeps the context it was resumed in for that connection, and the open transaction then broke the next request.
- **No per-file limit,** in the HTTP limits, the HTTPS proxy, imports and the checklist. `METALIST_MAX_ATTACHMENT_BYTES` and the four-transfer limit are gone; the browser still sends a few at a time (`file-transfer-slots.js`).
- **One limit stays, and why (§3 asks):** 100 MiB, `MAX_IN_MEMORY_FILE_BYTES`, for what must hold a whole file in memory: an edited diagram, an email, the viewer's previews, a file's text for search, an image inlined in an export or compressed on import. Over it the file is stored, downloaded and found by name; a text file that size imports as a file.
- **Free space is checked first,** with the proposed reserve, and a disk filling mid-write gives the same kind of message (`app/services/disk_space.py`).

**Not built:** the holding folder is still unencrypted (§8, decision 3), and §9's playback question is open, so audio and video load the whole file first.
