# Back Up Now: remember which vaults are checked

**Status:** Agreed with the maintainer 2026-10-28. Ready to build. Small: a bug fix plus one rule.

Written from a read-only look at the repo. Check the code references before relying on them.

---

## 1. The bug

In `Back Up Now…` (Backup Settings), the vault checkboxes don't keep what the user chose. Every time the dialog opens, every vault is checked again.

- **The server already saves the choice.** `POST /api2/backup/run` saves the folder, the checked vaults and the number of backups to keep (`app/api/routes/backups.py`, `run_backup` → `update_backup_settings` in `app/services/backup_settings_service.py`). `GET /api2/backup/settings` returns the saved vaults, minus deleted ones (`_serialize_settings_response`).
- **The dialog ignores it.** `loadSettings` in `app/static/js/modules/modals/backup-settings-modal.js` sets `selectedNamespaces: this._defaultSelectedNamespaces(payload.available_namespaces)`, i.e. every vault. That came in with commit `4cdd031e` ("Checkpoint namespace database cleanup", 2026-06-07); before it, the dialog used `payload.selected_namespaces`. The folder and the number to keep are still remembered correctly.

## 2. The rule

1. **The dialog opens with the vaults checked as they were at the last backup.**
2. **A vault created since then starts checked.** An unchecked new vault would silently never be backed up, with nothing to warn about it; an extra checked one costs a little disk space and is visible in the dialog.
3. A deleted vault disappears from the list, as today.
4. **The vault you're in is always checked, and its checkbox is locked** (shown checked and disabled). Only the other vaults can be checked or unchecked. From inside a vault you always want that vault backed up; the remembered choice is only about which others come along. The "Choose at least one vault to back up." error can no longer happen, so remove it. The server should refuse a run that leaves out the current vault.
5. Unchanged: the settings stay per vault, on purpose. Each vault's server saves them in its own database, so a backup started from another vault uses that vault's own choice. Different vaults can have their own folder and backup cadence, and a rarely used vault may be left out of an everyday vault's backups while always backing itself up.
6. Unchanged: with only one vault, no checkboxes are shown.

## 3. Suggested approach

- **Remember the unchecked vaults rather than the checked ones.** The dialog checks every available vault except those. A saved "checked" list can't tell a new vault from one that was deliberately left out.
- The remembered unchecked list never contains the vault you're in.
- Keeping `selected_namespaces` in the API (worked out from the unchecked list and the available vaults) keeps the restore dialog's folder chooser working: `_pickAndPersistBackupFolder` in `backup-restore-modal.js` reads the settings and writes them back with a new folder. If the API changes instead, update that caller too.
- **Convert the saved setting once, with no compatibility code afterwards.** The only existing vaults are two personal installs; nothing should be kept for old settings formats. (Since June the dialog has checked everything, so the saved choice is very likely "all checked" in both.)
- Remove `_defaultSelectedNamespaces` if nothing else needs it.

## 4. Done when

1. Uncheck a vault, run a backup, reopen `Back Up Now…`: that vault is still unchecked, the others checked.
2. Create a new vault, reopen `Back Up Now…`: the new vault is checked, the unchecked one still unchecked.
3. Delete a vault that was unchecked: it's gone from the list and nothing breaks.
4. The vault you're in is checked and can't be unchecked; a run request without it is refused by the server.
5. `Choose Backup Folder…` in the restore dialog still saves the folder without changing which vaults are checked.
6. Tests cover 1–5; `docs/ui/command-palette.md` (`Back Up Now…`) says the choice is remembered per vault, new vaults start checked, and the current vault is always included.

## Found when filed (2026-10-28)

- References check out: `_defaultSelectedNamespaces` (`backup-settings-modal.js:244`, used in `loadSettings` at `:383`), the `Choose at least one vault to back up.` error (`:487`), `run_backup` → `update_backup_settings` (`app/api/routes/backups.py:895`/`:905`), `_serialize_settings_response` (`:192`), commit `4cdd031e`, and `_pickAndPersistBackupFolder` (`backup-restore-modal.js:634`).
- The settings are one encrypted JSON payload (`app_settings.backup_settings_json`, with its nonce and tag; `app/db/backup_settings_sql.py`, classified in `app/encryption_audit.py`). Storing an unchecked list instead of a checked one changes only the payload, not the schema, so no database version bump. The one-time conversion runs on the decrypted payload, after unlock.
- No open questions.
