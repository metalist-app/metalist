# Command Gate (Client Busy/Loading Model)

## Goal
Prevent UI lockups and request interleaving by centralizing “busy” handling.

## Core Rule
All **user-initiated server-bound actions** should run through `CommandGate.run(name, asyncFn)`.

Exception:
- Live `@shell` sessions do not use `CommandGate` because the shell runner must keep accepting input and polling output while the rest of the UI remains usable.

`CommandGate` responsibilities:
- Set/clear `ModeContext.isLoading` (the only place allowed to call `ModeContext.setLoading(...)`).
- Drop inputs while busy (no queueing/coalescing/replay).
- Maintain a watchdog timer that throws if a command never finishes (15 s by default).

Long commands pass options to `run`: `{ timeoutMs }` when they have a known bound (export, print, paste and drop, backup), `{ disableWatchdog: true }` when their length grows with the user's data and they show their own progress (the import wizard's import, bulk AI proposals). A whole folder import passed 15 s in 0.26.0 and the watchdog called it stuck while it ran on.

The loading state immediately blocks overlapping input, but the visible full-screen loading overlay is delayed by `CONFIG.LOADING.SPINNER_DELAY` so fast commands do not flash a pause indicator.

## Why
- Keyboard/mouse handlers globally ignore input when `ModeContext.isLoading` is true.
- Before `CommandGate`, multiple async paths flipped `isLoading` manually; any missed `setLoading(false)` could hard-freeze the UI.
- Background loops (polling/infinite-scroll/tab-state) can interleave with user commands unless explicitly blocked.

## Implementation
- `CommandGate`: `app/static/js/modules/mode-manager/services/command-gate-service.js`

## Turns

Built 2026-11-22 (`docs/future-plans/one-writer-refactoring.md`, idea 4, its first step). One thing at a time changes the notes and the tabs shown: a command, a piece of background work, or something the server sent each take a turn, and turns run in the order they were asked for (`turns.js`, which knows nothing of the page and is unit-tested as it is: `tests/unit/turns.test.mjs`, with a run of 200 random orderings).

Before, only commands took turns among themselves. Background work looked whether a command ran when it started, then ran beside whatever started after it, and the two agreed through a flag read every few milliseconds, so which went next was the order of timers. A list refresh that woke after a tab change asked for the tab shown before: "notes.view response for tab A arrived after the active tab changed to B" (GitHub's `reference-views` in Firefox, 2026-11-22).

- **A command** (`CommandGate.run`) takes a turn. With background work in progress its work starts when that has finished; the gate is busy from the call on, so input meanwhile is dropped as during the command.
- **Background work that may be skipped** asks `CommandGate.isTurnTaken()` and skips its round when one is, then runs through `CommandGate.runBackground(name, work)` in the same task: the infinite scroll moving its band, a change made in another view (`liveChanges.apply`), the list refresh for link titles that arrived, the scroll saver, and the floating windows' refresh. `runBackground` throws when a turn is taken: asking first is the caller's part.
- **Background work that must not be skipped** goes through `CommandGate.queueBackground(name, work)` and runs when its turn comes: a reference page the server closed.
- **Every list refresh runs in a turn.** `actionRefreshAndMaybeSelect` asked for with no turn taken takes one of its own (`queueBackground`), and the gate notes what asked (`CommandGate.refreshesOutsideTurns()`).
- A turn's work must not await a turn it asks for itself: that one waits for this one. A command stuck that way is named by the watchdog.
- No turn: the once-a-second status check. It only reads, and hands what it finds to `liveChanges.apply`.

**View changes are commands, whoever asks** (built 2026-11-22, cases 1 to 5 agreed with the maintainer; `BROWSER_TEST_SUITE=view-commands`). A sort order, the Untagged view, a date range and a file or link filter (`CommandPalette.setSortMode`, `setIsUntaggedView`, `setDateFilter`, `setFileFilter`) go through `CommandGate.asCommand`: called from inside a command they are part of it; called with the gate free they become one. Before, the command palette's entries and the × of the sort and Untagged chips ran them beside whatever else was running.

1. The × of the sort chip or the Untagged chip, while background work has the turn: the change waits for it, then is made.
2. A view entry chosen in the palette while background work has the turn: the same.
3. A palette entry chosen while another command runs (an autosave, a search started by a timer): it waits for that command, then runs (`CommandGate.whenFree()` before the entry). The one place where a choice waits and is not dropped: it was typed and chosen on purpose.
4. The × clicked twice quickly: the second click is dropped, and the server is asked once. The two × are commands at their click, as the date and file chips' × were.
5. Everything else is as before: a click during a command is ignored.

`asCommand` takes "a command is running" to mean "this was called by it". That holds because nothing else starts one meanwhile: input is dropped during a command, background work waits its turn, and the palette waits for the gate.

Commands already, before this: the fold arrow, deleting a note, the right-click menus' view entries, the phone sheet, a tab click. Still outside the gate: palette entries other than the view's that do not take it themselves (not traced one by one), and suites that call internal functions directly, which is where most entries of `refreshesOutsideTurns()` come from.

What a slow server now means: a command asked for while background work waits on the server waits with it, where before it ran beside it. On the same computer that is milliseconds.

## Background Traffic Policy
Background loops must not generate traffic while a user command is in-flight, and what they change takes a turn (above).
Pattern:
- Add `if (CommandGate.isTurnTaken()) return;` at the top of the poller, then do the work in `CommandGate.runBackground(...)`. A poller that changes nothing on the page (a status check) asks `CommandGate.isBusy()` as before.

## Adding a New User Action
1. Wrap the action:
   - `void CommandGate.run('some.action', async () => { ... })`
2. Do not call `ModeContext.setLoading(true/false)` directly.
3. If you need refresh, call `actionRefreshAndMaybeSelect(...)` inside the gate.

For a live `@shell`-style interaction:
- Manage a dedicated per-widget running state instead of `ModeContext.isLoading`.
- Poll only that widget's session endpoint and keep the rest of the UI interactive.
