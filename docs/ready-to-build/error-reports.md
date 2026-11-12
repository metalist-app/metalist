# Error reports, and logs that serve support

**Status:** Agreed with the maintainer 2026-11-11 and 2026-11-12. Ready to build. Built already: §6 (no encrypted logs; the safe plain log). **First build:** §1–§4 and §6a. **Later, not in the first build** (the maintainer, 2026-11-12): the replay generator (§5) and the hosted service's handling (§4a). Which session builds it is not decided yet.

The goal: when a red fatal overlay shows, MetaList keeps a report detailed enough that a script can turn it into a **failing browser test**, with none of the user's text in it, tag names included (§3), except the sentence or two a person types into a report they file themselves (§1).

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

- **Always, in memory only:** a ring of the last **10 minutes** (the maintainer, 2026-11-12; 2 minutes was too short for a problem reported after the fact), capped at 5,000 entries; if the cap is reached first, the oldest go. Each entry is small (kind, note id and part, key code, redacted typed text, time), and a run of typing in one note with no other input between is one entry, so the cap counts actions, not keystrokes. 500 entries would not reach 10 minutes: editing alone presses Enter, Backspace and arrows many times a minute. At roughly 100 bytes each the full ring is about half a megabyte. The first time a note is touched within the window, its redacted shape is copied once, so a replay can start from how it looked before the inputs. Nothing is written or sent; a reload discards it.
- **When the red overlay shows:** the client builds the report from the ring, the page's state, the recent requests, and the redacted notes. Not for the calm `InputRejected` banner or the connection banner.
- **When the user asks, with no red error** (the maintainer, 2026-11-12: his dad must be able to file a report when MetaList is slow or does something unexpected): **Report a Problem…** in the command palette builds the same report on the spot, from the same ring and page state, through the same redaction and final check. It opens a small dialog with one text box for a sentence or two about what went wrong (at most 300 characters) and an Export… button: what he typed is in view as he exports, and is exactly what the report carries (the maintainer, 2026-11-12). Export… keeps the report with the others and opens the same save dialog as Export Report…. Its `error` is empty and it is marked as made by the user.
- **For slowness,** a report (either kind) also carries the server's slow-request records (§6a: duration, wait for its turn, and how busy the computer and MetaList were) from the **last 15 minutes**, longer than the ring, because people report slowness some minutes after it happens. The server keeps them in a bounded ring in memory (15 minutes, at most 200 records); nothing new is written to disk for it. **How the two windows fit:** the inputs reach back 10 minutes and the slow-request numbers 15. The extra 5 minutes are numbers only, a few hundred bytes, and still say that MetaList (or the computer) was slow before the oldest input kept; a replay uses only the inputs and the requests that answered them.
- **Before login** (decided 2026-11-12): an error on the login page builds a report with no notes, tags or inputs from a vault, kept in memory only (there is no key yet to encrypt it with), and its overlay has Export Report… as any other. A reload loses it.

## 2. What a report holds

```json
{
  "metalist": "0.12.3", "window": {"w": 1440, "h": 900}, "theme": "dark",
  "search": {"tags": ["qzvt", "bnelrmox"], "rest": {"redacted": "xxxx"}},
  "notes": [{"id": "4812", "parent": null, "order": 3, "folded": false,
             "tags": ["qzvt"], "format": "markdown",
             "text": {"redacted": "Xxxxx: $\\frac{x}{x}$"}}],
  "inputs": [{"t": 0,   "kind": "click", "note": "4812", "part": "content", "offset": 12},
             {"t": 410, "kind": "key",   "code": "KeyE", "mods": []},
             {"t": 900, "kind": "type",  "text": {"redacted": "xx0"}}],
  "commands": [{"t": 0, "label": "listEdge.leave_edit", "ms": 38, "outcome": "ok"}],
  "requests": [{"t": 1203, "route": "PUT /api/notes/{id}/preview", "note": "4812",
                "status": 409, "ms": 12, "requestId": "3fa2c1d0", "answeredAt": 1215,
                "server": {"errorType": null, "codeLocation": null}}],
  "madeBy": "overlay",
  "error": {"class": "HttpRequestError", "message": {"redacted": "XXX xxxx xxxxxx: 000 Xxxxxxxx"},
            "frames": ["api-client.js:205 _apiCall", "edit-preview.js:88 refresh"]}
}
```

- **Inputs:** clicks, double-clicks and drags by note id plus part of the note (content with character offset, fold arrow, tag chip, badge) or, off the notes, by control (menu item by its command label, button by its id); keys by `code` and modifiers; typing, pastes and dictation as redacted text; dropped files as type, size and redacted name; scrolls, window resizes, focus and visibility changes; all with times.
- **State:** window size, theme and skin, the preferences that change behavior, search tags, sort, mode (view/edit), the involved notes' tree, order, folds, tags, format and redacted text.
- **Requests:** route with ids in place (`{id}`), note id, status, send and answer times (so the order of answers is known), request id, and the server's own safe record of that request: error type and code line, never its message. **Every server answer carries its request id** (a header), not only 500s.
- **Error:** class, redacted message (a parser's message can quote the formula), stack frames (code only). Empty (`null`) in a report the user made, whose `madeBy` is `"user"` instead of `"overlay"`.
- **Description** (`"description"`): only in a report the user made, the text typed into Report a Problem…, exactly as typed, at most 300 characters; absent from overlay reports.
- **Slow requests** (`"slow"`): the server's §6a records from the last 15 minutes, numbers and route templates only, the same allow-listed fields as the safe log.
- **How busy the computer is now** (`"machine"`): every report, made by Report a Problem… or on the red error, carries one §6a reading taken as it is made, the same numeric fields as a slow request (computer CPU % and available memory, swap in use, MetaList's own CPU % and memory). Added 2026-11-12 (the maintainer: "Yes, add it"), because a "MetaList feels slow" report with no request over 1 s said nothing about the computer.

## 3. Redaction

- **Note text, typed text, pastes, file names, non-tag search words, error messages:** letters become `x`/`X`, digits `0`; spacing and line breaks stay, so words keep their lengths (clicks land by character offset, and notes wrap and scroll about as they did). Only characters MetaList reads as syntax stay: Markdown, CSV, formulas, addresses, markers (`# * _ - + > | [ ] ( ) { } \ $ @ / , . : = ~` and the backtick; the exact list is settled when built). Prose-only punctuation (`? ! ' "` and curly quotes) becomes `x` (agreed 2026-11-11).
- **MetaList's own words stay, only where they work as syntax:** a list shipped with MetaList of LaTeX command names (`\frac`, `\sum`), Mermaid keywords (`graph`, `TD`, `subgraph`, `end`), note markers and fence names (`@csv`, `@markdown`, `mermaid`, `json`), kept only inside a `$…$` formula, a fence, or a marker's place. `$\text{late fee}$` → `$\text{xxxx xxx}$`; prose `the end of the graph` → `xxx xxx xx xxx xxxxx`. Without it, formulas and diagrams would not parse in the replay.
- **Tag names become stand-ins, in every profile** (the maintainer, 2026-11-12: real tag names would break the privacy the rest keeps). Each tag becomes a pseudo-random string of letters, unique within the report, and the same tag gets the same stand-in everywhere in it (search, notes, inputs on a tag chip). What a replay needs is kept: the same length and capitals (chip widths), a leading `@`, and folder slashes, each segment replaced on its own so `home/` and `home/garden/` share their first stand-in segment (`qzvt/` and `qzvt/mabrel/`); stand-ins are generated in the tags' alphabetical order so they sort the same way within the report. MetaList's own tags on its list (`@csv`, `@markdown`, `@password`) stay as they are. **Fresh for each report:** a new random map every time, so two reports cannot be lined up to see that one tag recurs, and nothing about a replay needs them to match across reports.
- **Kept as they are:** ids, numbers, values from MetaList's lists.
- **`@password` / `@username` values:** a fixed `••••••••`, as in exports.
- **The guarantee (the maintainer's design):** one final check over the finished report before it is kept. Every word in a redacted text must be only `x`, `X` and `0`, or on MetaList's word list; every other string must be a stand-in from this report's own tag map, an id, or a value from MetaList's lists (command labels, key codes, routes, control parts, MetaList's own tags). A real tag name is never allowed. The one exception is `description` in a report the user made: free text, allowed only there and only up to 300 characters. Anything else throws. The error names where (`notes[2].text`), never the word, and the overlay adds one line that the report was not made.
- **Command labels become a closed list:** the template-built labels in §0 are spelled out.
- **Proof:** a test fills notes, non-search tags, file names, pastes and a KaTeX error with unique marker words, plays every kind of input, forces an error, and fails if a marker appears anywhere in the report's bytes.

## 4. Where reports go, what the user sees

- Each report is **kept encrypted** in the vault's folder, the last 20; older ones are deleted. An unencrypted vault keeps them plain, as its notes are.
- The overlay gets one button: **Export Report…** (saves that report as readable JSON where the user picks).
- The command palette gets **Report a Problem…** (§1) and **Export Problem Reports…** (pick which kept reports, save one readable file; hidden when there are none). The list shows each report's time and its kind: the error's class for one the overlay made, "Reported" for one the user made. Called Export Error Reports… until 2026-11-12, renamed because the list now holds reports with no error; it pairs with Report a Problem….
- The last 20 kept are of both kinds together.
- **No automatic sending, no consent dialog:** the user exports a file they can open and read, and sends it themselves. That is their say. This holds for the personal and self-hosted profiles (`docs/ready-to-build/deployment-profiles.md`): nothing leaves a machine the user runs.

### 4a. Hosted (later, not in the first build)

On the hosted service the server is the maintainer's, so a report never leaves anything: the browser hands it to the server it already talks to, and the server keeps it for the operator beside its logs. Agreed 2026-11-11:

- **On by default,** no opt-in. Settings has a switch to turn it off. The hosted service's privacy page says it keeps redacted error reports.
- **Tag names are stand-ins,** as in every profile (§3), so the operator sees no tag a user wrote. The one text of the user's that reaches the operator is a `description` they typed into a report they filed.
- **Kept by the operator** for a bounded time (to set, `docs/ready-to-build/unbounded-growth-audit.md`), and readable by the user through Export Problem Reports… as everywhere else.

## 5. Replay: a report becomes a failing test (later, not in the first build)

A script (`scripts/` …, name to choose) turns a report into a browser suite of the existing shape:

1. Start a throwaway and seed the redacted notes (new ids mapped from the report's), window size, theme, preferences and search.
2. Replay the inputs with their recorded gaps.
3. **Force the recorded answer order:** with Puppeteer request interception the test holds each server answer until the ones answered before it in the report have arrived. A race such as the edit preview's 409 (the preview answered while a save was still running) then fails on every run. Test-only; MetaList's code does not change.
4. Expect no red overlay.

## 6. Logs

- **Drop the encrypted logs. Built 2026-11-11:** an unlocked vault writes no log file (`activate_authenticated_logging`, `app/services/diagnostics.py`); full exception text is never written; printed output stays encrypted per record. The maintainer's 404 existing `.log.enc` files (161 MB) were deleted on his say 2026-11-11; on other installs, **the first start after an update deletes them** (decided 2026-11-12; open question 1): only files named `<vault>-server.auth-<time>-<id>.log.enc` in the logs folder, alongside the log retention in `app/services/log_retention.py`. - **One plain log, before and after login, of safe things only. Built 2026-11-11** (`app/services/safe_log.py`; how it works: `docs/security/README.md` "Sensitive Telemetry"): routes as the app declares them, timings, statuses, request ids, counts, error types and code lines, never error messages or note text. Only records from an allow-list of MetaList's own events with typed fields; a loguru patcher checks each before any sink and anything else throws. Third-party loggers never pass as they are (`httpx` logs every fetched URL): below WARNING dropped, else package, error type and code frames only. A canary test proves marker words in notes, tags, searches, paths, error messages and fetched URLs never reach the console or the log file.
- **Successful `/static/` loads are no longer logged;** failures and slow loads (1 s or more) stay. **Every answer carries its request id** (`X-Request-Id`), and the browser's error line names it for any failed call (`api-error-diagnostics.js`).
- Still open here: the 512 MB start-up wall (open question 3) and the encrypted `stdout`/`stderr` streams (open question 6).
- The encrypted `stdout`/`stderr` streams can go once the plain log's guarantee covers what is printed (open question 6).
- `docs/security/README.md` ("Sensitive Telemetry") is rewritten in the same change.

### 6a. How busy the computer was, on each slow request

Agreed with the maintainer 2026-11-12, not built. Why: the maintainer's dad (Windows) finds MetaList slow while the maintainer does not, who suspects another program on the dad's computer. Nothing today records whether the computer was busy at the time.

- **When:** a request that takes 1 s or more to answer. *Found when filing:* the safe log has no such threshold for every request yet. 1 s applies only to static-file loads (`_SLOW_STATIC_LOAD_MS`, `app/main.py`), and the `request.slow` event (`app/services/safe_log.py`) comes from the in-flight watchdog for a request still running after 10 s (`_SLOW_REQUEST_SECONDS`, `app/services/diagnostics.py`). Building this adds the 1 s check on every answered request.
- **What:** one more allow-listed event in the safe log, numbers only:
  - the whole computer's CPU % and available memory, and swap in use if cheap to read;
  - MetaList's own process CPU % and memory;
  - the request's duration, and how long it waited for its turn to change the vault (the mutation slot, `_mutation_slot` / `_async_mutation_slot` in `app/api/transactions.py`, `bulk_operation_guard`).
- **And when a report is made** (added 2026-11-12): one more reading of the same numbers, measured over 0.3 s (`SNAPSHOT_SECONDS`, `app/services/request_history.py`), short enough that saving the report does not feel stuck. It is the report's `machine` field (§2); it is not written to the safe log.
- **How to read it:** the computer at 95% with MetaList at 3% means something else is the cause; MetaList at 80% means MetaList is. A long wait for its turn with both low means one change queued behind another.
- **Needs `psutil`,** a new dependency: `os.getloadavg()` does not exist on Windows, and memory and per-process CPU have no standard-library reading on every platform. Adding it goes through the supply-chain check and the dependency audit (`scripts/full_checks.py`), with wheels on Windows, macOS and Linux at Python 3.11 and 3.14.
- **Not part of the design, a possible later addition:** the browser's own long-task measure (`PerformanceObserver` with `longtask`), to tell a slow tab from a slow server.
- **Numbers only, never program names** (decided by the maintainer 2026-11-12): the names of the busiest programs would say what someone runs, and a process name is free text outside MetaList's lists, which the safe log refuses.

## 7. Open questions

1. ~~Existing `.log.enc` files on other installs?~~ Decided 2026-11-12: updates delete them (§6).
2. ~~Ship §6 first?~~ Its urgent part (no encrypted log files) was built 2026-11-11.
3. ~~**The 512 MB wall itself.**~~ Answered and built 2026-11-11: the start-up refusal is gone; logs are bounded per vault and go a day after their vault does (`app/services/log_retention.py`; `unbounded-growth-audit.md`, decision 1).
4. ~~Errors before login?~~ Decided 2026-11-12: in memory only, with Export Report… on that overlay (§1).
5. **Where the vault's reports live:** a folder beside the vault's databases (no schema change) is the assumption; storing them in a database table would need a version bump (AGENTS.md).
6. **`stdout`/`stderr` after login** once the encrypted streams go: anything printed would reach the terminal in plain text. Confirm nothing prints user data (the existing canary tests cover passwords only).
8. ~~Tag stand-ins everywhere?~~ Decided 2026-11-12: yes, pseudo-random letters, unique, fresh for each report (§3).
7. **Command labels from the ontology modal** (`ontology-modal.js:659`, `CommandGate.run(name, …)`): check where `name` comes from before closing the list.
9. ~~Names of the busiest programs on a slow request (§6a)?~~ Decided 2026-11-12: numbers only.
10. ~~A sentence typed into Report a Problem…?~~ Decided 2026-11-12: yes, kept as typed, at most 300 characters, the one free-text field the final check allows (§1, §2, §3).
11. ~~Is the 2-minute ring long enough?~~ Decided 2026-11-12: the ring reaches back 10 minutes, capped at 5,000 entries; no second ring (§1).

## 8. Acceptance checks (first build, written 2026-11-12 before the code)

What the maintainer should see; each is checked in a throwaway before the early look.

1. A red error ends with an **Export Report…** button; it saves one `.json` file, readable as text.
2. **Report a Problem…** in the command palette leaves edit mode (saving) and opens a small dialog: one text box and **Export…**, following the theme (Light, Dark, Fathom) and fitting a phone-width window.
3. Typing "it froze when I added a tag" and Export… saves a file whose `description` is exactly that sentence, and whose `madeBy` is `"user"` and `error` is `null`. The box takes at most 300 characters.
4. In any exported report no word of a note, tag or search appears: a note "Rent 1,450" shows as `Xxxx 0,000`; a tag `work` shows as four random letters, the same letters everywhere in that file; a second report gives it different letters; `$\frac{a}{b}$` keeps `\frac`.
5. A report holds the inputs of the last 10 minutes (clicks by note id and part, keys by code), the commands with their outcomes, and the requests with status and request id, in order.
6. **Export Problem Reports…** is in the palette only once a report is kept. It lists the kept reports newest first with their time and kind (the error's class, or "Reported"), lets the user pick, and saves one file. After a 21st report it lists 20.
7. A request that takes 1 s or more writes one line to the plain log with how busy the computer and MetaList were (CPU %, memory) and how long it waited for its turn; a report carries those of the last 15 minutes.
7a. Every report, with or without a slow request, carries `machine`: the computer's and MetaList's CPU % and memory as it was made, numbers only (added 2026-11-12).
8. An error on the login page shows Export Report… on its overlay; nothing is kept after a reload.
9. After MetaList starts with this version, no `*-server.auth-*.log.enc` file is left in the logs folder.
