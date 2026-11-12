# Error reports, and logs that serve support

**Status:** Agreed with the maintainer 2026-11-11 (brainstorm). Ready to build. Part 3 (dropping the encrypted logs) is urgent: see §0.

The goal: when a red fatal overlay shows, MetaList keeps a report detailed enough that a script can turn it into a **failing browser test**, without any of the user's text in it except tag names.

---

## 0. Today (from the code, checked 2026-11-11)

- **The overlay** (`app/static/js/modules/error-overlay.js`, `showFatalError`) shows the message and stack only. Nothing reaches the server; a reload loses it.
- **Commands** pass through `CommandGate.run(label, …)` (`mode-manager/services/command-gate-service.js`), 184 call sites. Labels hold no user text, but some are built from code values (`contextMenu.note.${commandName}`, `mouse.drag_reorder_${drop.direction}`, `commandPalette.${commandName}`), so the set is not a closed list yet. `mode-logger.js` only prints to the console.
- **Request ids:** the server gives every request one (`app/main.py`, `diagnostic_request_id`) but returns it to the browser only in a 500's `diagnostic` (`api-error-diagnostics.js`). A 409 cannot be matched to its server line.
- **Encrypted logs are write-only.** After login every record goes to `<namespace>-server.auth-<time>-<id>.log.enc` (`activate_authenticated_logging`, `app/services/diagnostics.py`; `EncryptedLogSink`, `app/security/authenticated_logging.py`). Nothing in `app/` or `scripts/` calls `decrypt_log_records`: nobody, the user included, can read them.
- **They are never rotated or deleted,** unlike the plain log (Loguru, 25 MB rotation, 14 days). The maintainer's Mac: 404 files, 161 MB since 2026-08-12, 96 MB in 2026-11-01..11 (~9 MB/day). At start, `assert_log_disk_usage_within_bounds` **refuses to start MetaList** when the logs folder passes 512 MB (`_LOG_DIRECTORY_MAX_BYTES`). The folder was at 328 MB on 2026-11-11: at that pace MetaList stops starting around 2026-12-01. Dad's and Joe's installs grow more slowly toward the same wall.
- **The plain log is mostly noise:** 21,110 of 21,990 lines in `thomas-server.log` were successful `/static/` loads.
- **Plain logs of other namespaces** (`namespace-*.log`, old `test`/`obsidian-*` vaults) are compacted at 25 MB but never removed.
- **Browser suites** (`scripts/browser-*-regressions.mjs`, Puppeteer) already seed notes through `NotesAPI` in a throwaway, click by note id and type keys: the shape a generated replay test needs.

## 1. When a report is made

- **Always, in memory only:** a ring of the last 2 minutes or 500 inputs, whichever is less. Each entry is small (kind, note id and part, key code, redacted typed text, time). The first time a note is touched within the window, its redacted shape is copied once, so a replay can start from how it looked before the inputs. Nothing is written or sent; a reload discards it.
- **Only when the red overlay shows:** the client builds the report from the ring, the page's state, the recent requests, and the redacted notes. Not for the calm `InputRejected` banner or the connection banner.

## 2. What a report holds

```json
{
  "metalist": "0.12.3", "window": {"w": 1440, "h": 900}, "theme": "dark",
  "search": {"tags": ["work", "meetings"], "rest": {"redacted": "xxxx"}},
  "notes": [{"id": "4812", "parent": null, "order": 3, "folded": false,
             "tags": ["work"], "format": "markdown",
             "text": {"redacted": "Xxxxx: $\\frac{x}{x}$"}}],
  "inputs": [{"t": 0,   "kind": "click", "note": "4812", "part": "content", "offset": 12},
             {"t": 410, "kind": "key",   "code": "KeyE", "mods": []},
             {"t": 900, "kind": "type",  "text": {"redacted": "xx0"}}],
  "commands": [{"t": 0, "label": "listEdge.leave_edit", "ms": 38, "outcome": "ok"}],
  "requests": [{"t": 1203, "route": "PUT /api/notes/{id}/preview", "note": "4812",
                "status": 409, "ms": 12, "requestId": "3fa2c1d0", "answeredAt": 1215,
                "server": {"errorType": null, "codeLocation": null}}],
  "error": {"class": "HttpRequestError", "message": {"redacted": "XXX xxxx xxxxxx: 000 Xxxxxxxx"},
            "frames": ["api-client.js:205 _apiCall", "edit-preview.js:88 refresh"]}
}
```

- **Inputs:** clicks, double-clicks and drags by note id plus part of the note (content with character offset, fold arrow, tag chip, badge) or, off the notes, by control (menu item by its command label, button by its id); keys by `code` and modifiers; typing, pastes and dictation as redacted text; dropped files as type, size and redacted name; scrolls, window resizes, focus and visibility changes; all with times.
- **State:** window size, theme and skin, the preferences that change behavior, search tags, sort, mode (view/edit), the involved notes' tree, order, folds, tags, format and redacted text.
- **Requests:** route with ids in place (`{id}`), note id, status, send and answer times (so the order of answers is known), request id, and the server's own safe record of that request: error type and code line, never its message. **Every server answer carries its request id** (a header), not only 500s.
- **Error:** class, redacted message (a parser's message can quote the formula), stack frames (code only).

## 3. Redaction

- **Note text, typed text, pastes, file names, non-tag search words, error messages:** letters become `x`/`X`, digits `0`; spacing and line breaks stay, so words keep their lengths (clicks land by character offset, and notes wrap and scroll about as they did). Only characters MetaList reads as syntax stay: Markdown, CSV, formulas, addresses, markers (`# * _ - + > | [ ] ( ) { } \ $ @ / , . : = ~` and the backtick; the exact list is settled when built). Prose-only punctuation (`? ! ' "` and curly quotes) becomes `x` (agreed 2026-11-11).
- **MetaList's own words stay, only where they work as syntax:** a list shipped with MetaList of LaTeX command names (`\frac`, `\sum`), Mermaid keywords (`graph`, `TD`, `subgraph`, `end`), note markers and fence names (`@csv`, `@markdown`, `mermaid`, `json`), kept only inside a `$…$` formula, a fence, or a marker's place. `$\text{late fee}$` → `$\text{xxxx xxx}$`; prose `the end of the graph` → `xxx xxx xx xxx xxxxx`. Without it, formulas and diagrams would not parse in the replay.
- **Kept as they are:** tag names (checked against the vault's tags), ids, numbers, values from MetaList's lists.
- **`@password` / `@username` values:** a fixed `••••••••`, as in exports.
- **The guarantee (the maintainer's design):** one final check over the finished report before it is kept. Every word in a redacted text must be only `x`, `X` and `0`, or on MetaList's word list; every other string must be a vault tag, an id, or a value from MetaList's lists (command labels, key codes, routes, control parts). Anything else throws. The error names where (`notes[2].text`), never the word, and the overlay adds one line that the report was not made.
- **Command labels become a closed list:** the template-built labels in §0 are spelled out.
- **Proof:** a test fills notes, non-search tags, file names, pastes and a KaTeX error with unique marker words, plays every kind of input, forces an error, and fails if a marker appears anywhere in the report's bytes.

## 4. Where reports go, what the user sees

- Each report is **kept encrypted** in the vault's folder, the last 20; older ones are deleted. An unencrypted vault keeps them plain, as its notes are.
- The overlay gets one button: **Export Report…** (saves that report as readable JSON where the user picks).
- The command palette gets **Export Error Reports…** (pick which kept reports, save one readable file). Hidden when there are none.
- **No automatic sending, no consent dialog:** the user exports a file they can open and read, and sends it themselves. That is their say. This holds for the personal and self-hosted profiles (`docs/ready-to-build/deployment-profiles.md`): nothing leaves a machine the user runs.

### 4a. Hosted

On the hosted service the server is the maintainer's, so a report never leaves anything: the browser hands it to the server it already talks to, and the server keeps it for the operator beside its logs. Agreed 2026-11-11:

- **On by default,** no opt-in. Settings has a switch to turn it off. The hosted service's privacy page says it keeps redacted error reports.
- **Tag names become stand-ins** (open question 8), so the operator sees no tag a user wrote, consistent with hosted vaults being encrypted with the user's password.
- **Kept by the operator** for a bounded time (to set, `docs/ready-to-build/unbounded-growth-audit.md`), and readable by the user through Export Error Reports… as everywhere else.

## 5. Replay: a report becomes a failing test

A script (`scripts/` …, name to choose) turns a report into a browser suite of the existing shape:

1. Start a throwaway and seed the redacted notes (new ids mapped from the report's), window size, theme, preferences and search.
2. Replay the inputs with their recorded gaps.
3. **Force the recorded answer order:** with Puppeteer request interception the test holds each server answer until the ones answered before it in the report have arrived. A race such as the edit preview's 409 (the preview answered while a save was still running) then fails on every run. Test-only; MetaList's code does not change.
4. Expect no red overlay.

## 6. Logs

- **Drop the encrypted logs. Built 2026-11-11:** an unlocked vault writes no log file (`activate_authenticated_logging`, `app/services/diagnostics.py`); full exception text is never written; printed output stays encrypted per record. The maintainer's 404 existing `.log.enc` files (161 MB) were deleted on his say 2026-11-11; other installs keep theirs (open question 1). **Still to build:** one plain log, before and after login, holding only safe things: routes, timings, statuses, error types and code lines, never error messages or note text. This removes the unreadable files, the encryption machinery for logs, and the 512 MB start-up wall (§0).
- **The plain log after login needs the same guarantee:** only records from an allow-list of MetaList's own events. Third-party loggers must not pass as they are: `httpx` logs every fetched URL (`HTTP Request: GET https://…`), and after login those include the links in notes whose titles are fetched.
- **Stop logging successful `/static/` loads;** failures and slow loads stay.
- The encrypted `stdout`/`stderr` streams can go once the plain log's guarantee covers what is printed (open question 6).
- `docs/security/README.md` ("Sensitive Telemetry") is rewritten in the same change.

## 7. Open questions

1. **Existing `.log.enc` files on other installs** (Dad's, Joe's): nobody can read them, and new ones are no longer written, so they no longer grow toward the 512 MB cap. Delete them on upgrade, or by hand? The maintainer's own were deleted by hand 2026-11-11.
2. ~~Ship §6 first?~~ Its urgent part (no encrypted log files) was built 2026-11-11.
3. **The 512 MB wall itself:** refusing to start over log size is a hard failure for something the user cannot fix. Keep it (fail loud) with retention that makes it unreachable, or replace it with deleting oldest logs? Plain logs of removed or old namespaces are never cleaned today.
4. **Errors before login** (login page): no notes or tags, and no key to encrypt with. Keep the report in memory only, exportable from the overlay?
5. **Where the vault's reports live:** a folder beside the vault's databases (no schema change) is the assumption; storing them in a database table would need a version bump (AGENTS.md).
6. **`stdout`/`stderr` after login** once the encrypted streams go: anything printed would reach the terminal in plain text. Confirm nothing prints user data (the existing canary tests cover passwords only).
8. **Tag stand-ins everywhere?** On hosted (§4a) tag names must not reach the operator, so there each tag becomes a same-shape stand-in, consistent within the report (`work` → `xxxx`, `home` → `xxxy`; slashes, `@`, capitals and alphabetical order kept). Recommended: stand-ins in every profile, so there is one kind of report and none holds real tag names. Not yet agreed.
7. **Command labels from the ontology modal** (`ontology-modal.js:659`, `CommandGate.run(name, …)`): check where `name` comes from before closing the list.
