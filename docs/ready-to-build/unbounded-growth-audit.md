# Audit: everything that only grows

**Status:** Asked for by the maintainer 2026-11-11. **Audit done 2026-11-11** (read the code, measured the maintainer's `~/MetaList` read-only; nothing deleted or changed). Findings below. **Every agreed fix was built the same day** (see Decisions and each row); nothing is committed yet. Found while designing error reports (`docs/ready-to-build/error-reports.md`): the encrypted logs were a new file per login, never rotated or deleted, and MetaList refuses to start once the logs folder passes 512 MB. Anything else that accumulates without end is a minefield of the same kind: it works for months, then fails on a user's machine with nothing they can do.

## The task

Go through every place MetaList writes, on disk and in its databases, and for each answer:

1. **What makes it grow?** Per login, per request, per edit, per link, per error…
2. **What bounds it?** A count, an age, a size, or deletion when its owner goes (a note, a link, a vault). "Nothing" is a finding.
3. **Who deletes, and when?** Name the function. A bound that only a manual command enforces (`commandPalette.trimUnusedFiles`) counts as no bound unless something prompts for it.
4. **What happens at the limit?** A hard stop (like the 512 MB start-up check) must be unreachable in normal use, because the user cannot fix it.
5. **A test** that grows it past its bound and checks it stays bounded.

Backups are the exception that proves the rule: safety backups got their own retention on 2026-11-08 (AGENTS.md, "Backup Immutability"). Any deletion in a backup folder goes only through the paths approved there.

## Findings

Verdicts: **stop** = can stop MetaList or a feature; **grows** = no bound; **gap** = bounded except in a case named; **ok** = bounded, owner named. Sizes are from the maintainer's Mac, 2026-11-11.

### Logs (`~/MetaList/logs`, 167 MB, 39 files)

| # | What | Grows by | Bound today, and who enforces it | At the limit | Verdict |
|---|---|---|---|---|---|
| L1 | The logs folder as a whole | everything below | `assert_log_disk_usage_within_bounds` (`app/services/diagnostics.py:409`), called once at start (`configure_process_diagnostics`, `:323`): over 512 MB (`_LOG_DIRECTORY_MAX_BYTES`, `:34`) it raises | **MetaList does not start.** Reachable: L2 and L3 have no folder-wide bound, so about 7 abandoned vault names at their caps, or a log storm within 14 days (L3), passes 512 MB | **stop** |
| L2 | Logs of vaults that no longer exist (deleted, renamed, test vaults): `<ns>-server.log`, `<ns>-server.<time>.log`, `<ns>-server.fault.log`, `namespace-<ns>.log`, `namespace-delete-<ns>.log`, `namespace-rename-<a>-to-<b>.log` | per vault name ever run, deleted or renamed | Each direct-append file is compacted to its last 10 MB once over 25 MB (`recycle_direct_append_log_file`, `diagnostics.py:327`; patterns `:35`). **Nothing removes them:** the delete worker removes only the vault folder (`_delete_namespace_directory`, `app/services/namespace_deletion_worker.py:123`), the rename worker moves only the vault folder (`namespace_rename_worker.py:87`). A stopped vault's rotated server logs are never aged out (L3) | counts toward L1 | **grows**. 62 MB now: `codex`, `default`, `obsidian`, `obsidian-2`, `obsidian-3`, `obs-4`, `temp`, `test`, `test2` |
| L3 | Server log of a running vault, `<ns>-server.log` | every log line, ~3 MB/day on `thomas` | loguru: rotation at 25 MB, retention 14 days (`diagnostics.py:29-30`, `:287-296`). loguru applies retention **only when this sink rotates** (`loguru/_file_sink.py`, `_terminate_file`), by age only, no count | A storm of log lines makes any number of 25 MB files within 14 days → L1 | **gap** (age, no count) |
| L4 | `<ns>-server.fault.log` | faults, thread dumps on SIGUSR1 | compacted like L2, at start and every 5 min (`start_direct_append_log_recycler`, `:433`) | — | ok, but see L4b |
| L4b | loguru's retention glob for `<ns>-server.log` includes `<ns>-server.*.log`, so it **matches the fault log** | — | At a rotation, a fault log older than 14 days (it is opened at start and rarely written, so its age is the uptime) is deleted while faulthandler still holds it open. On Windows `os.remove` of an open file fails, so retention stops partway and other old rotated files may stay | Mac: fault output after that goes to an unlinked file. Windows: a loguru error per rotation | **bug** |
| L5 | `namespace-<ns>.log` (the child process's stdout/stderr, encrypted per record after unlock) | per vault start, per printed line | compacted at 25 MB (`namespace_switcher.py:1736-1738`, L2's recycler) | — | ok while the vault exists (13 MB on `thomas`) |
| L6 | `ollama-managed.log` (977 KB), and `~/MetaList/runtime/ollama/ollama-runtime.json` | nothing: Ollama support was removed (`fd09d7fd`) | nothing removes them | counts toward L1 | leftover |
| L7 | `*.auth-*.log.enc` | no longer written (built 2026-11-11) | the maintainer's deleted by hand; Dad's and Joe's remain (`error-reports.md` §7 question 1) | they count toward L1 on those machines, size unknown | leftover |

**Built 2026-11-11 (decision 1).** `app/services/log_retention.py` owns the folder; tests in `tests/unit/test_log_retention.py`.

- L1: the 512 MB start-up refusal is gone (`assert_log_disk_usage_within_bounds` and `calculate_log_disk_usage` removed). Each vault's logs stay under about 125 MB: 25 MB live server log, 2 rotated, a fault log and child output compacted at 25 MB.
- L2, L6: as a vault starts (`configure_process_diagnostics` → `trim_logs_directory`, under a lock file `.retention.lock`, since vaults start together), logs of vaults with no folder in `namespaces/`, and `ollama-managed.log`, are deleted once nothing has written them for a day. That covers delete and rename too: the workers keep writing their own `namespace-delete-…`/`namespace-rename-…` log, and Windows cannot delete an open file, so the workers themselves delete nothing. A name that reads two ways (`namespace-x-server.log`) stays while either vault exists; files named any other way (`*.log.enc`, the user's own) are never touched. `~/MetaList/runtime/ollama/` (4 KB) is left.
- L3, L4b: loguru's retention is `retain_newest_rotated_server_logs`: the newest 2 rotated files by count, and only rotated files, so the fault log its glob also finds is never deleted. The starting vault also trims its own rotated files to 2 (rotations under the old 14-day rule).
- Not done: the fault log keeps its name (renaming it would have changed `scripts/smoke_installed_package.py`; the retention function makes it unnecessary).

### The root `~/MetaList/metalist.db` (225 MB)

| # | What | Finding |
|---|---|---|
| R1 | `items` (13,728 rows), `config` | **The old MetaList's own database, not this MetaList's.** Only the old-MetaList importer read it (`--legacy-database`, `app/services/legacy_metalist.py`), and that was removed 2026-11-08 (`77ae370a`). Nothing in `app/`, `scripts/` or `main.py` opens it now. Last written 2026-08-01; it does not grow. It holds the maintainer's notes as the old app had them, so it is his to keep or delete; MetaList should never touch it. |

### Vault databases (`<ns>.metalist.db`: 149 MB, 108,970 notes; `files/catalog.db`)

| # | What | Grows by | Bound today | Verdict |
|---|---|---|---|---|
| D1 | `link_titles` (1,346 rows, 0.5 MB) | each distinct link address rendered (`app/services/content_formatting.py:1011`) | **none**: no `DELETE` outside `reset_for_tests.py:30`; rows stay after the last note with that link goes | **grows** (slowly) |
| D2 | `link_icons` (577 rows, 1.5 MB) | each distinct origin linked (`app/services/link_icons.py:265`) | **none**: no `DELETE` anywhere | **grows** (slowly) |
| D3 | `ai_chat` (1 row, 2.2 MB) | every turn: messages, activities, action logs, summaries (`app/services/ai_chat.py:441-451`) | each message ≤ 32,000 characters (`:25`); **no cap on count** ("Nothing is trimmed", `:422`). Only Clear Chat deletes (`delete_ai_chat_row`, `app/db/ai_chat_sql.py:92`). The whole row is re-encrypted and rewritten at turn start, turn end and each summary (`:453`, `:543`, `:568`, `:593`, `:652`): each write costs the whole chat | **grows** |
| D4 | `search_interaction_history` (1 row) | tag activity per day | 365 populated days (`MAX_TAG_ACTIVITY_RETENTION_DAYS`, `app/services/search_history_storage.py:10`), pruned on every write (`_prune_counts_by_date`, `app/services/search_history.py:176`) | ok |
| D5 | `notes.proposed_tags` | AI tag proposals | 12 per request (`app/api/note_requests.py:13`), one pending per tag name (`app/usecases/tag_proposals.py:76`), cleared on accept/reject | ok (no total cap per note, but each is a distinct tag) |
| D6 | `ontology_rules` (8,048) | the user adds rules | the user deletes (`delete_rule`, `app/db/ontology_rules_sql.py:115`) | ok (user's own) |
| D7 | `reminders` | the user adds | removed when done or deleted (`app/services/reminders.py:880`); a reminder on a deleted note stays, visible in the reminders list | ok (user sees it) |
| D8 | `tab_state`, `app_settings`, `namespace_content_migrations` | — | ≤ 1,000 tabs (`app/services/tab_state.py:34`); allow-listed preference keys (`client_state_service.py:55`); older migrations replaced | ok |
| D9 | Files no note uses (`files` rows and their blobs; 527 files, 121 MB of blobs) | upload, paste, import; deleting a note keeps its files (so undo works) | **Trim Unused Files** (`trim_unused_files`, `app/services/file_storage.py:869`), prompted by the trim reminder card at 10 MB unused and every further 10 MB (`app/static/js/modules/trim-reminder-schedule.js:13`, on by default) | ok (prompted); none if the user turns the reminder off |
| D10 | Diagram previews, file texts, first pages (`files/catalog.db`) | per diagram save, per readable file | one row per file and variant, upserted; the old blob is retired at once (`replace_file_content` → `_retire_blobs`, `file_storage.py:580`); rows cascade with their file (`app/db/file_schema.py:46`, `:66`, `:88`). No revision history is kept on disk | ok |
| D11 | Blobs no catalog row names (crash leftovers) | a crash mid-write | swept at every start if older than 1 h (`sweep_blob_leftovers`, `app/main.py:334`; `file_storage.py:83`). Measured: 584 blobs = 584 catalog references, none orphaned | ok |
| D12 | Free pages, `-wal` files | deletes; big transactions | no `VACUUM` outside migrations (`purge_migration_residue`, `app/db/migrations.py:564`); free pages are reused, so the file stays at its high-water size (1.8 MB free on `thomas`). WAL uses SQLite's default auto-checkpoint | ok (does not grow) |

### Backups

| # | What | Grows by | Bound today | Verdict |
|---|---|---|---|---|
| B1 | Safety backups, `namespaces/<ns>/backups` (526 MB, 3 each) | one per migration at unlock (`app/services/auth_service.py:298`), one per vault per in-app update (`update_backups.py:154`), Create Backup (`app/api/routes/auth.py:640`, used only by the smoke test) | newest 3 (`SAFETY_BACKUPS_KEPT`, `app/services/backup_service.py:90`; `trim_safety_backups_for_database`, `:1230`), after a migration at unlock (`auth_service.py:314`) and after an in-app update restarts (`metalist trim-safety-backups`, `main.py:750`) | ok, with B2, B3 |
| B2 | Safety backup before a **passwordless** vault upgrades at start (`back_up_before_passwordless_upgrade`, `backup_service.py:1247`, called at `app/main.py:290`) | one full copy, attachments included, per upgrade | **never trimmed** unless the in-app updater runs. Upgrading with `uv tool upgrade`, pip or a git pull adds a copy each time | **gap** |
| B3 | Safety backups of a **renamed** vault | per rename | the rename moves the folder (`namespace_rename_worker.py:102`) but archives keep the old name, and listing and trim match by name (`list_backups_in_directory`, `backup_service.py:1106`): they are invisible and never trimmed. Renaming them is forbidden (immutability) | **gap** (stranded) |
| B4 | Backups in the user's folder | Back Up Now, per vault ticked | the user's retention count, default 30 (`app/services/backup_settings_service.py:29`), applied in `run_backup` (`app/api/routes/backups.py:879-889`) to the vaults in that run only. Vaults unticked, renamed or deleted, and earlier folders, keep theirs | ok (the user's folder and setting) |
| B5 | `.partial` archives | a failed or crashed backup write | `delete_partial_archives` (`backup_service.py:880`) after success and before the next backup of that vault into that folder (`:848`) | ok (at most one per vault and folder) |

### Other files

| # | What | Grows by | Bound today | Verdict |
|---|---|---|---|---|
| F1 | `~/MetaList/update-jobs/<id>.json` and `<id>.log` (12 KB) | one pair per in-app update, failed ones included (`app/services/app_updates.py:128`) | **none** (only `active.json` and `.tmp` are ever removed, `:123`, `:92`) | **grows** (a few KB per update) |
| F2 | Updater's uv, `~/Library/Caches/MetaList/update-tools/uv-<version>-<target>` (51 MB; `%LOCALAPPDATA%\MetaList\update-tools` on Windows) | one folder per `INSTALLER_VERSION` (`app/services/update_installer.py:23`, `:122`) | **none**; a failed publish also leaves `*.tmp` (`:175-183`) | **grows** (51 MB per uv bump) |
| F3 | uv's package cache (default location; `UV_CACHE_DIR` never set) | each update preflight downloads with `--refresh` (`app/services/update_preflight.py:106`) | **none** (no `uv cache prune`). Shared with any other uv use (4.3 GB on the maintainer's Mac, mostly development) | **grows** |
| F4 | Vault delete and rename job files (`<tempdir>/metalist-runtime/namespace-{delete,rename}-jobs/<id>.json`, or `<data>/runtime/…` with `METALIST_DATA_DIRECTORY`; `app/server_runtime.py:39-41`) | one per delete or rename (`app/services/namespace_deletion_jobs.py:117`, `namespace_rename_jobs.py:113`) | none; the OS clears its temp folder | ok in temp; **grows** under a data folder (tiny) |
| F5 | Import uploads (`<data>/import-uploads/<id>/`) | each import started | discarded by the browser (`app/api/routes/imports.py:206`), at start (`app/main.py:188`) and at lock | ok |
| F6 | Python temp folders (backup, restore, pre-update, preflight venv, link icons) | each operation | removed by their context managers; left only after SIGKILL or power loss, then the OS temp clean-up | ok |
| F7 | `.recovery.lock`, `admission.lock`, certs (`network-settings.json` retired 2026-11-13, removed on first start) | — | one each | ok |

### Browser storage and memory

| # | What | Grows by | Bound today | Verdict |
|---|---|---|---|---|
| M1 | `localStorage`, `sessionStorage` | — | every key name is fixed (none per note, vault, search or URL); no list grows. No IndexedDB, Cache Storage or service worker | ok |
| M2 | Server `ViewCache._views` keyed by browser window and tab (`app/services/view_cache.py:42`) | each new browser window (a new `metalist_client_id`, `mode-context.js:1695`) | dropped per MetaList tab delete (`notes.py:613`) and at login, logout, lock, restore; **not** when a browser window closes (sync's idle eviction does not reach it, `app/services/sync.py:31-48`) | **grows** until lock |
| M3 | `AgentTraceStore` runs and events per session (`app/services/agent/trace.py:19`); `_discarded_run_ids` (`:20`) | every AI run and event | cleared with the chat or session; no cap on runs or events. `_discarded_run_ids` is never cleared, not even by `reset()` (`:24`) | **grows** (session; ids: process lifetime) |
| M4 | `content_cache` decrypted note text, tags (`app/services/content_cache.py:34-37`) | each note created | a deleted note is never evicted (no per-note removal); `clear_cache` only at lock and restore | **grows** with deletes until lock (and holds deleted notes' text) |
| M5 | `_HostPacer` per host (`app/services/link_titles.py:1056-1057`) | each host fetched for a title or icon | **none**; its `reset()` has no caller | **grows** (process lifetime, small) |
| M6 | `LoginRateLimiter._buckets` per client IP (`app/services/login_rate_limit.py:39`) | each IP that fails a login | dropped only when that IP returns or logs in (`:59`, `:79`) | **grows** per IP (matters only when reachable from a network, as the maintainer's is, `0.0.0.0`) |
| M7 | `SearchIndex` slots, `FileTexts._filters`, `provider_limits._GATES` | deletes leave dead slots; per file; per model | compacted at rebuild (`app/services/search_index.py:578`) or cleared at lock | ok (small, reset at lock) |
| M8 | Client object-URL caches: image and PDF previews (`file-image-preview-service.js:7`), remote images (`remote-image-proxy-service.js:7`), diagram previews and frame heights (`excalidraw-preview-service.js:16-21`), mermaid heights | each image, page or diagram viewed | released only on page unload | **grows** for the page's life (image blobs) |
| M9 | Bounded with caps (checked): undo stacks (100 operations, 32 clients, 32 MiB, `app/services/undo_state.py:316`), sync clients and clipboards (`sync.py:41-48`), loop stalls (50, `diagnostics.py:46`), active requests, file edit sessions (8), auth tokens (one session), remote image proxy (50,000 LRU), web evidence (64 pages), `SensitiveMemo` caches (count and bytes), floating messages (20) | — | as listed | ok |

### Development and test leftovers (maintainer's machine only)

| # | What | Grows by | Bound today | Verdict |
|---|---|---|---|---|
| T1 | `$TMPDIR/metalist-browser-*` (23 now, 63 MB; the scale suite's holds 100k notes) | every browser suite run (`scripts/browser-smoke.mjs:130`) | never removed, pass or fail (`:1042-1057` stops only the server) | **grows** until the OS cleans temp |
| T2 | `$TMPDIR/metalist-browser-suites-*`, `metalist-backup-reminder-*` | each runner run (`scripts/run-browser-suites.mjs:62`; `browser-backup-reminder-regressions.mjs:293`) | never | **grows** |
| T3 | `logs/checks/<time>/` in the repo (76 now) | each `full_checks.py` run (`scripts/full_checks.py:173`) | never | **grows** |
| T4 | Throwaway folders | `npm run throwaway` | deleted on Ctrl-C, SIGTERM, SIGHUP (`scripts/throwaway-metalist.mjs:165-173`), but not on Ctrl-C during `--notes` generation, a start timeout or a seeding failure; `--keep` keeps on purpose | **gap** |
| T5 | pytest data folder | each run | a `TemporaryDirectory` removed in `pytest_unconfigure` (`tests/conftest.py:16-30`) | ok |

Error reports, once built, keep the last 20 (`error-reports.md` §4); they go in this list with their test.

## Proposed fixes (each waits for the maintainer)

| # | Bound | Owner | Test |
|---|---|---|---|
| L1–L6 | **Built 2026-11-11**, see "Built" under Logs | `app/services/log_retention.py` | `tests/unit/test_log_retention.py` |
| D1, D2 | **Built 2026-11-11.** Each time the notes are loaded (startup, unlock), once the page has started (`auth_cache_state.after_page_ready`, registered in `app/main.py`), a thread reads which addresses and sites the notes link to (`content_formatting.urls_linked_in`; notes without `http` skipped: 0.45 s for 109,000 synthetic notes) and drops the other rows (`LinkTitleStore.forget_urls_not_in`, `LinkIconStore.forget_origins_not_in`), never one being looked up, none while locked | `app/services/link_row_pruning.py` | `tests/unit/test_link_row_pruning.py` |
| D3 | None: the maintainer keeps the whole chat until Clear Chat (decision 2) | — | — |
| B2 | **Built 2026-11-11** (decision 3): `back_up_before_passwordless_upgrade` says whether it backed up; once the upgrade at start has committed, `app/main.py` calls `trim_safety_backups_once_vault_is_current`, which refuses unless the vault is at the current version, then keeps the newest 3. The start-up sanity gate now resolves relative imports and lets `app/main.py` import only these two backup functions (`_MAIN_BACKUP_IMPORTS`) | `backup_service.py`, `app/main.py` | `tests/unit/test_safety_backup_trim.py`; `test_startup_sanity.py` |
| B3 | **Built 2026-11-11** (decision 3): the rename records the vault's former names in `former-names.json` in its folder (`app/services/vault_former_names.py`, written by `namespace_rename_worker._rename_namespace_storage`). In the vault's own backups folder, and only there (another vault may take an old name later), `list_backups_in_directory`, the trim and restore by name (`restore_own_backup`, which moves the launch profile to the current name) match those names too. The archives are never renamed | `backup_service._archive_names_of_vault` | `tests/unit/test_renamed_vault_backups.py` |
| F1 | **Built 2026-11-11.** The newest 10 jobs (by record mtime) are kept when a new one starts; the new one and the active one always stay | `app_updates._trim_update_jobs_locked` | `tests/unit/test_job_and_tool_retention.py` |
| F2 | **Built 2026-11-11.** Once the current uv is verified, other `uv-*` folders go, and staged `*.tmp` files over an hour old in the current folder. A failed delete stops that update attempt, loudly | `update_installer._remove_superseded_installer_files` | `tests/unit/test_job_and_tool_retention.py` |
| F3 | **Built 2026-11-11.** The updater's own uv runs `uv cache prune` (no `--ci`, no `--force`) after the safety-backup trim; a failure prints "updated, but uv's download cache was not pruned" and exits nonzero, the update itself already done | `self_update.PRUNE_UV_CACHE_ARGUMENTS` | `tests/unit/test_self_update.py` |
| F4 | **Built 2026-11-11, changed from the proposal:** the deleted and renamed pages poll a job's file, so it is not deleted when the job finishes; instead the newest 10 per kind are kept when a new job starts, and a pending one is never deleted (one whose worker crashed while pending stays) | `namespace_deletion_jobs._trim_finished_jobs`, same in `namespace_rename_jobs` | `tests/unit/test_job_and_tool_retention.py` |
| M2 | **Built 2026-11-11.** When sync forgets a client (idle, or over its client cap), its views go too: one idle timer | `view_cache`, `sync.py` | `tests/unit/test_view_cache_idle_clients.py` |
| M3 | **Built 2026-11-11.** 50 runs per session; 100,000 events per run, newest kept (`dropped_events` counted); discarded run ids keep the newest 10,000 (not cleared in `reset()`: late events of runs dropped before a reset must still be discarded) | `app/services/agent/trace.py` | `tests/unit/test_agent_trace_caps.py` |
| M4 | **Built 2026-11-11.** A delete evicts the notes from all four caches (`content_cache.forget_notes`, from `apply_delete_subtree`); undo caches them again through `apply_restore_records`. Four older delete tests' fixtures now fill the real cache (see Decisions) | `content_cache.py`, `delete_subtree.py` | `tests/unit/test_deleted_notes_leave_content_cache.py` |
| M5, M6 | **Built 2026-11-11.** A site whose spacing and cooldown are over is forgotten on each release or cooldown (`_HostPacer._forget_past_locked`); rate-limit buckets with no failure in the window go on each check and failure, a still-blocked one stays | `link_titles._HostPacer`, `login_rate_limit.py` | `tests/unit/test_link_title_pacing.py`, `tests/unit/test_login_rate_limit.py` |
| M8 | **Built 2026-11-11.** 200 entries per picture cache and size map (`app/static/js/modules/object-url-cache.js`). A dropped object URL is revoked only when no image the service set still uses it (weak references, inactive tabs included) and no element in the document, its open shadow roots or same-origin frames shows it; otherwise it is checked again at the next drop. A diagram preview stays while its other theme's is loading; a missing one is no longer cached | the four preview services | `tests/unit/picture_cache_bounds.test.mjs`, `object_url_cache.test.mjs` |
| T1–T4 | **Built 2026-11-11.** `scripts/run-folders.mjs` makes, removes and sweeps run folders (only `<prefix>` + 6 characters directly in the temp folder; sweeps those untouched for a day). A passing browser run removes its folder after its server exits; a failing one keeps it and prints it. The suites runner stops its runs with SIGTERM and waits (not `stopChildrenOnExitSignals`, which would SIGKILL them past their servers). `full_checks.py` keeps the newest 10 run logs. The throwaway stops and waits for every process, then deletes its folder, on every way it ends | `scripts/` | `tests/unit/run_folders.test.mjs`, `tests/unit/test_full_checks_run_logs.py` |

## Decisions (put to the maintainer one at a time)

1. **Logs (L1–L6): agreed and built 2026-11-11.** logs go with their vault, 2 rotated server logs per vault, and the 512 MB start-up refusal replaced by those bounds. This deletes the 62 MB of logs of the 9 vault names no longer present (`obsidian`, `test2`, `codex`…) and `ollama-managed.log`. Also answers `error-reports.md` §7 question 3.
2. **AI chat (D3): decided 2026-11-11, keep the whole chat.** No cap: the conversation is the user's own, and Clear Chat is its bound. Known cost: every turn rewrites the whole encrypted row (2.2 MB now), so turns slow down as the chat grows; revisit if that is ever felt.
3. **Safety backups: agreed and built 2026-11-11.** B2 (a passwordless vault's start-up upgrade) trims to the newest 3 like an unlock's upgrade. B3: a renamed vault lists, restores and trims its backups made under a former name, in its own backups folder only. Vaults renamed before this change have no record of their former names; their old-name backups stay as they are.
4. **The rest: agreed and built 2026-11-11** (D1, D2, F1–F4, M2–M8, T1–T4; see each row). Four older delete tests (`tests/unit/test_delete_notes_in_view.py`, two in `tests/unit/test_refactor_ordering.py`) stubbed the content cache getters and never filled the real cache, so M4's eviction raised; their fixtures now fill it and clear it after (agreed 2026-11-11).
5. **Root `metalist.db` (R1):** nothing to build; the maintainer may delete it by hand when he no longer wants the old app's copy.

## Found on the way (not growth; reported, not fixed)

- **Fixed 2026-11-11 (both items below):** a pre-update backup is now made by `backup_service.create_verified_backup_for_update`, the ordinary writer with its catalog, blobs and `.partial` publication (`tests/unit/test_update_backups.py`). Archives made before the fix are unchanged and still lack attachments, so restore now refuses a backup with no catalog or files database over a vault whose catalog names a file (`InputRejected`, maintainer 2026-11-11; `tests/unit/test_backup_service.py`). Into a vault with no files it still restores: nothing is lost.
- **Pre-update backups hold no attachments, and restoring one deletes every attachment** (code read, then reproduced in a test). `_database_sources` (`app/services/update_backups.py:35`) looks for the old `<ns>.files.db` sidecar, not `files/catalog.db` and `files/blobs`; the maintainer's `thomas-20261111-165620-264454` archive (96 MB) holds only the notes database. Restoring such an archive installs an empty catalog (`_install_staged_files`, `backup_service.py:1003`) and then sweeps every blob with no grace (`:1025`). These archives count among the 3 safety backups kept, so three updates in a row leave no backup with attachments.
- Pre-update archives are written straight under their final name (`update_backups.py:146`, `tarfile.open(..., "x:gz")`), not through the approved `.partial` and hard link, so a crash leaves a truncated archive under a real backup name.
- ~~**The HTTPS certificate is never renewed.**~~ Fixed 2026-11-11: valid 825 days, replaced at a start in its last 30 days (`ensure_default_tls_pair`, `docs/security/README.md`).
- **An update that fails in its detached shell blocks every later in-app update:** the job stays `installing` while the running version is below the target (`read_job`, `app_updates.py:104-107`), and `active.json` then rejects new jobs "already in progress" (`:122`) until deleted by hand.
- Import uploads share one folder for all vaults (`_holding_root`, `app/services/import_uploads.py:42`): any vault starting or locking (`discard_every_upload`, `:237`) deletes another vault's upload in progress.
- L4b above (loguru retention deletes the open fault log).

## A ShockHarness rule to propose

**Shape:** a file opened for writing whose name contains a timestamp, random id or counter (a new file per run, login or event), in a directory where nothing in the repository deletes files matching that name pattern. **Why it bites:** each run adds a file and nothing ever takes one away, so the folder grows until a disk or size check fails, months later and on a user's machine. **False positives:** deliberate archives the user owns (exports, backups in a folder they chose); a declared retention owner silences it. Database tables keyed on an ever-growing value with no delete path are the same bug, but harder to match generally.

The audit confirms the shape: it would have caught the `.log.enc` files, F1 (`<uuid>.json`/`.log`), F4 and T1–T3. It would not catch L2 (a file per vault name, not per run) or D1–D3 (tables and payloads); those need the "owner goes, its records stay" check by hand.
