# Errors and status: never rearrange the layout (modals vs. floating indicators)

**Status:** Agreed with the maintainer 2026-10-24. Being built on `feature/dialog-conventions`: the floating messages (§2.2, placements 1 and 2, with Recent Messages) are built and documented in `docs/ui/floating-messages.md`; the error dialogs, the field messages and the escalation (step 5) and the checks (step 6) are not. Filed here from `docs/inbox/` on 2026-10-24. Build it together with `docs/ready-to-build/dialog-and-menu-conventions.md`, which it extends, and document both in the same place.
**Scope:** How every error and status message is shown: one rule, the two kinds of message, the three places a floating message may appear, and the existing dialogs that need converting.

Written from a read of the repo on 2026-10-24. Check every reference before relying on it; build only what is missing.

---

## 1. The rule

**Nothing that reports an error or a status may change the layout.**
- No message is inserted into a dialog or page, pushes buttons or content down, or appears where the user might not be looking.
- Every error or status is shown **above** the layout, in one of the two forms below.

**Why** (it follows from `docs/ui/interaction-principles.md`):
- **Principle 1:** keep the point of attention still. An inserted message moves things under it.
- **Principle 2:** only the user's action changes the screen.
- **Principle 3:** never lose sight of what was just acted on. An error below the fold is out of sight.
- **Principle 5:** errors may be emphasized.

**The maintainer's complaints about today's behavior:**
- Inline errors shift the layout.
- They often land low enough to miss. Example: "Google API key must start with AIza" in AI Agent Settings, which pushes Save/Cancel down.

## 2. Two kinds, told apart by who ends them

| | **Modal** | **Floating indicator** |
|---|---|---|
| What it is | Pauses the flow on purpose and waits for the user | Reflects a condition, live, above the layout; the user never acts on it |
| Who ends it | **The user:** a decision button, or, for "make sure you saw this," just `×`, Escape or a click outside | **The condition:** it changes or disappears when what it describes changes, or after a few seconds for one-off news |
| Use it for | A decision (Delete Vault / Cancel). An action the user just took that **didn't happen** (Save rejected). Something the user must know before continuing. | Temporary news ("Saved," "Copied," "Update installed"). Ongoing conditions ("Not saved, reconnecting…," "Offline, read-only," "Locked"). Feedback on what's being typed ("Passwords don't match," "Tags can't contain spaces"). |

### 2.1 Modals for errors

- **The dialog underneath stays open** with everything the user entered. The error modal stacks on top (use the existing modal stack in `docs/ui/modals.md`).
- **The message says what happened and how to fix it,** with no apology and no jargon. For example: "That isn't a Google API key. Google keys start with AIza."
- **One modal lists every problem**, never a cascade of modals.
- **When it closes, focus returns to the field at fault.** That field keeps a red outline **drawn without changing any sizes** (for example an outline or box-shadow, not a thicker border) until its value changes.
- **Buttons: no meaningless buttons.** This replaces the "dismiss-only Close/OK buttons are not used" line in `docs/ui/modals.md`.
  - An acknowledgement-only modal has **no button**: `×`, Escape and a click outside close it.
  - If the user can do something about it, the one button names that action ("Fix Key," "Try Again"), following the button order and labels in `dialog-and-menu-conventions.md`.
- **Accessibility:** `role="alertdialog"`, focus moved into it, announced by screen readers.

### 2.2 Floating indicators: three placements

1. **Upper-right corner, temporary.**
   - One-off news that disappears by itself after a few seconds; hovering pauses the timer.
   - Several stack in the corner without moving anything else.
   - A **"Recent Messages"** command in the command palette lists the last few (in memory only), so nothing missed is lost.
2. **Upper-right corner, lasting while the condition does.**
   - Examples: "Not saved, reconnecting…" (from the commit/shutdown protocol's save states), "Offline, read-only," "Locked."
   - It stays exactly as long as the condition holds and updates live.
   - If a condition puts the user's work at risk and doesn't resolve within `STATUS_ESCALATE_SECONDS` (initially 30), it **escalates to a modal**.
3. **Anchored just under a field, while typing.**
   - It reflects the field's current value and disappears when the value becomes valid.
   - It never steals focus, never covers the field being typed into, and never moves anything.
   - **Typing never opens a modal.** Validation that needs a modal waits until the user presses the action button.

**No permanent status area.** Nothing reserves screen space for status; a floating indicator is visible exactly while it's relevant.

### 2.3 Not affected

- **AI chat messages** in the conversation ("not sent because…," "Ask again") stay there, as described in `docs/ui/ai-chat.md`. They're the conversation's own content, and adding a message doesn't shift other UI.
- **View indicators:** chips inside the search field for sort mode, date range, or "Notes with files" show view state the user chose. They aren't status.

## 3. Existing code to convert (found 2026-10-24)

A class scan found inline error or banner elements in these files under `app/static/js/modules/`. Check each; some may be view indicators or harmless hints.
- `modals/namespace-modals.js` (5)
- `error-handler.js` (4)
- `modals/delete-namespace-modal.js` (3)
- `modals/backup-restore-modal.js` (2)
- one each in:
  - `modals/ai-agent-settings-modal.js` (the "Google API key must start with AIza" case)
  - `modals/backup-settings-modal.js`
  - `modals/note-layout-appearance-modal.js`
  - `modals/password-modal.js`
  - `modals/prioritize-modal.js`
  - `modals/random-password-modal.js`
  - `modals/reminder-modal.js`
  - `modals/search-suggestion-statistics-modal.js`
  - `modals/session-timeout-modal.js`
  - `modals/version-info-modal.js`

Also `app/templates/index.html`, the login screen's error line: check it against `docs/ui/login-screen.md`. Login has its own established look, so propose before changing it.

Also review:
- **The sorted-view "blocked action" banner** (`docs/ui/controls.md`: "a blocked action does nothing and shows a banner saying why"). Proposed: a temporary floating indicator.
- **The Excalidraw editor's save bar** ("Unsaved changes / Saving… / Could not save. Retrying…", `docs/ui/excalidraw.md`). Proposed: a floating indicator lasting while the condition holds, escalating as in §2.2.

## 4. Make it stick

1. **Document it** in the same "Dialog and menu conventions" section `dialog-and-menu-conventions.md` asks for (in `docs/ui/modals.md` or a sibling doc), with the reasons above. Link it from `docs/ui/interaction-principles.md`.
2. **One shared component** for each kind: an error modal helper and a floating-indicator service (temporary, lasting while the condition holds, anchored to a field). Then no dialog builds its own error element.
3. **A check** (test or ShockHarness rule) that fails when a dialog inserts error or status elements into its own layout instead of using the shared components.

## 5. Done when

- Every item in §3 is converted or explicitly ruled out, with a reason.
- The two shared components exist, and the conventions are documented with their reasons.
- The check runs in CI and fails on a deliberately wrong fixture.
- Browser smoke and the existing modal tests pass.

## Found when filed (2026-10-24)

- Every file in §3 exists. `docs/ui/modals.md:137` is the "dismiss-only `Close`/`OK`" line §2.1 replaces; `docs/ui/controls.md:90` is the sorted-view banner; `docs/ui/excalidraw.md:32` is the save bar.
- **Conflict, uncommitted on `feature/ai-providers`:** the Google `AQ.` key change (2026-10-24) moved AI Agent Settings' key errors ("must start with AIza or AQ.", "Paste your … key first") into a new inline line under the key row (`.ai-settings-key-error`, `ai-agent-settings-modal.js:117`). That follows today's inline pattern and is exactly what §1 forbids. The dialog's other inline line (`.error-message`, above Save) is still there too. **Decided 2026-10-24:** keep the inline line until this rule is built; it is converted with the other dialogs in §3.
- Already in line with the rule: the user's standing preference that progress and outcome messages float instead of being written into the layout.

## 6. Questions for the maintainer

1. How long temporary indicators stay up (proposed: about 4 seconds, longer for longer messages).
2. `STATUS_ESCALATE_SECONDS`: 30 proposed.
3. The login screen's error line: convert it, or keep it as the established login design?
