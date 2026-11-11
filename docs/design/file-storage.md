# File storage: one encrypted file per attachment, with a catalog

**Status:** Built 2026-11-08 and released in 0.27.0, as §13 records, including where the code differs from the sections below. Streaming uploads and no per-file limit came next (§14).

Written without looking at the code, apart from a few references noted below. Check every reference before relying on it.

---

## 1. Decision and why

**Each stored item becomes one encrypted file on disk, plus a small catalog database at the root of the files folder.** This replaces today's single `<vault>.metalist.files.db` (the `files` and `file_previews` tables in `app/db/file_schema.py`).

The maintainer's reasons:
- **Simplicity.** A folder of files is something anyone can reason about, inspect, back up and repair by hand.
- **Fewer moving parts.** Sealed shards, tombstones and compaction were considered and rejected: each is simple alone, but together they leave room for subtle bugs.
- **Migration is cheap now,** while vaults are few and small.

**Costs that were accepted:**
- Small-file overheads in object storage come to cents per heavy user per month.
- There are more objects to verify and replicate.
- The number of items is visible, but not their exact sizes (§4).

## 2. Layout

```
<vault>/
  <vault>.metalist.db                ← notes database (unchanged)
  files/
    catalog.db                       ← everything ABOUT each item
    blobs/
      3f/3fa2…c9.mlb                 ← one encrypted item per file, named by random ID
```

- **Everything is a blob:** originals, thumbnails, the light and dark previews, and extracted text. The catalog links them together.
- **Names are random 128-bit IDs, not content hashes,** so two vaults holding the same file can't be matched.
- **Two-character fan-out folders** keep each directory small. **`.mlb`** ("MetaList blob") makes stray files recognizable.

## 3. The catalog

One row per item.
- **Plaintext:** `item_id` (what notes reference; stable), `blob_id` (the current blob; changes on each revision), `kind` (`original`, `thumbnail`, `preview-light`, `preview-dark`, `text`), `parent_item_id`, `padded_size`, `content_revision`, `backed_up_at`.
- **Encrypted per field:** timestamps, title, original name, MIME type, real size, origin, metadata, `content_hash` (SHA-256 of the plaintext), and `file_key_wrapped`.
- **The plaintext columns are the minimum** that backup and crash-leftover cleanup need without the key.
- **Metadata only, about 1 KB per item.** Thumbnails, previews and text never go in the catalog. The search filters below are the one addition: about 5 to 8 KB per file that has text.
- **Search (decided 2026-11-08):** today's `file_texts` table splits. Each file's extracted text becomes a `text` blob, because it can reach 5 MiB per file and the catalog must not grow with what is inside files. A search already reads text one file at a time, only when the filter says the term may be there; benchmark that read when building. The bloom filters stay in the catalog, encrypted: login loads them all at once, and opening thousands of files for that would slow unlock.

## 4. Blob format, encryption and padding

- **Header:** magic `ML`, a suite byte (AES-256-GCM), a version and a 7-byte random nonce prefix, followed by segments. Built: §13.
- **A per-item file key:** a fresh random 256-bit key per item, stored wrapped by the vault key in the catalog. This keeps bulk file encryption off the vault key's nonce budget, and lets one item be re-encrypted alone.
- **Streaming segments in one file:** fixed plaintext segments (64 KiB proposed), each sealed with a counter-derived nonce, the last marked final. This is the standard streaming-AEAD construction, as used by `age` and libsodium's secretstream. Large files stream, never sit wholly in memory, and are never plaintext on disk. Truncation, reordering and segment swapping are detected.
- **Padding:** the plaintext is padded with Padmé (at most about 12% overhead), plus a random amount up to 1% of the file's size, so stored sizes don't identify known documents. The padding is removed on read using the real size from the catalog.
- **No plaintext ever touches disk** in a vault with a password. Temporary files hold ciphertext only.
- **A vault with no password (decided 2026-11-08)** uses the same folder and catalog, with its files unencrypted and unpadded: there is no password behind a key, so encrypting would only pretend to protect them. Setting or removing a password rewrites every file, as it does today, and must survive a crash partway through.

## 5. Writing and editing (crash-safe order)

1. Generate `item_id`, `blob_id` and the file key.
2. Stream-encrypt to `…/<blob_id>.mlb.tmp`, `fsync`, then rename to `.mlb`.
3. Commit the catalog row.
4. Commit the note's reference to `item_id`.
5. Queue the blob for backup (hosted).

- **A crash before step 3** leaves a blob with no catalog row; the sweep (§7) removes it.
- **A crash between steps 3 and 4** leaves a catalog row nothing references, which is harmless.
- **The catalog never points to a missing blob.**
- **Editing** (Excalidraw, regenerated previews) writes a **new blob**, repoints `blob_id` and increases `content_revision`. The old blob is deleted from the live folder after the commit. Nothing is ever rewritten in place.

## 6. Backups

- **Self-hosted and personal backups stay one whole archive** (`Back Up Now`): the notes database plus the `files/` folder as it is (catalog and blobs). Every backup is complete; nothing chooses which files go in. An export opens directly as a vault.
- **The rule behind it:** people must never have to get the choice of what to back up right. If MetaList later backs up to cloud storage itself (an integration with AWS, Azure or Google Drive, say), it may upload each file once there too, as hosted does, because MetaList does the choosing (`docs/future-plans/backups-s3.md`).
- **Hosted:** a keyless uploader sends each new blob to the backup store **once**, as one object, and sets `backed_up_at`. The catalog is snapshotted together with the notes database, as a pair with one snapshot ID, using `VACUUM INTO` after a WAL checkpoint, on the existing snapshot triggers. A restore always uses a matching pair. Here no person chooses anything, so uploading each file once is safe, and it's the only affordable way at hourly snapshots.
- **Hosted retention:** a backed-up blob stays as long as any retained catalog snapshot references it.

## 7. Cleanup

- **Crash leftovers, automatic and keyless:** blobs with no catalog row, older than a grace period (1 hour proposed), are deleted.
- **Files nothing references:** removed only by `Trim Unused Files…`, which a person runs, prompted by the trim reminder (built 2026-10-29: `Trim Reminder` in `docs/ui/command-palette.md`). **Agreed:** no automatic removal of catalog rows nothing references. The trim reminder keeps Trim from being forgotten. Finding those rows also needs the notes' contents, which are encrypted, so a keyless job couldn't do it anyway.
- **Hosted backup store:** a blob is deleted once no retained catalog snapshot references it and its retention lock has expired. This works from the plaintext columns, keylessly.
- **Verification:** every catalog `blob_id` exists live (and, once backed up, in the backup store). Spot-check by decrypting samples and comparing `content_hash`.

## 8. Restore and export

- **Whole vault at time T:** the notes and catalog pair at T, plus the blobs it references. Each blob is one object, so restore is parallel and resumable.
- **One file:** one blob, so "restore this attachment from yesterday" becomes possible later.
- **Markdown exports** read items through the catalog and write the plaintext originals into `attachments/`.
- The hosted own-copy download uses the same layout as the archive. `docs/future-plans/hosted-own-copy.md` already notes that its layout depends on this decision.

## 9. Migration from today's files database

Migrate on open, after a snapshot:
1. For each `files` row, write the original's blob and a catalog row. Write the previews as `preview-light` and `preview-dark` blobs with their own rows.
2. Check that every item decrypts and its hash matches.
3. Delete the old `.files.db` once every item has checked out (decided 2026-11-08). The backup taken before the migration is the way back; waiting for a person's backup would keep two copies forever for anyone who never makes one.

A backup made before this change holds a `.files.db` and is never altered: restoring one installs it and then migrates it like this.

Test it like every migration.

## 10. Still open

1. ~~Padmé alone, or plus a small random amount~~ **Decided 2026-10-27:** Padmé plus a small random amount (§4). **Decided 2026-11-08:** up to 1% of the file's size.
2. ~~Hosted retention of deleted files~~ **Decided 2026-10-27, for now:** keep them while any retained snapshot references them, disclosed in the privacy policy (§6). A cap such as 2 years may be revisited.
3. ~~Segment size~~ **Decided 2026-11-08:** 64 KiB (§13).
4. ~~The crash-leftover grace period~~ **Decided 2026-11-08:** 1 hour. The sweep schedule is left to whoever builds it.
5. Hosted storage classes: how many days before a blob moves to infrequent access, and how that tier treats small files.

## 11. Invariants

1. One stored item is one encrypted file on disk (and, hosted, one object in backup). Nothing is chunked across storage.
2. A blob is written once and never modified. Edits create a new blob.
3. A blob is written and synced before the catalog references it.
4. A backup a person handles is a whole archive. Uploading each blob once is only for backups MetaList runs itself (hosted, or a future cloud integration).
5. Only a person deletes files nothing references. Machines delete only crash leftovers and expired backup copies.
6. Names are random. In a vault with a password, stored sizes are padded and plaintext never touches disk.

## 12. Checked 2026-10-27 (filed from the inbox)

- Filed as a future plan, as its status asks. Confirmed: today's `files` and `file_previews` tables (`app/db/file_schema.py`) in `<vault>.metalist.files.db`; `docs/future-plans/hosted-own-copy.md` notes its layout depends on this.
- **When built:** this changes the files database's schema, so AGENTS.md's "Database Schema Changes Require a Version Bump" applies: a `CURRENT_DATABASE_VERSION` step in `app/db/migrations.py`, the encryption audit (`app/encryption_audit.py`) keyed on the version, every new plaintext column documented in `docs/security/README.md`, and AGENTS.md's backup immutability rules (§9's migration runs on the live vault only, never on a backup).
- The trim reminder it mentions was built 2026-10-29 (`Trim Reminder` in `docs/ui/command-palette.md`).

## 13. Built so far (2026-11-08)

**Built:** blobs and the catalog (`app/db/blob_store.py`, `app/db/file_schema.py`), streaming encryption (`app/security/streaming_blob.py`), migration 16→17 (`app/db/move_files_to_blobs.py`), backups and restore, crash recovery, the encryption audit, the crash-leftover sweep at startup, and downloads that stream and answer `Range` requests (`app/api/byte_ranges.py`).

**Built after it:** §14.

Where this differs from the sections above, the code is right:

- **§3, three tables, not one.** The catalog keeps today's `files`, `file_previews` and `file_texts`, each row naming one blob. (Database version 18 adds a fourth, `file_first_pages`: a PDF's first page for galleries, `docs/future-plans/gallery.md`.) It stores the same things with far less change. `kind`, `parent_item_id` and `backed_up_at` wait for hosted backups; a blob's padded size is its size on disk.
- **§3 and §4, one seal per blob.** `file_key_wrapped`, real size and `content_hash` are one payload, `blob_seal`, encrypted with the vault key like the row's other fields. Each blob, including a revision of an item, has its own key.
- **§4, header.** Each blob has its own random nonce prefix, and the whole header is each segment's associated data.
- **§5, deletion.** A blob in use is pinned and goes when its last reader finishes: Windows refuses to delete an open file, and a backup must find every blob its catalog snapshot names. During a password change or a restore nothing is deleted until the change commits, so a rollback finds every blob. Catalog connections use `synchronous=FULL`, so a blob already deleted cannot come back into the catalog after a power cut.
- **§6, archive format 2.** A backup holds `files/catalog.db` and one member per blob. A vault not yet moved is backed up in the old format, and older archives still restore: the old files database goes back, the catalog is emptied, and the next migration moves it.
- **§9.** A vault with no password has no unlock to take its safety backup, so startup takes one first (`back_up_before_passwordless_upgrade`).
- **Segment size (§10.3):** free to change only by a new format version now that real files use it.
- **Padding:** sits above the encryption. The real size in the seal cuts every read.

**Open (maintainer):** a browser's audio and video players send their own requests, without the tab's session header every file request needs. Letting them jump inside a file means a new way to authorize those requests; it is `docs/future-plans/media-jump-playback.md`.

## 14. Files of any size (built 2026-11-08)

Agreed with the maintainer 2026-11-03 and 2026-11-06, because streaming a segment at a time keeps memory small whatever a file's size. Before this each file was limited to 100 MiB, and folder imports skipped larger ones.

- **Uploads stream into their blob** as they arrive (`app/api/streaming_upload.py`, `FileUpload` in `file_storage.py`): a parsed form would hold them in a plaintext temporary file. The body is read in a context of its own: reading can resume the connection's reader, the event loop keeps the context it was resumed in for that connection, and the open transaction then broke the next request.
- **No per-file limit** in any deployment: not in the HTTP limits, the HTTPS proxy, imports or the checklist. `METALIST_MAX_ATTACHMENT_BYTES` and the server's four-transfer limit are gone; the browser still sends a few at a time so progress stays steady (`file-transfer-slots.js`).
- **One limit stays, and why:** 100 MiB, `MAX_IN_MEMORY_FILE_BYTES`, for what must hold a whole file in memory: an edited diagram, an email, the viewer's previews, a file's text for search, an image inlined in an export or compressed on import. Over it the file is stored, downloaded and found by name; a text file that size imports as a file.
- **Free space is checked first** against the free disk space less a reserve of 1 GiB or 5% of the disk, whichever is smaller. A disk that fills mid-write removes the partial file and says so (`app/services/disk_space.py`). Hosted will check the plan's remaining storage instead.
- **A folder dropped on the page is held encrypted** (`app/services/import_uploads.py`): each file under a random name, its key and real path only in the server's memory, so nothing about it is readable on disk and a restart or a lock ends the upload. Every vault's uploads are encrypted this way, with or without a password. Imports read through `ImportFolder` (`app/services/obsidian_import/import_folder.py`), which is either a folder on disk or this held one.
- **Multi-gigabyte uploads over HTTPS** can pass the proxy's 30-minute deadline (`app/https_proxy.py`, `MAX_REQUEST_SECONDS`) and then fail with a plain message. Resumable uploads are `docs/future-plans/resumable-uploads.md`.
- **Invariants:** no file is held wholly in memory to store, read, back up or restore, apart from the uses above; no per-file size limit in any deployment; a file too large to read for text is still kept and found by name.
