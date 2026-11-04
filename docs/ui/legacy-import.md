# Bringing in the old MetaList's notes

Built 2026-11-04 (the maintainer: friend Joe moves from the old MetaList to this one with as little effort as possible). Joe installs MetaList, starts it, and is offered his old notes before he does anything.

## What the user sees

- **The offer.** A namespace with no notes and no password (a fresh install) whose data folder holds the old MetaList's file shows a dialog once it opens: "Notes from your old MetaList", "Bring them in?", **Not Now** and **Bring Them In**.
- **Protected notes** add an "Old password" field, focused, ready to type in. A wrong password says "Incorrect password" under the field (`docs/ui/modals.md`, messages under a field); nothing starts.
- **Bringing them in** shows the progress card "Bringing in your old notes…". The notes replace the empty namespace, the server restarts as after restoring the open vault, and the page reloads. Protected notes protect this MetaList with the same password, so the login screen asks for the old password, and that opens the notes. Unprotected notes come in unprotected, with no login.
- **An old password too weak for the password rules** (`AuthService.password_policy_error`) can't protect this MetaList: the dialog says why and asks for a new password and its confirmation. A new one that is too weak says so under its field. Everything is checked before anything is written.
- **Not Now, ×, Escape or a click outside** decline: the dialog is not offered again in this namespace (`pref.legacy_import_declined`). The palette's **Bring In Notes from Old MetaList…** stays while the old notes are offered, that is while the namespace has no notes and no password (`isCommandAvailable`).
- The old notes come in in the old order, as the old MetaList showed them.

## Rules

- **The old file is only read**, like a backup (`AGENTS.md`, Backup Immutability). It is opened read-only, hashed before and after the conversion, and a change meanwhile (the old MetaList still running and writing) installs nothing and asks to close the old MetaList and try again. Joe deletes the old file and his old exports himself, once he is happy: the old encryption is weak (below).
- **Only an empty namespace without a password is offered them.** The maintainer's own MetaLists have notes, so a `~/MetaList/metalist.db` of his own never asks.
- **Notes from an older old MetaList** (data version below 23) are refused, asking to open them once in the old MetaList, which updates them.

## How it works

- **The old file.** The old MetaList (a Node app, `MetaList_old`) keeps `~/MetaList/metalist.db`, in this MetaList's default data folder: an `items` table, one JSON row per top-level note (its children in `subitems`, `prev` and `next` chaining the order), and a `config` row `bundle` with the rest of what its Backup exports. A password encrypts the subitems only: AES-GCM keyed by one unsalted SHA-256 of the password, each item with its own 12-byte IV (`MetaList_old/js/utils/crypto.js`, `persist.js`). One item tells whether a password opens them all. `app/services/legacy_metalist.py` finds, reads and decrypts it.
- **The conversion** is `convert-from-legacy.py`, run by the server as its own process (`app/services/legacy_metalist_conversion.py`) with `--legacy-database` (the old file instead of an export) and `--passwords-from-stdin` (both passwords as one JSON line, nothing asked, never on the command line). It writes a whole namespace into a staging folder beside the old file; setting its password there leaves the server's own keys alone. `backup_service.install_converted_databases` installs it as the live namespace, as a restore installs an archive (checked, copied under the recovery journal, an empty files database when the conversion wrote none). The routes (`app/api/routes/legacy_import.py`: `status`, `check-password`, `convert`, `convert-protected`) hold maintenance, reset the runtime state and restart the server as a restore of the open vault does.
- **The dialog** is `app/static/js/modules/modals/legacy-import-modal.js`; `CommandPalette.offerLegacyImport()` opens it once the app is ready. After a conversion it reloads only once the server has gone and come back, never from the process about to restart.
- **At a terminal** the same converter reads an export or the old file: `convert-from-legacy.py --legacy-database ~/MetaList/metalist.db` (README, Legacy Import).

## Tests

- `tests/unit/test_legacy_metalist.py`: finding the old file (and not another file of that name), the order, refusals, decryption, the file left unchanged.
- `tests/unit/test_convert_encrypted_legacy.py`: the converter on an export and on the old file, asking nothing, refusing passwords that can't work before writing anything.
- `tests/unit/test_legacy_import_route.py`: what is offered where, the checks, maintenance and restart order, a real conversion into an empty live namespace, a file that changes meanwhile.
- `scripts/browser-legacy-import-regressions.mjs` (suite `legacy-import`, Chrome and Firefox): the offer at startup, a wrong password, Not Now remembered, the palette command, the conversion, restart and login.
- The encrypted fixture was written by the old MetaList's own code: `tests/fixtures/legacy-export/make-encrypted-fixture.mjs`.
