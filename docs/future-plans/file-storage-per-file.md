# File storage: one encrypted file per attachment, with a catalog

**Status:** Future plan. **Direction agreed with the maintainer 2026-10-23; don't build yet.** It's sent now so nothing new leans further on the single files database. The open points are in §10.

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
- **Metadata only, about 1 KB per item.** Thumbnails, previews and text never go in the catalog.
- Where file tags and extracted-text search live today stays as it is. *Check how they're stored now.*

## 4. Blob format, encryption and padding

- **Header:** magic `ML`, a suite byte (AES-256-GCM) and a version, followed by segments.
- **A per-item file key:** a fresh random 256-bit key per item, stored wrapped by the vault key in the catalog. This keeps bulk file encryption off the vault key's nonce budget, and lets one item be re-encrypted alone.
- **Streaming segments in one file:** fixed plaintext segments (64 KiB proposed), each sealed with a counter-derived nonce, the last marked final. This is the standard streaming-AEAD construction, as used by `age` and libsodium's secretstream. Large files stream, never sit wholly in memory, and are never plaintext on disk. Truncation, reordering and segment swapping are detected.
- **Padding:** the plaintext is padded with Padmé (at most about 12% overhead), plus a small random amount, so stored sizes don't identify known documents. The padding is removed on read using the real size from the catalog.
- **No plaintext ever touches disk.** Temporary files hold ciphertext only.

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
- **Files nothing references:** removed only by `Trim Unused Files…`, which a person runs, prompted by the trim reminder (separate note, `2026-10-27-trim-reminder.md`). **Agreed:** no automatic removal of catalog rows nothing references. The trim reminder keeps Trim from being forgotten. Finding those rows also needs the notes' contents, which are encrypted, so a keyless job couldn't do it anyway.
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
3. Keep the old `.files.db` until the next confirmed backup, then delete it.

Test it like every migration.

## 10. Still open

1. ~~Padmé alone, or plus a small random amount~~ **Decided 2026-10-27:** Padmé plus a small random amount (§4). How much is still to set.
2. ~~Hosted retention of deleted files~~ **Decided 2026-10-27, for now:** keep them while any retained snapshot references them, disclosed in the privacy policy (§6). A cap such as 2 years may be revisited.
3. Segment size (64 KiB proposed); tune on real files.
4. The crash-leftover grace period and the sweep schedule.
5. Hosted storage classes: how many days before a blob moves to infrequent access, and how that tier treats small files.

## 11. Invariants

1. One stored item is one encrypted file on disk (and, hosted, one object in backup). Nothing is chunked across storage.
2. A blob is written once and never modified. Edits create a new blob.
3. A blob is written and synced before the catalog references it.
4. A backup a person handles is a whole archive. Uploading each blob once is only for backups MetaList runs itself (hosted, or a future cloud integration).
5. Only a person deletes files nothing references. Machines delete only crash leftovers and expired backup copies.
6. Stored sizes are padded and names are random. Plaintext never touches disk.

## 12. Checked 2026-10-27 (filed from the inbox)

- Filed as a future plan, as its status asks. Confirmed: today's `files` and `file_previews` tables (`app/db/file_schema.py`) in `<vault>.metalist.files.db`; `docs/future-plans/hosted-own-copy.md` notes its layout depends on this.
- **When built:** this changes the files database's schema, so AGENTS.md's "Database Schema Changes Require a Version Bump" applies: a `CURRENT_DATABASE_VERSION` step in `app/db/migrations.py`, the encryption audit (`app/encryption_audit.py`) keyed on the version, every new plaintext column documented in `docs/security/README.md`, and AGENTS.md's backup immutability rules (§9's migration runs on the live vault only, never on a backup).
- The trim reminder it mentions is filed as `docs/ready-to-build/trim-reminder.md`.
