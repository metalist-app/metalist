# Audit: everything that only grows

**Status:** Asked for by the maintainer 2026-11-11. Ready to do. Found while designing error reports (`docs/ready-to-build/error-reports.md`): the encrypted logs are a new file per login, never rotated or deleted, and MetaList refuses to start once the logs folder passes 512 MB, about three weeks out on the maintainer's Mac. Anything else that accumulates without end is a minefield of the same kind: it works for months, then fails on a user's machine with nothing they can do.

## The task

Go through every place MetaList writes, on disk and in its databases, and for each answer:

1. **What makes it grow?** Per login, per request, per edit, per link, per error…
2. **What bounds it?** A count, an age, a size, or deletion when its owner goes (a note, a link, a vault). "Nothing" is a finding.
3. **Who deletes, and when?** Name the function. A bound that only a manual command enforces (`commandPalette.trimUnusedFiles`) counts as no bound unless something prompts for it.
4. **What happens at the limit?** A hard stop (like the 512 MB start-up check) must be unreachable in normal use, because the user cannot fix it.
5. **A test** that grows it past its bound and checks it stays bounded.

Backups are the exception that proves the rule: safety backups got their own retention on 2026-11-08 (AGENTS.md, "Backup Immutability"). Any deletion in a backup folder goes only through the paths approved there.

## Seed list (a first look on 2026-11-11, the maintainer's Mac; check each)

| What | Where | Bound today | Size seen |
|---|---|---|---|
| Encrypted logs, a file per login | `~/MetaList/logs/*.auth-*.log.enc` | **none** (to be dropped, `error-reports.md` §6) | 161 MB, 404 files |
| Plain logs of other or removed namespaces | `~/MetaList/logs/<ns>-server*.log`, `namespace-*.log`, `namespace-rename-*.log`, `namespace-delete-*.log` | compacted at 25 MB each, **never removed** | part of 167 MB |
| Plain log of the running namespace | `<ns>-server.log` | 25 MB rotation, 14 days | 7 MB |
| `ollama-managed.log` | `~/MetaList/logs/` | check | |
| The logs folder as a whole | `assert_log_disk_usage_within_bounds` | **refuses to start** over 512 MB | 328 MB |
| Root `metalist.db` (tables `items`, `config`) | `~/MetaList/metalist.db` | check: still used, or left from before namespaces? | 225 MB |
| Safety backups | `namespaces/<ns>/backups` | newest 3 (2026-11-08) | 526 MB, 3 files |
| Backups in a user-chosen folder | user's folder | the user's retention setting | |
| File blobs no note uses | `namespaces/<ns>/files/blobs` | manual Trim Unused Files only | 122 MB folder |
| File revisions, diagram previews | `files/catalog.db` | check | |
| Link titles, link icons (cached per address) | `link_titles`, `link_icons` tables | check: kept after the last note with that link goes? | 1,346 and 577 rows |
| Search interaction history | `search_interaction_history` | check: one row, but does its payload grow? | 1 row |
| AI chat history | `ai_chat` | check, same | 1 row |
| Ontology rules, tag activity, proposed tags | tables | check | 8,048 rules |
| Update jobs | `~/MetaList/update-jobs` | check | 4 |
| `.partial` archives | backup folders | `delete_partial_archives` | |
| The updater's uv cache | managed cache (`update_installer.py`) | check: old uv versions kept? | |
| Throwaway and test data folders | scratch dirs (`npm run throwaway`, test runs) | throwaway deletes on Ctrl-C; check crashes and test runs | |
| Browser storage | `localStorage`, `sessionStorage`, IndexedDB | check | |
| In-memory stores | server caches, client rings | check each has a cap | |

Error reports, once built, keep the last 20 (`error-reports.md` §4); they go in this list with their test.

## Done means

Every row has a bound, an owner that enforces it, and a test, or an agreed reason it needs none. A hard stop at a limit is either removed or made unreachable by that bound. Findings that need deleting a user's files (the existing `.log.enc` files, the root `metalist.db` if unused) are asked about first.

## A ShockHarness rule to propose

**Shape:** a file opened for writing whose name contains a timestamp, random id or counter (a new file per run, login or event), in a directory where nothing in the repository deletes files matching that name pattern. **Why it bites:** each run adds a file and nothing ever takes one away, so the folder grows until a disk or size check fails, months later and on a user's machine. **False positives:** deliberate archives the user owns (exports, backups in a folder they chose); a declared retention owner silences it. Database tables keyed on an ever-growing value with no delete path are the same bug, but harder to match generally.
