# PLAN: scale testing, so a large vault cannot freeze MetaList unnoticed again

Written 2026-11-05, after 0.26.0 froze on a real vault (an import of 1,127 files, an AI question
with an empty search box) while 4,488 unit tests, 83 browser suites and a three-OS CI matrix
passed. The four fixes shipped in 0.26.1 (553e6e54); this plan is `feature/scale-testing`.

## What the test harness could not see

1. **Every test runs on a handful of notes.** Unit fixtures have 5 notes, the browser suites
   seed a few dozen, the throwaway seeds 12. Three of the four bugs are correct on small data
   and wrong on large data: a 15 s timer on a job whose length grows with the files, a quadratic
   loop over the view's notes, and CPU work on the request loop. None can show at 5 notes.
2. **No browser test runs the server's AI.** Every AI suite replaces `/api2/ai/chat` inside the
   browser (`window.fetch`), so the agent loop, its tools and the frozen scope never run in a
   browser test. The only server-side AI tests are unit tests with scripted models, on 5 notes.
3. **A blocked request loop is logged, never failed.** `EventLoopWatchdog` logs "event loop
   unresponsive" after 5 s. The 0.26.0 freeze logged 100 s stalls in a test server and nothing
   failed.
4. **A tool result's shape is a dict spread.** The empty search result dropped three keys the
   action log reads; no type could notice.
5. **Process:** the freeze was first "fixed" from a hypothesis. Reproducing it at the reporter's
   scale took an hour and found two bugs the hypothesis missed.
6. **The browser suites do not gate a release.** `browser-suites.yml` is "a check, not the
   release gate": 0.26.1 was tagged while two of its twenty jobs were red on the exact commit
   (Firefox `ai-chat-summary`, red on main for three runs; Firefox `ai-selected-note`). They were
   judged runner timing by hand, which is exactly the judgment a gate exists to remove.

## The change, in seven parts

### 1. Tools: a scripted server-side AI and a generated large vault

- `app/services/agent/scripted_inference.py`: a `ScriptedInferenceAdapter` that plays turns from
  a JSON file (`METALIST_SCRIPTED_AI=<file>`): each turn is text and tool calls, as
  `tests/unit/test_agent_loop.py`'s `_ScriptedModel` does. `ai_setup` selects it, and treats the
  provider as configured, **only in test mode**; outside test mode the variable is a startup
  error. Scripts can name the view's search word, so one script serves any vault.
- `scripts/generate_large_vault.py --notes N --data-dir D [--seed S]`: writes N notes straight
  into a fresh vault through `note_store` (the import path takes a minute per 100k notes; the
  store takes seconds), deterministic from the seed: a mix of short and long notes, trees three
  deep, folder tags, a few tables and diagrams, so search, scopes and rendering all have work.
  Also writes `D/../files/` with M Markdown files for the import flow.
- `npm run throwaway` gains `--notes N` (uses the generator instead of the 12 sample notes) and
  `--scripted-ai <file>`, so the reproduction done by hand on 2026-11-05 is one command.

Done 2026-11-06, with two changes found in the code: the browser suites and the throwaway
never run in `TEST_MODE` (that mode means `./test.db` and no diagnostics), so "test mode
only" became "only on a server with its own data folder" (`METALIST_DATA_DIRECTORY` set,
as every test server has; a server on the user's vault refuses to start with the variable).
And a script is literal (its search word is fixed); the generator puts "Harbor" at the start
of every tenth note and nowhere else, so one script serves every generated vault. First look
at 100,000 notes in Chrome: the scripted question was answered in 10 s with the list usable
meanwhile, but a 100 ms probe of the server waited 4.7 s once during the search: a stall
part 2's gate will report on its first run (the search scan itself, or the alias step, still
runs on the request loop at this size).

### 2. A blocked request loop fails any browser suite

- In test mode `EventLoopWatchdog` records every stall of 1 s or more (threshold from
  `_EVENT_LOOP_STALL_SECONDS`, test-mode value named beside it) with the active requests and
  the thread dump, and serves them at `/api2/diagnostics/stalls` (test mode only).
- `browser-smoke.mjs` reads that at the end of every run and fails the run on any stall. The
  runner prints the stall's requests and the top of its stack. This is the structural guarantee:
  no future code path can hold the server, whatever it is. The first run reports what today's
  suites trip; the threshold is tightened once they are clean.

### 3. The `scale` browser suite and its CI job

A focused suite that starts its server on a generated vault (100,000 notes; the number is a
named constant in the suite) with the scripted AI, in Chrome, and runs:

- **Import:** the wizard imports 1,200 generated Markdown files (the folder picker is answered
  from the test-mode variable `METALIST_TEST_PICK_FOLDER`, as the reproduction did). The import
  finishes, its search context opens, no fatal overlay at any time.
- **AI with an empty search box:** clear the search, ask a question; the script searches the
  whole view, reads notes, answers. One second in, type in the list's search box: the list
  updates within 3 s. Press Stop on a second question during its search: the Send button is
  back within 1 s and the list still answers. No fatal overlay; no stall (part 2).
- **The list itself:** scroll to the bottom, collapse and expand a tree, run a tag search and
  clear it; each within a budget. Budgets are generous with respect to the failures they catch
  (a freeze is 15 s against a normal 0.5 s), so a slow CI machine cannot fail a good build while
  a regression still cannot pass.

CI: a `scale` job in `browser-suites.yml`, its own matrix row rather than a slice (it runs
minutes, not seconds), on Linux and Windows (the reporter runs Windows), Chrome. Firefox and
macOS can follow as the harness doc's symmetry note asks. Its logs and stall reports are kept
as artifacts on failure.

### 4. Every CommandGate command declares its watchdog

`CommandGate.run(name, fn, options)` and `runWhenFree` require `options.watchdog`, one of:
`'quick'` (the 15 s default), `{seconds: N}` (a known bound: export, print, paste, backup), or
`'none'` (length grows with the user's data and the command shows its own progress: the
import, bulk proposals). A call without it throws, in the browser and in a unit test that reads
every call site (175 today: 164 `run`, 11 `runWhenFree`) so a missed site fails `npm test`, not
a user's click. The existing `timeoutMs` and `disableWatchdog` options go away.

The 175 sites are triaged in the change: every command that calls an endpoint iterating the
vault (delete notes in view, alphabetize, reset filters, trim files, tag proposals, exports,
imports, backups) gets `{seconds}` or `'none'` with its reason; the rest `'quick'`.

### 5. Typed tool payloads

Each note tool's result becomes a Pydantic model (`ViewOverviewResult`, `ReadViewNotesResult`,
`SearchViewNotesResult`, `OpenWebPagesResult`, ...) serialized by `ToolResult`; the action log
and the alias mapper read fields, not keys. A branch cannot drop a field: the model requires it
and `full_checks`' type check sees it at commit time. `NoteAliases` keeps working on the
serialized JSON.

### 6. The BUG workflow reproduces at the reporter's scale

AGENTS.md, BUG step 1 gains: before any fix, reproduce the report in a throwaway at the
reporter's scale and platform (`npm run throwaway -- --notes N --scripted-ai ...`; a report from
a Windows user is a Windows report), on the code they run; the fix is checked the same way.
`docs/testing/harness.md` gets a "Scale" section (the suite, the stall gate, the tools) and
`coverage-map.md` the new rows.

### 7. The release driver requires the browser suites green on the exact commit

`scripts/release.py` checks the `Publish to PyPI` run of the commit it tags. It gains the same
check for the `Browser suites` run of that commit: every job passed (the `scale` job among
them), or the driver refuses to tag, naming the red jobs. No rerun-for-green: a job that failed
stays a failure, as "Run the Full Release Matrix Once, on Main" says; a job GitHub never started
is rerun the way the driver already reruns such jobs. AGENTS.md's release gate names the browser
suites as a second required run. The two Firefox jobs red today are fixed first (their waits are
made as generous as the `scale` budgets, with a failing test for the shape they trip on), so the
gate starts green rather than being waived on its first day.

### ShockHarness proposals (to the ShockHarness project, not this repo)

- `if x not in <list>: <list>.append(x)` inside a loop: quadratic; `dict.fromkeys` keeps order.
- A loop with no `await` over an unbounded collection inside an `async def`.
- Returning the same kind of payload from several branches with different key sets.

## Order of work and checkpoints

1. Part 1 (tools) and part 2 (stall gate): checkpoint. The stall gate runs on every existing
   suite from here on, so its first full run on GitHub is informative on its own.
2. Part 3 (`scale` suite and job): checkpoint. First, run it against 0.26.0's code (436ccebf) in
   a copy: it must fail on all three freezes, or the budgets are too loose.
3. Part 4 (watchdog declarations): checkpoint.
4. Part 5 (typed payloads): checkpoint.
5. Part 7 (release driver gate, after the two Firefox jobs are green): checkpoint.
6. Part 6 (AGENTS.md and docs), then COMMIT FEATURE: `full_checks.py --no-browser`, the
   `scale`, `legacy-import`, `ai-chat-summary`, `ai-selected-note` and `agent-help` suites alone.

Estimate: all seven parts in one session. The writing is small; the time goes to runs (generating
the vault, the `scale` suite against 0.26.0 and against this branch, the existing suites once
with the stall gate on) and to the maintainer's looks between checkpoints.

## Acceptance checks

- `npm run throwaway -- --notes 100000 --scripted-ai tests/fixtures/scripted-ai/search-view.json`
  starts in under a minute and answers an AI question with the list usable meanwhile.
- The `scale` suite fails on 436ccebf (0.26.0) for the import, the AI question and Stop, and
  passes on this branch.
- A deliberate 2 s `time.sleep` in an async route fails every browser suite with the route named.
- A `CommandGate.run` call without `watchdog` fails `npm test` and throws in the browser.
- Removing a field from the empty-search branch fails the type check.
- Chrome and Firefox browser-suites workflow stays green with the stall gate on.
- `scripts/release.py` refuses to tag a commit whose `Browser suites` run has a failed job, and
  says which; a unit test with a recorded run proves it.

## Open questions

- Vault size for `scale`: 100,000 notes (about 2× the reporter's likely size) or 250,000?
- Should `scale` also gate the release (`publish-pypi.yml`), or stay a check in
  `browser-suites.yml` like the other suites?
- Stall threshold in test mode: start at 1 s, or at 500 ms and accept a noisier first run?
