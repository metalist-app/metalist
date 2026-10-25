# Modal Architecture Pattern

## Overview

This document defines the standard pattern for implementing modal dialogs in the application. All modals must follow this architecture for consistency and maintainability.

## Design Principles

### 0. **One Dark Visual System**
- Every application modal uses the shared dark shell in `app/static/css/main.css`, independent of the page's light/dark preference.
- Shared tokens on `.modal` define the surface, inset surface, borders, text hierarchy, accent, success, and danger colors.
- `.modal-content` owns the standard panel, shadow, radius, padding, scrolling, headings, controls, buttons, and close control. Feature-specific modal CSS should define layout and width only where possible.
- Dense information uses cards, tables, and split panes only when they improve scanning. Do not repeat a value in a large summary card beside the control that already displays it.
- Default action rows are right-aligned on desktop and stack to full width on narrow screens.
- The command palette retains its specialized layout while using the shared surface language. The ontology editor and its sub-dialogs keep their established standalone styling and are excluded from shared modal overrides.
- Within the ontology exception, tag suggestions stay attached to the search input. The focused-tag edit dialog exposes confirmed whole-tag deletion, while **Add new tag…** avoids redundant description and label text.

### 1. **Centralized State Management**
- **ALL modal state lives in ModeContext** - no exceptions
- Modal-specific state stored in `ModeContext.modalState = {modalName: {...}}`
- Modal lifecycle managed via `ModeContext.modalStack = []` (empty = no modals open)

### 2. **Clean State Enforcement**
- **Notes must be closed** (exit editing mode) before opening any modal
- **BaseModal throws error** if opening when application is in active state:
  - `ModeContext.currentNoteId` exists (editing state)
  - In searching state  
  - Any other "active" state that should be closed first
- Caller responsible for cleaning state before attempting to open modal
- Always, for every modal, with no exceptions: the user's mental model is "a modal saves and closes what I was editing" (interaction principle 6). Closing or cancelling the modal does not resume editing; one more click does.
- When a caller exits note editing, it must complete the normal save/deselect/view-refresh flow before opening the modal. This restores view-only rendering such as cached URL titles instead of leaving the editor HTML visible behind the modal.

### 3. **Event Handling Integration**
- Follow existing pattern in `keyboard-events.js` (like Esc key handler)
- Keyboard events still fire but check modal state and defer appropriately
- Operations like Cmd+Enter (new note) require modal to be closed first
- Modal has precedence - if modal open, modal-specific logic handles events

## File Organization

```
app/static/js/modules/modals/
├── base-modal.js       # BaseModal class with state enforcement
└── password-modal.js   # Password management modal
└── note-layout-appearance-modal.js # Namespace-scoped note layout presets + preview
└── [future-modal].js   # Other modals follow same pattern
```

## Implementation Pattern

### BaseModal Class

All modals extend BaseModal which provides:

1. **State Validation**
   - Throws error if opening with dirty application state
   - Enforces clean state requirement

2. **ModeContext Integration**  
   - Updates `ModeContext.modalStack` on open/close
   - Sets modal-specific state in `ModeContext.modalState`

3. **Common Event Handling**
   - Every modal shows the same upper-right circular `×` close control as full-screen note view
   - `Escape` closes every modal
   - Clicking outside the modal content closes every modal
   - `Enter` activates the modal's single declared primary action; modals with multi-step or input-specific behavior implement the equivalent explicitly
   - Focus management

4. **Shared Visual Contract**
   - Render the top-level panel with `.modal-content`; add a feature class only for specialized width/layout.
   - Use `.form-group`, `.form-actions`, `.primary-btn`, `.secondary-btn`, and `.danger-btn` instead of redefining controls.
   - Use the shared muted text, inset panel, warning, table, and status patterns before adding feature-specific colors.
   - Keep the main content within the shared viewport-aware max height; only large workspaces such as reminders or ontology should declare a fixed working height.

### Modal Opening Flow

1. User triggers a modal from the command palette or another UI control.
2. Handler checks current application state
3. If editing/searching → save + deselect + refresh the note view and/or exit search first
4. Attempt `new ModalClass().open()`
5. BaseModal enforces clean state (throws error if dirty)
6. Modal opens and updates `ModeContext.modalStack`
7. Modal-specific initialization runs

### Modal State Management

```javascript
// Example modal state structure
ModeContext.modalState = {
  passwordModal: {
    mode: 'create', // 'create' | 'change' | 'remove'
    currentStep: 1,
    formData: {...},
    isProcessing: false
  }
};

// Modal stack for stacking support
ModeContext.modalStack = ['passwordModal']; // Active modals in order
```

### Keyboard Event Integration

```javascript
// In keyboard-events.js
function handleKeyDown(event) {
  // Check if modal is open
  if (ModeContext.modalStack.length > 0) {
    const activeModal = ModeContext.modalStack[ModeContext.modalStack.length - 1];
    // Defer to modal-specific event handling
    return deferToModal(activeModal, event);
  }
  
  // Normal application event handling
  // ...
}
```

## Modal Lifecycle

### Opening a Modal
1. Validate clean application state
2. Add to modal stack
3. Set modal-specific state
4. Show modal UI
5. Set up modal-specific event listeners

### Closing a Modal  
1. The user clicks the upper-right `×`, presses `Escape`, or clicks outside the modal content
2. Clean up modal-specific event listeners
3. Remove modal-specific state
4. Remove from modal stack
5. Hide modal UI
6. Return focus to application

## Dialog and menu conventions
One set of rules for every dialog's buttons and for menus (agreed 2026-10-23, built 2026-10-24/25). People learn where "Save" is; an inconsistent order makes them read every dialog or press the wrong button. Code: `modals/action-row.js` (`actionRowHtml`, the one source of every dialog's row), `BaseModal` (Enter and first focus); tests: `scripts/browser-dialog-key-regressions.mjs`, `scripts/browser-dialog-button-regressions.mjs`, `tests/unit/dialog_labels.test.mjs`, `menu_conventions.test.mjs`, `command_palette_conventions.test.mjs`, and the check below.

1. **Order: the main action is rightmost.** Cancel is just left of it; a rare alternative ("Clear Form", "Open in New Tab") goes at the far left, apart. Reading ends at the lower right; right means forward (Next is right, Back left, in every flow); and it matches macOS, iOS and Android.
   ```
                                      [ Cancel ]  [ Save ]
   [ Open in New Tab ]                [ Cancel ]  [ Open in This Tab ]
   [ Back ]                                       [ Next ]
                                      [ Cancel ]  [ Delete Vault ]   ← red
   ```
2. **Labels say what happens:** verbs naming the result ("Save", "Add Key", "Delete Vault", "Rename and Restart"), never "OK", "Yes", "Submit" or "Confirm". Cancel is "Cancel", Back is "Back". A label that depends on a choice follows it.
3. **Title Case** for every button and menu item (the macOS convention).
4. **Keys and focus.** Enter presses the main action; on a focused button it presses that button, so Enter on Cancel cancels. Escape and `×` cancel. First focus goes to the first field needing input; tab order follows the row, left to right.
5. **Destructive actions** sit in the same rightmost place, in red; moving them around to be "safe" breaks the habit everywhere else. **Enter never presses one:** such a dialog opens with focus on Cancel (or in the field the user must type in), and Enter beside a red button does only what the dialog allows (picking a suggestion). Irreversible whole-vault actions keep two steps or type-to-confirm; undoable actions get no confirmation.
6. **Multi-step flows:** Back left, Next or the last step's verb right; Cancel or `×` leaves from any step.
7. **Narrow screens:** a stacked row puts the main action on top, then Cancel, then any alternative.
8. **Menus** (right-click menus, the app menu, the palette): `…` means a dialog asks for more first, no `…` acts at once; separators group related items, most-used first, and a menu never opens with a separator above its first item; destructive items go last, in red; shortcuts show on the right; the current choice is ticked, not greyed, and picking it changes nothing; items that cannot apply are hidden. Related actions sit in submenus so a menu fits the window (`docs/ui/controls.md`).

## Errors and status
**Nothing that reports an error or a status changes the layout** (agreed 2026-10-24, built 2026-10-25). Every error or status shows above the layout, in one of two forms below. Why (`docs/ui/interaction-principles.md`): an inserted message moves things under the point of attention (principle 1); only the user's action changes the screen (2); an error below the fold is out of sight (3); errors may be emphasized (5). The complaint that started it: inline errors shifted dialogs and landed low enough to miss ("Google API key must start with AIza" pushed Save/Cancel down).

### 1. Two kinds, told apart by who ends them
- **A dialog** pauses on purpose and waits for the user, who ends it: a decision, an action the user just took that **didn't happen**, something to know before going on. See "Errors" below.
- **A floating indicator** reflects a condition, live, and the condition ends it: one-off news, a lasting condition, feedback on what is being typed. Corner cards: `docs/ui/floating-messages.md`; under a field: "Messages under a field" below.
- **No permanent status area:** nothing reserves space for status; an indicator shows exactly while it is relevant.

### 2. Not affected
- **AI chat content** ("not sent because…", the chat's confirmation card, its tagging and summary operations) stays in the conversation, as `docs/ui/ai-chat.md` describes: adding to the conversation shifts no other UI.
- **View indicators** (sort, date range and "Notes with Files" chips in the search field) show state the user chose; they are not status.
- **The login screen's error line** keeps the established login design (decided 2026-10-25).
- **Content that is the dialog's purpose** stays: loading placeholders, the password's "Encrypting notes…" view, the link-title retry progress, Version Info's update section, the strength meters.

No button only dismisses: an acknowledgement has none (`×`, Escape or a click outside closes it), and a button names what it does. Workflow actions such as `Save`, `Cancel`, `Back`, and destructive confirmations remain visible when they carry meaning beyond dismissing the modal.

### Errors
An action the user took that did not happen (refused input, a failed request) is told in an error dialog over the dialog they were in, never written into that dialog's layout (built 2026-10-25). Code: `modals/error-dialog.js` (`showErrorDialog(problems)`, `showErrorDialogFor(error, fieldId)`); test: `scripts/browser-error-dialog-regressions.mjs` (`error-dialogs` suite).
- The dialog underneath stays open with what was typed; nothing in it moves.
- One error dialog lists every problem (`[{ text, fieldId }]`); a dialog's checks collect them all before refusing.
- It has no button: `×`, Escape or a click outside closes it, and only it. Keys and focus stay in it while it shows.
- Closing it focuses the first field at fault; each field at fault keeps a red outline (`.field-at-fault`, drawn outside the field, so no size changes) until its value changes.
- A refusal about one field throws `FieldInputRejected(message, fieldId)` (`expected-errors.js`), which `failureFieldId` reads.
- A dialog that fails to load (its list or settings cannot be read, or Add Password in a vault that has one) shows the error, and closing it closes both (`showOpenFailure`). Opening is not held up while the error shows: the AI's menu request reports the error's text as the reason the dialog did not open (`agent-menu-actions.js`).
- `role="alertdialog"`: screen readers announce it.
- Messages say what happened and how to fix it, for the user ("That vault already exists. Pick another name.").
- Failures while typing (a tag lookup) never open a dialog: they float in the corner (`docs/ui/floating-messages.md`).

### Messages under a field
What is wrong with a field's value while it is typed floats just under that field (built 2026-10-25). Code: `modals/field-message.js` (`setFieldMessage(field, text, kind)`, `''` removes it); test: `scripts/browser-field-message-regressions.mjs` (`field-messages` suite).
- It floats over what is below, lined up with the field and 4 px under it; nothing moves, focus stays in the field, and it never covers the field. It leaves once the value is fine.
- Errors are red, warnings (`kind: 'warning'`) amber. It is placed in the field's nearest container that draws a box, so it scrolls with the field.
- Typing never opens a dialog; a dialog that needs one waits for its action button.
- Passwords (Add/Change): "Passwords do not match." under Confirm once the confirmation stops being the start of the new password. A missing or short entry says nothing under its field (the length meter shows it); the dimmed button's tooltip says what is missing (Remove Password too).
- Search suggestion windows: a bad day count under its slot's field ("A slot must be between 1 and N days.", "Another slot already covers N days."); it is not saved until fixed.
- Reminders: a past date or time, and "Months without the Nth use that month's last day.", in amber under the date (the time when the date is hidden).
- Export and Print: "The AI couldn't suggest a title: …" under the title, until the next key or click.

### The check
`tests/unit/dialog_conventions_check.test.mjs` (the JS unit suite, so CI runs it on every OS) fails when a file writes a dialog button row by hand (`form-actions` / `dialog-actions` outside `modals/action-row.js`) or an error line into a dialog (`error-message`, `role="alert"`, `data-error`, a class ending in `-error`). Each failure names the file and line and what to use instead. Its exceptions name a file, a kind, an exact count and a reason (tool buttons such as Memory Usage's Copy and Refresh; AI chat content, such as the chat's tagging and summary operations), so a new line of that kind there fails too. It also fails on a deliberately wrong sample. A row with Cancel alone (a dialog still loading, or one that can only stop what runs) is `actionRowHtml({ ..., main: null })`.

### Modal Stacking
- Modals can stack via `ModeContext.modalStack`
- Top modal receives events
- Closing top modal reveals previous modal
- The error dialog is the one modal that opens over another (BaseModal dialogs refuse to open while one is open)

## Example Implementation

### BaseModal Class Structure
```javascript
class BaseModal {
  constructor(modalName) {
    this.modalName = modalName;
  }
  
  open() {
    this.validateCleanState();
    this.addToModalStack();
    this.setupModalState();
    this.showModal();
    this.setupEventListeners();
  }
  
  close() {
    this.cleanupEventListeners();
    this.hideModal();
    this.removeModalState();
    this.removeFromModalStack();
  }
  
  validateCleanState() {
    if (ModeContext.currentNoteId) {
      throw new Error('Cannot open modal while editing note');
    }
    if (ModeContext.isSearching) {
      throw new Error('Cannot open modal while in search mode');
    }
    // Add other state validations
  }
}
```

### Keyboard Shortcut Handler
```javascript
// In keyboard-events.js
if (event.metaKey && event.key === 'p') {
  event.preventDefault();
  
  // Clean state first
  if (ModeContext.currentNoteId) {
    await exitEditingMode();
  }
  
  // Open one explicit password operation; the command palette exposes all three.
  const addPasswordModal = new AddPasswordModal();
  addPasswordModal.open();
}
```

Password management uses three distinct modal flows from
`app/static/js/modules/modals/password-modal.js`:

- **Add Password**: passwordless namespace → encrypted namespace. Shows local zxcvbn strength feedback.
- **Change Password**: current password → new password. Shows local zxcvbn strength feedback. With no password set, the menu's Change password opens Add Password instead (`CommandPalette.openChangePassword`).
- **Remove Password**: encrypted namespace → passwordless namespace. Requires an explicit plaintext-storage acknowledgement.

Each modal checks `/api2/auth/status` before rendering and rejects an operation
that does not match the namespace's current password state.

## Benefits of This Architecture

1. **Consistency** - All modals follow same pattern
2. **State Safety** - Clean state enforcement prevents conflicts
3. **Integration** - Works seamlessly with existing ModeContext system
4. **Scalability** - Easy to add new modals following same pattern
5. **Maintainability** - Clear separation of concerns
6. **Debuggability** - All state centralized and inspectable

## Future Considerations

- Modal animations/transitions
- Modal size variants (small, medium, large)
- Modal positioning (center, top, custom)
- Nested modal content (tabs within modals)
- Modal templates for common patterns

All future enhancements must maintain compatibility with this base architecture.
