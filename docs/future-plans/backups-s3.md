# Backups to S3-compatible storage (future plan)

**Status:** Future plan, direction only. Agreed with the maintainer 2026-10-27. Don't build yet. File it under future plans so later work doesn't assume backups only ever go to a folder. Details marked *proposed* are suggestions.

Written from a read-only look at the code, without running it. Check every reference before relying on it.

---

## 0. Where this fits

- **Personal and self-hosted backups leave the computer in layers:**
  1. **Synced folders** (ready to build, `docs/ready-to-build/backups-synced-folders.md`): the backup folder sits in Dropbox, Google Drive, OneDrive or iCloud Drive, and their apps upload it.
  2. **S3-compatible storage**, this note: MetaList uploads itself, with an access key. One API covers AWS S3, Backblaze B2, Cloudflare R2, Wasabi and MinIO.
  3. **Never:** signing in to Google, Dropbox or Microsoft (OAuth). Layer 1 covers them through their desktop apps.
- **Azure Blob Storage** is a different API. Leave it out until someone asks.
- **Hosted is separate.** It keeps its own snapshot pipeline, where each file blob is uploaded once (`docs/future-plans/file-storage-per-file.md`).

## 1. Setup

- **A second destination in Backup Settings**, beside the folder: provider (or a custom endpoint), bucket, prefix, region, access key ID and secret.
- **The key is stored in the vault,** encrypted like the vault's other settings, never in plaintext on disk. It's usable only while the vault is unlocked, which is when backups run.
- **A vault password is required** for this destination (proposed). MetaList itself sends the data, so the bucket and anyone holding the key only ever see ciphertext.

## 2. Manual and automatic, both selectable (agreed)

- The menu offers either today's way, `Back Up Now` with Backup Reminder (the default), or **automatic backups** on a schedule (proposed: daily, or after a stretch of edits) while the vault is unlocked.
- **Automatic applies to the folder destination too.** Automatic backups replace the reminder; a failure shows a card, as the reminder does.

## 3. What gets uploaded (agreed)

- **The notes every time; each file once.** MetaList chooses what to upload here, not the person, so per-file upload is allowed. A backup a person moves by hand (the folder archive) stays one whole archive.
- **Listing the bucket is enough** to know which files are already there. A key without read access still works.
- **Each snapshot has a manifest** naming its notes database and the file blobs it needs. Retention keeps the newest N snapshots and deletes a blob only when no kept snapshot names it.
- Uploads are complete or absent, never half there: upload the manifest last, so a snapshot exists only once everything it names is uploaded.

## 4. `Test Connection` (agreed)

Setup mistakes should surface on day one, not at restore time. The test uploads a small file, reads it back, tries to delete it, and checks versioning or object lock, then reports in plain words (proposed wording):
- `This key can delete backups. Anyone with this computer could erase them.`
- `Deleted backups can be recovered for 30 days.` (versioning with a lifecycle rule)
- `This key can't read backups. Restore from the provider's console.` A write-only key is an accepted choice, not an error.
- `Versioning is off: a deleted backup is gone for good.`

## 5. Making the key easy to get (agreed direction)

AWS setup has many steps (bucket, versioning, a limited user, a hand-written policy, a key), and any of them can go quietly wrong.
- **Recommend Backblaze B2** in the help to people with no cloud account: a bucket and a key limited to it, in one form, with old versions kept by default.
- **For AWS, a one-click setup template** (CloudFormation) that creates the bucket with versioning, a user limited to one prefix, and its access key. The help page links to it.
- **Cloudflare R2** needs a bucket lock rule as well, since its tokens can delete.
- **Wasabi** is IAM-style, like AWS.

## 6. Restore from S3 (agreed)

As easy as backing up:
1. `Restore from Backup…` → **From S3**.
2. Enter bucket, prefix and key. On a new machine there is no vault yet, so the key can't come from one; it's typed or pasted from a password manager.
3. Pick a backup (vault, date, size).
4. Enter the vault password.

Needs read access; with a write-only key, say so (§4).

## 7. Invariants

1. No Google, Dropbox or Microsoft sign-in, ever.
2. A snapshot in the bucket is complete or absent.
3. Nothing reaches the bucket from a vault without a password.
4. Restoring is as easy as backing up, wherever the key allows reading.

## 8. Checked 2026-10-27 (filed from the inbox)

- Filed as a future plan, as its status asks; nothing built. `docs/future-plans/file-storage-per-file.md` exists, and its §6 anticipates this ("If MetaList later backs up to cloud storage itself").
- **Depends on per-file storage for §3:** today every attachment lives inside one `<vault>.metalist.files.db`, so "each file once" has no file to upload on its own until `file-storage-per-file.md` is built (or this extracts files from the database itself).
- **When built:** the key is a new vault setting, so AGENTS.md's "Database Schema Changes Require a Version Bump" applies (migration step, encryption audit, `docs/security/README.md`). Deleting snapshots and blobs from the bucket is retention of backups, so it must follow "Backup Immutability" too.
- **Open (proposed):** the vault-password requirement, the automatic schedule, and the `Test Connection` wording.
