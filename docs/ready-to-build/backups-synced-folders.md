# Backups to synced folders: safe partial writes, a plaintext warning, suggested folders

**Status:** Agreed with the maintainer 2026-10-27. Small; ready to build. The three fixes in §1 are agreed. Wording and detection details are proposed, so adjust any that read badly.

Written from a read-only look at the code, without running it. Check every reference before relying on it; build only what's missing.

---

## 0. Background

- **Getting backups off the computer, for personal and self-hosted, works in layers.** The first is a backup folder inside Dropbox, Google Drive, OneDrive or iCloud Drive, whose desktop apps upload it. MetaList holds no cloud credentials. Today's `Back Up Now…` already supports this: pick a synced folder and it works. This note closes three gaps around it.
- **Coming later, as a separate future plan:** MetaList uploading to S3-compatible storage itself (`docs/future-plans/backups-s3.md`).
- **Never:** signing in to Google, Dropbox or Microsoft to back up. On a computer their desktop apps already do this.
- **How it works today:**
  - `Back Up Now…` writes one `<vault>-<timestamp>.metalist-backup.tar.gz` per vault into one folder, chosen with the native picker (`_pick_backup_folder_path`, `app/api/routes/backups.py`), and keeps the newest N.
  - Restore and pruning list only exact archive names (`_ARCHIVE_BACKUP_FILENAME_RE` with `fullmatch`, `app/services/backup_service.py`).
  - The archive's databases are ciphertext only when the vault has a password (manifest `encryption_enabled`).

## 1. The three fixes (agreed)

### 1.1 Never leave a half-written archive under a real name

- **Today:** `_create_archive_backup_for_paths` opens the final path directly (`tarfile.open(backup_path, mode="x:gz")`). A sync app can start uploading a half-finished archive. A crash or power loss mid-backup leaves a truncated archive under a valid name, which Restore offers and pruning counts as one of the N kept.
- **Fix:** write to `<final name>.partial` in the same folder, flush and fsync it, then rename it to the final name. That rename is atomic on one filesystem. Neither the restore picker nor pruning matches `.partial`, because the name pattern is a `fullmatch`.
- **Cleanup:** at the start of the next backup, delete leftover `.partial` files for that vault. Never delete a completed archive this way.
- Pruning runs only after the rename succeeds, so a failed backup never costs a good one.

### 1.2 Warn before plaintext goes to a synced folder

- **When:** the chosen folder is inside a synced location (§1.3) and a selected vault has no password.
- **What (proposed):** Backup Settings shows a warning beside the folder and asks before backing up: `This folder syncs to Dropbox, and "Recipes" has no password, so its notes will be readable there. Set a vault password, or back up anyway.` with **Back Up Anyway** and **Cancel**.
- **A warning, not a block:** the person chose the folder. Ask once per folder and vault, not on every backup. Ask again if the folder changes.
- Automatic backup paths, if any are added later, must not skip this warning; they ask before the first one.

### 1.3 Suggest the synced folders MetaList finds

- **Backup Settings lists any synced folders it finds** above the picker (proposed): `Dropbox › MetaList Backups`, `Google Drive › My Drive › MetaList Backups`, `iCloud Drive › MetaList Backups`. Choosing one creates the `MetaList Backups` subfolder if needed and selects it. The native picker stays for anything else.
- **Where to look (confirm on each platform):**
  - macOS: the entries of `~/Library/CloudStorage/` (current Dropbox, Google Drive and OneDrive clients mount there; their names start with the provider, such as `Dropbox`, `GoogleDrive-…`, `OneDrive-…`), and `~/Library/Mobile Documents/com~apple~CloudDocs` for iCloud Drive.
  - Linux: `~/Dropbox`.
  - Older clients may use `~/Dropbox` or `~/Google Drive` on macOS too.
- **The same check** decides "inside a synced location" for §1.2: the chosen path is at or under one of these folders.
- Read folder names only; never read or list the contents of those folders beyond checking that the subfolder exists.

## 2. Docs

- Add a line under `Back Up Now…` in `docs/ui/command-palette.md`: a synced folder is the way to keep backups off the computer, and MetaList suggests the ones it finds.

## 3. Acceptance checks

- Kill MetaList mid-backup (or simulate a failure while writing): no file with a valid archive name is left, Restore lists only complete archives, and the next backup removes the `.partial` file.
- A successful backup leaves only the final `.metalist-backup.tar.gz`, and pruning still keeps exactly N.
- With a Dropbox folder present under `~/Library/CloudStorage/`, Backup Settings suggests `Dropbox › MetaList Backups`, and choosing it creates and selects the folder.
- A vault with no password plus a synced folder shows the warning, and Back Up Anyway proceeds. The same vault with a plain local folder shows no warning, and so does a vault with a password and a synced folder.
- No synced folders present: no suggestions, and the picker works as before.

## 4. Checked 2026-10-27 (filed from the inbox)

- **Confirmed:** `_pick_backup_folder_path` (`app/api/routes/backups.py`); `_ARCHIVE_BACKUP_FILENAME_RE` matched with `fullmatch` (`app/services/backup_service.py`); `_create_archive_backup_for_paths` refuses an existing name, then writes `tarfile.open(backup_path, mode="x:gz")` straight to the final name; the manifest's `encryption_enabled`; Backup Settings and Backup Reminder (`docs/ui/command-palette.md`).
- **Conflict with AGENTS.md (§1.1):** "Backup Immutability" forbids `os.replace`/rename-style publication of a backup, and the `BKP001` startup gate (`app/startup_sanity.py`) can't be suppressed. Writing `.partial` and renaming it is that pattern. Options to settle before building:
  - Publish with `os.link(partial, final)`, which fails if the final name exists (exclusive, like `x` mode), then remove the `.partial`. It never overwrites, but hard links may not work in every synced folder (cloud-provider mounts under `~/Library/CloudStorage/` especially); test there first.
  - Or amend the rule to allow one specific publication: a no-replace rename of this backup's own fresh `.partial` (`renamex_np(RENAME_EXCL)` on macOS, `renameat2(RENAME_NOREPLACE)` on Linux; a plain rename on Windows already refuses an existing name), with the gate checking that shape.
- **Also for §1.1:** deleting leftover `.partial` files must stay distinct from deleting backups. `BKP001` allows deleting backups only in the retention workflow, so the cleanup needs its own clearly scoped function that matches only `.partial` names.
- **Open (proposed):** the warning's wording, "ask once per folder and vault", and the folder suggestions' names and places (§1.3, confirm each platform; Windows isn't listed yet).
