# Commit and shutdown protocol: nothing shown as Saved is ever lost (decided)

**Status:** Agreed with the maintainer 2026-10-24, brought up to date 2026-10-31 for multi-view editing (`docs/ready-to-build/multi-view-editing.md`) and the phone that edits (`docs/ready-to-build/phone-same-app.md`). The client parts (§3) can be built now; the server's hosted parts (§2.2, §2.3, §4) go with the hosted deployment.

Written from a read-only look at the repo; filed 2026-10-31 after checking the references (§10, Found when filed).

---

## 0. The rule

**Acknowledge a write only after it is durably committed; never "flush on shutdown."** Every stop (deploy, Lock, dormancy, crash, out-of-memory kill, SIGKILL, loss of the whole host) is assumed to be a SIGKILL. A graceful stop is a courtesy that takes the final snapshot and makes the next start faster. It is never what keeps data safe.

An edit is in one of three places when a process stops:

| Where | Risk | Made safe by |
|---|---|---|
| In the client, not yet acknowledged | Tab closed or crashed, phone app killed, network down | Short autosave, save when hidden, retry until acknowledged, honest status (§3) |
| Received by the server, in memory only | Process stops before writing | Doesn't exist: acknowledge only after a durable commit (§2) |
| Written to disk | Host fails before the OS flushes | `synchronous=FULL` in hosted (§2.2), plus regular snapshots |

**The promise, in user words:** *"Anything MetaList shows as Saved survives updates, Lock and restarts. If something isn't saved yet, MetaList says so."* Don't claim more.

## 1. Today (from the code)

**Already right:**
- Every write route commits before it responds (`@transactional_route`, `app/api/transactions.py`; commit in `app/db/session.py`), and a startup check refuses a mutation route without it.
- A note save sends the whole note (`PUT /notes/{id}/save`), so repeating it gives the same content.
- Drawings autosave 2 s after drawing stops, one save at a time, with an honest status and a warning before closing the tab (`docs/ui/excalidraw.md`, "Saving and Closing").
- Anything modal saves and closes the note first (`docs/ui/interaction-principles.md`, principle 6).
- A transport failure shows "Not saved, reconnecting…" and disables editing (`docs/ui/state-handling.md`).
- Multi-view's Take Over already says the other view saves its typing and shows anything unsaved for copying.

**Gaps:**
1. **Notes autosave only after 60 s idle,** a value marked "for debugging" (`app/static/js/modules/mode-manager/events/inactivity-events.js:9`). **Changed to 10 s on 2026-10-31** (`CONTENT_INACTIVITY_THRESHOLD`), alone, as a trial: saves still run as before.
2. **Hiding or closing a tab doesn't save a note.** The mode manager's `visibilitychange` handler only logs (`mode-manager-controller.js`, `_handleVisibilityChange`); there is no `beforeunload` for notes.
3. **A save can mark text typed during the request as saved** (fixed 2026-10-31, see §10). `actionSaveNoteOnIdle` captures the content, awaits the server, then calls `ModeContext.setDirty(false)` unconditionally (`content-actions.js:123`; also line 70). Keystrokes typed while the request was in flight are marked clean without being sent. **Fix this first; it applies today, not only to hosted.**
4. **No retry, no change IDs.** A failed save stays dirty; nothing resends after a reconnect, leaving edit mode or a restart.
5. **Every save records an undo step** (`app/usecases/update_content.py:159`). At a 10-second autosave, one editing pass would still become many steps.
6. **Saves claim the session** (`claimSession` → `X-Metalist-Claim`, `api-client.js`). With multi-view's several sign-ins this should go entirely: saving never claims anything.
7. **`synchronous=NORMAL`** (`app/models/database.py:90`, `app/db/file_session.py`): safe against a process kill in WAL mode, not against an OS crash or host loss.
8. **The shutdown hook only stops shell runs** (`app/main.py`, `stop_shell_runs`). No draining state, no final snapshot.

## 2. Server

### 2.1 What "acknowledged" means
The server returns success only when:
- the transaction holding the write has committed, with the durability setting below;
- for files: the blob is written and fsynced before the catalog row, and the catalog row before the note's reference;
- the change ID (§3.3) is recorded **in the same transaction** as the change.

Keep today's structure: commit inside `@transactional_route`, then respond.

### 2.2 Durability in hosted
- **Hosted runs `PRAGMA synchronous=FULL`:** each commit waits for storage, so an acknowledged save survives losing the host. A few milliseconds per commit; a typing user saves every few seconds at most. Self-hosted and personal keep `NORMAL`.
- **WAL on network storage needs proving before launch.** SQLite's documentation says WAL doesn't work over a network filesystem (the `-shm` index assumes one host). One process per vault on one host might be fine; don't assume it. Candidate: `PRAGMA locking_mode=EXCLUSIVE` (WAL index in process memory). Decide after the host-loss test (§5).
- **Two processes never write one database.** On a deploy, a spare taking over or a failed start, the old process is fenced off before the new one opens the file (the hosted control plane's job; required here).

### 2.3 Draining
A process told to stop enters **draining**: new mutations get `503` with `{"restarting": true}` (the client keeps and resends them, §3.2); transactions already running finish and are acknowledged; reads keep working until exit.

## 3. Client: keep it until acknowledged

### 3.1 Autosave
- **10 s after typing stops** (`NOTE_AUTOSAVE_DELAY_MS`; decided 2026-10-31, replacing the 2 s first agreed), one save in flight per note, as drawings do. Replaces the 60-second idle save. Why 10: saving when the tab is hidden and the close warning already cover everyday ways of losing work; the delay only bounds what a crash, a dead battery or a killed phone app loses (a few sentences), while saving far less often than at every pause.
- **Save immediately when hidden:** `visibilitychange` to hidden and `pagehide`, with `fetch(..., {keepalive: true})`; the phone the same when it goes to the background.
- Escape, modals and Lock still save first.
- **"Dirty" clears only when the acknowledged text equals what's in the editor now** (gap 3).
- **One editing pass is one undo step,** however many autosaves it took: the server groups saves of one note from one edit session into one undo entry (gap 5). *Check* whether the undo stack already coalesces.

### 3.2 Pending writes and retry
- Every mutation waits in an in-memory **pending list**, in order, until acknowledged.
- On a network error, timeout or `503 restarting`: keep it, back off (`SAVE_RETRY_BACKOFF`: 1 s, 2 s, 5 s, then every 10 s), resend after reconnecting, oldest first, **same change ID**. A reconnect to a new process resends everything pending before any new edit.
- **Nothing pending is written to the device.** Closing a tab with something unacknowledged loses it, which is why the window is kept small and the status is honest (§3.5).

### 3.3 Change IDs: exactly once
- Every mutation carries a **`change_id`** (random UUID from the client) and, for edits to an existing note, the **`base_revision`** this view last had acknowledged.
- The server stores each applied `change_id` with its result, in the change's transaction. A repeat returns the stored result without applying again. Keep them `CHANGE_ID_RETENTION_DAYS` (7). They carry no content, so no encryption.
- They matter most for creates, pastes, moves, deletes and tag operations, where applying twice does damage. Full-content saves are nearly idempotent already.
- A save whose `base_revision` isn't current is refused with `409` and handled as in §3.4.

### 3.4 A view that lost its lock
With multi-view editing, a view loses the right to edit a root note when another view takes it over. Its later writes to that root, late retries included, are **refused**, never applied over newer work and never silently dropped: its unsent text is shown for copying, as Take Over already specifies. With a 10-second autosave and save-on-hide this is rare.

### 3.5 What the user sees
- A status while editing or while something is pending: `Saving…`, `Saved`, `Not saved, reconnecting…` (text kept on screen).
- **Closing or reloading with anything pending or dirty asks first** (`beforeunload`), as drawings do.
- After `Not saved` lasts `NOT_SAVED_WARN_SECONDS` (30), the status gets error emphasis.

## 4. The graceful stop (hosted)

One code path for every trigger: Lock, lock-on-close, lock after inactivity, dormancy, update restart, host drain.
1. Tell every view: `restarting` or `locking`. Views stop sending new edits, show "Updating…" / "Locking…", keep anything pending.
2. Drain (§2.3).
3. Persist the AI conversation if a turn just completed (normally already written after each turn).
4. **Final snapshot:** WAL checkpoint, `VACUUM INTO`, hand it to the uploader.
5. Zero key material (best effort) and exit.
6. On an update, views reconnect, resend their pending lists, and show what's new.

It must finish within `DRAIN_TIMEOUT_SECONDS`, below the container's stop timeout (SIGTERM, wait, then SIGKILL; *check* the platform's limits), sized for the largest vault's snapshot. **If killed first,** nothing acknowledged is lost; only the final snapshot is missing, so the next start takes one before serving (`SNAPSHOT_ON_START_IF_MISSED`). Lock while editing saves the note first, then stops.

## 5. Tests

- **Kill at random points** (SIGKILL) under scripted typing, saves, creates, moves and uploads. After restart: every acknowledged change present exactly once, nothing unacknowledged.
- **Duplicate delivery:** replay each request 1–3 times, in and out of order; state equals one delivery.
- **Host loss on the real hosted storage:** force-stop the machine mid-write (not just the process); every acknowledged change survives. This decides §2.2.
- **Takeover mid-save:** type in view A, take over from view B. B's work is never overwritten; A shows its unsent text.
- **Hidden-tab save:** type, then hide or close within 10 s; the save arrives, or the close was confirmed.
- **Typing during a save** (gap 3): the note stays dirty and the next autosave sends the rest.

## 6. Config values

| Name | Initial value |
|---|---|
| `NOTE_AUTOSAVE_DELAY_MS` | 10000 (decided 2026-10-31; first 2000) |
| `SAVE_RETRY_BACKOFF` | 1 s, 2 s, 5 s, then every 10 s |
| `NOT_SAVED_WARN_SECONDS` | 30 |
| `CHANGE_ID_RETENTION_DAYS` | 7 |
| `DRAIN_TIMEOUT_SECONDS` | below the container stop timeout; sized by measurement |
| `SNAPSHOT_ON_START_IF_MISSED` | on |
| SQLite `synchronous` | `FULL` hosted; `NORMAL` self-hosted and personal |

## 7. Invariants

1. A write is acknowledged only after a durable commit, with its change ID, in one transaction. Nothing depends on a flush at shutdown.
2. Every stop is survivable as a SIGKILL; the graceful stop adds a snapshot and a faster restart, never safety.
3. The client keeps every change until acknowledged and resends it with the same change ID; a change ID applies at most once.
4. "Saved" is shown only for acknowledged content; unsaved text is saved, retried, or shown as not saved, never silently dropped.
5. Nothing pending is stored on the device.
6. A view without the lock on a root can't write to it, and saving never claims a session or a lock.
7. Two server processes never write one database at the same time.
8. One editing pass is one undo step.

## 8. Left to you

- WAL on the hosted storage (§2.2), decided by the host-loss test.
- `DRAIN_TIMEOUT_SECONDS`, by measuring the largest vault's snapshot.
- Where change IDs live (their own table, or with the undo records).
- Offline editing on the phone is not part of launch; this protocol assumes a connection, with the pending list covering short drops.

## 9. Done when (client part, buildable now)

1. Notes autosave 10 s after typing stops and when the tab is hidden or closed; the 60-second idle save is gone.
2. Typing during a save is never marked saved (a test reproduces the race and passes).
3. A save that fails is retried with backoff and the same change ID, and survives a server restart; a repeated change ID applies once.
4. `Saving… / Saved / Not saved, reconnecting…` and the close warning behave as in §3.5.
5. One editing pass is one undo step.
6. Saves no longer send the session claim.
7. `docs/ui/state-handling.md` and `docs/ui/interaction-principles.md` describe the protocol.

## 10. Found when filed (2026-10-31)

Every code reference in §1 checked out: the 60-second idle save (`inactivity-events.js`, `CONTENT_INACTIVITY_THRESHOLD`), the logging-only `_handleVisibilityChange`, no `beforeunload` for notes (only drawings and two image services have one), `setDirty(false)` after the await (`content-actions.js`, lines 70 and 123), the undo step per save (`update_content.py`), `claimSession` (`api-client.js`), `synchronous=NORMAL` (`app/models/database.py:90`, `app/db/file_session.py`) and the shutdown hook that only stops shell runs (`app/main.py`, `stop_shell_runs`). One correction and what it means for §3.1:

- **Gap 3 is not live today.** Every save runs through `CommandGate.run` (the idle save as `autosave`), and while a command runs the keyboard and input handlers drop input (`keyboard-events.js` and `input-events.js` check `ModeContext.isLoading`; `docs/ui/command-gate.md`). So nothing can be typed during a save: no keystroke is wrongly marked saved. The code shape is still wrong, and the race becomes real as soon as typing is allowed during a save.
- **The 10-second autosave must not run through the CommandGate as it does today.** At the current 60 s a dropped keystroke is rare; at 10 s, a save would often start at a pause in writing and swallow the keys typed during its request, and the loading overlay could appear while typing (after `CONFIG.LOADING.SPINNER_DELAY`). The autosave has to let typing go on, which is what makes the gap 3 fix (clear "dirty" only when the acknowledged text equals the editor's) necessary.
- **Decided 2026-10-31: keep saves as they run today, for now.** Measured in a throwaway MetaList, a save takes 5–10 ms for short and medium notes and about 25 ms for a 600-line one, so a key pressed just as a save runs is very unlikely on a local MetaList. The delay went to 10 s alone (gap 1) as a trial; a letter lost on resuming typing after a pause is the sign to build the fix. **Revisit before the hosted launch,** where every save also crosses the network (a tenth of a second or more). The options then: (A) the autosave stays out of the CommandGate with its own one-save-in-flight rule, as drawings have, and every other command waits for it; (B, preferred 2026-10-31) the gate learns a background kind of command that keeps typing flowing, and a key or click during it waits instead of being dropped. Either needs the gap 3 fix. A user setting for the delay was considered and declined: it hands users a trade they can't see, and the default decides for nearly everyone anyway. **Built 2026-10-31 instead of A or B, for keys:** letters typed during an autosave are kept and typed in after it (`type-ahead-service.js`, the piece that keeps letters typed while a clicked note opens); Backspace, Enter, arrows and shortcuts are still dropped, so A or B is still the answer for those on the hosted launch.
- **Found 2026-10-31 (`docs/BUGS.md`):** text that arrives without a key press while a command runs (dictation, autocorrect, the emoji picker, a writing assistant) lands in the note, but the input handler ignores it as "busy" (`input-events.js`, `handleInput`: `preventDefault` on an `input` event does nothing, since it can't be cancelled), so it isn't marked dirty and the autosave skips it. Leaving the note still saves it (`reconcileContentBeforeSave` compares the editor with the last content it recorded). So the close warning and the save when hidden (§3.1, §3.5) must make the same comparison, not trust the dirty flag. **Fixed 2026-10-31:** after each save the editor is compared with what was sent, and the note stays changed if it holds more (`editorHoldsUnsentText`, `content-actions.js`); this is gap 3's fix for both save paths.

Linked from `docs/ui/state-handling.md` and `docs/README.md`. Model checking this protocol is a future plan: `docs/future-plans/model-checking-protocols.md`.
