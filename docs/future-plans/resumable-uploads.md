# Resumable uploads

**Status:** Direction agreed with the maintainer 2026-11-03. **Build after the streaming and no-cap note** (`streaming-no-file-cap`, handed off the same day); file this as a future plan until that is built. It answers that note's open question about large uploads on slow connections. Details marked *proposed* are suggestions.

Written from a read-only look at the repo. Check the code references before relying on them.

---

## 0. Today (from the code)

- An upload is one request: the whole file in one `FormData` `fetch` (`app/static/js/modules/api-client.js`, e.g. `uploadImportFile`; `app/api/routes/files.py`, `POST /upload`). A dropped connection loses it; `fetch` gives no upload progress.
- Requests must finish within 30 minutes (`docs/security/README.md`): about 2 GB at 10 Mbit/s up.
- A dropped folder's ticked files go to a holding folder (`uploadId`), one request per file.
- A folder import through the native folder dialog reads the disk directly (`app/api/routes/imports.py`, `pick_folder`), no upload.

## 1. Why

With no per-file cap, multi-gigabyte files will come over home connections, sleeping laptops and phones changing networks. MetaList has no outside users yet, but expects many; one request per file fails exactly on the files that matter most.

## 2. Who

Hosted, and self-hosted over the internet. A personal install on the same computer rarely needs it, but uses the same path, so there is one way to upload.

## 3. How

- A file goes up in pieces (8 MiB, a whole number of encryption segments; *proposed*), each its own short request. The 30-minute deadline stops limiting file size.
- The server encrypts each piece as it arrives into the blob's ciphertext `.tmp` (per-file storage, §5 there). No plaintext on disk, nothing held in memory.
- A dropped connection resumes automatically from the last confirmed piece.
- The file becomes visible only when complete (rename `.tmp` → `.mlb`, then the catalog row, as per-file storage requires).
- *Proposed:* an open protocol such as tus, or a simple equivalent; your choice.

## 4. What the user sees

- A progress bar on the file's card while it uploads.
- Connection lost: "Paused, will resume", then it continues.
- After a reload or closed tab: the browser can't reopen a picked file, so the card says **Pick the file again to finish** and resumes once the same file is picked. Native apps resume by themselves.
- **Cancel** on the card deletes what was uploaded.

## 5. Leftovers

- An unfinished upload expires (7 days, *proposed*) and its ciphertext is deleted, by the same sweep as per-file storage's crash leftovers.
- Hosted: unfinished uploads don't count toward the plan's storage; the expiry bounds them.

## 6. Privacy

- What the browser keeps to recognise the file holds no plaintext file name (an upload ID plus a fingerprint of size and modification time; *proposed*).
- An unfinished upload can be resumed only by the same vault, while unlocked.

## 7. Invariants

1. A dropped connection loses at most the piece in flight.
2. A file is in the vault only when complete.
3. Unfinished uploads are ciphertext only, deleted on expiry or cancel.

## 8. Open

- Piece size and expiry; tune them.
- Whether downloads resume too (range requests make it nearly free).

## 9. Done when

1. A file of several GB uploads over a connection cut mid-way, resuming without starting over; a reload resumes after the file is picked again.
2. The card shows progress, the pause and Cancel.
3. Unfinished uploads expire and are swept; none is ever plaintext on disk.
4. `docs/security/README.md` (upload limits and deadline) and the help describe it.

## 10. Checked 2026-11-06 (filed from the inbox)

- Filed as a future plan, as its status asks: build after `docs/design/file-storage.md`. Nothing built.
- Confirmed: single-request uploads (`uploadImportFile` in `api-client.js`; `POST /files/upload` in `app/api/routes/files.py`); the dropped folder's holding folder (`uploadId`; `/import/uploads/{id}/file` in `app/api/routes/imports.py`, `app/services/import_uploads.py`); the native folder dialog (`pick_folder`, `POST /import/pick-folder`).
- **Correction:** the 30-minute deadline is the HTTPS proxy's only (`app/https_proxy.py`); plain HTTP has none.
- **Overlaps with two ready-to-build notes:** `folder-import-and-file-previews.md` already has a file-level resume rule for imports (pick the same folder again; files already in are skipped), and `desktop-drops-into-folders.md` (point C) leaves interrupted dropped-folder uploads starting over until that rule is built. This note adds resuming inside one file. Both now point here.
- **Decided with the maintainer 2026-11-06 (the conflict with the holding folder):** a dropped folder's files are unfinished uploads like any other: encrypted pieces in this note's store, held apart from the vault until Import, the Summary reading them by decrypting as it streams. One upload path; invariant 3 holds for imports too. The browser queues a folder's files a few at a time (the server's four-transfer limit goes, `docs/design/file-storage.md` §8). Combined with `folder-import-and-file-previews.md`'s file-level rule, an interrupted folder resumes at the file and the piece it stopped at.
