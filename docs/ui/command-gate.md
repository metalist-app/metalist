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

## Background Traffic Policy
Background loops must not generate traffic while a user command is in-flight.
Pattern:
- Add `if (CommandGate.isBusy()) return;` at the top of the poller.

## Adding a New User Action
1. Wrap the action:
   - `void CommandGate.run('some.action', async () => { ... })`
2. Do not call `ModeContext.setLoading(true/false)` directly.
3. If you need refresh, call `actionRefreshAndMaybeSelect(...)` inside the gate.

For a live `@shell`-style interaction:
- Manage a dedicated per-widget running state instead of `ModeContext.isLoading`.
- Poll only that widget's session endpoint and keep the rest of the UI interactive.
