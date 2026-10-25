# Dialog and menu conventions

**Status:** Agreed with the maintainer 2026-10-23. Being built on `feature/dialog-conventions`: Enter and focus, button order and labels, and the menus are built; the error dialogs (step 5) and the checks (step 6) are not. Filed here from `docs/inbox/2026-10-23-dialog-conventions-and-new-mark.md` on 2026-10-24 (its part B, the new mark, was built 2026-10-24: `brand/README.md`). Build it in the same pass as `docs/ready-to-build/errors-and-status-rule.md`, which extends it, and document both in the same place.
**Scope:** One set of conventions for every dialog's buttons and for menus, every existing dialog and menu brought in line with them, and a check so new ones can't drift.

Written from a read of the repo on 2026-10-23. Check every reference before relying on it; build only what is missing.

---

## A. Dialog and menu conventions

### A1. Why

`docs/ui/modals.md` already standardizes the surface, the button classes (`.primary-btn`, `.secondary-btn`, `.danger-btn`), right-aligned action rows that stack on narrow screens, the `×` close, Escape to close, and Enter for the single declared primary action. It doesn't say **which side the main button goes on**, and the dialogs disagree:
- 8 multi-button rows put Cancel first, with the action on the right.
- 11 put the action first, on the left.
- 3 put a red destructive button first.

People learn where "Save" is; an inconsistent order makes them read every dialog or click the wrong button.

### A2. The rules

**1. Order: the main action is rightmost.**

```
                                   [ Cancel ]  [ Save ]
[ Clear Form ]                     [ Cancel ]  [ Save ]           ← rare alternative, far left
[ Back ]                                       [ Next ]           ← multi-step flows
                                   [ Cancel ]  [ Delete Vault ]   ← red
```

- The main action (`.primary-btn`, or `.danger-btn` when destructive) is the **rightmost** button.
- **Cancel** is immediately to its left.
- A rare **alternative** ("Clear Form", "Open in New Tab", "Don't Save") goes at the **far left**, separated by space, never next to the main action.

Why:
- **Reading ends at the lower right.** It's the natural place for "done, go."
- **Right means forward.** Next is right and Back is left in every step-by-step flow. Putting the main action in the forward spot keeps one mental model across single dialogs and flows.
- **It matches the platforms.** macOS and iOS put the default button rightmost with Cancel to its left, and Android/Material puts the confirming action on the right.

**2. Labels say what happens.** Buttons are verbs naming the result: "Save", "Add Key", "Delete Vault", "Rename and Restart". Never "OK", "Yes", "Submit" or "Confirm". Cancel is always "Cancel"; Back is always "Back". A label that depends on a choice updates with it ("Delete 3 Notes").

**3. Capitalization.** One style for all buttons and menu items. Proposed: **Title Case** (the macOS convention, and most current labels: "Create and Open Vault", "Save Ports"), which means converting the sentence-case ones ("Clear form", "Delete vault"). **Ask the maintainer to confirm before converting labels.**

**4. Keys and focus.**
- **Enter** triggers the main action; **Escape** and `×` cancel (as today).
- **Initial focus** goes to the first field needing input; in a dialog with no input, focus goes to the main action, except destructive dialogs (rule 5).
- **Tab order** follows the visual order, left to right: alternative → Cancel → main action.

**5. Destructive actions.**
- The red button sits in the **same rightmost position** as any main action. Moving dangerous buttons around to be "safe" breaks the habit everywhere else.
- **Enter never triggers a destructive action.** In a destructive dialog, initial focus is on **Cancel** (or Back, in a multi-step destructive flow), so a reflexive Enter cancels. The user clicks the red button, or tabs to it.
- Irreversible whole-vault actions keep two steps or type-to-confirm, as deleting a vault already does.
- Undoable actions get no confirmation.

**6. Multi-step flows.** Back on the left; Next on the right; the last step's specific verb (or Done) on the right. Cancel or `×` leaves from any step. A per-step "Skip" goes in the left-side alternative position.

**7. Narrow screens.** When an action row stacks (already the behavior), the **main action is on top**, then Cancel, then any alternative.

**8. Menus** (context menus, the app menu, palette submenus):
- **`…` means "opens a dialog that asks for more"** before anything happens ("Rename Vault…", "Add New Tag…"). No ellipsis means it acts immediately. Many items already do this; make it universal.
- Separators group related items, with the most-used first.
- **Destructive items go last**, in their own group, in red where the menu style allows.
- Keyboard shortcuts are shown right-aligned in the item when one exists.
- Disabled items stay visible but greyed when the reason is discoverable; hide them only when they can never apply in that context.

### A3. Dialogs to change (found 2026-10-23)

These rows put the action first, so reorder them as shown. The `(primary)` labels are set dynamically; check them.

| `app/static/js/modules/modals/…` | Today | Should be |
|---|---|---|
| `ai-agent-settings-modal.js:270` | Save · Cancel | Cancel · **Save** |
| `backup-settings-modal.js:199` | (primary) · Cancel | Cancel · **(primary)** |
| `delete-namespace-modal.js:224` | Continue · Cancel | Cancel · **Continue** |
| `delete-namespace-modal.js:280` | Delete vault · Back | Back · **Delete Vault** (red; focus on Back) |
| `namespace-modals.js:367` | Open in This Tab · Open in New Tab · Cancel | Open in New Tab ··· Cancel · **Open in This Tab** |
| `namespace-modals.js:614` | Create and Open Vault · Cancel | Cancel · **Create and Open Vault** |
| `namespace-modals.js:813` | Rename and Restart · Cancel | Cancel · **Rename and Restart** |
| `namespace-modals.js:1006` | Save Ports · Cancel | Cancel · **Save Ports** |
| `note-layout-appearance-modal.js:116` | (primary) · Cancel | Cancel · **(primary)** |
| `password-modal.js:213` | Add Password · Cancel | Cancel · **Add Password** |
| `password-modal.js:262` | Change Password · Cancel | Cancel · **Change Password** |
| `password-modal.js:483` | Remove Password · Cancel | Cancel · **Remove Password** (red; focus on Cancel) |
| `reminder-modal.js:956` | (primary) · Clear form | Clear Form ··· **(primary)** |
| `session-timeout-modal.js:136` | (primary) · Cancel | Cancel · **(primary)** |

Already in order: `alphabetize-root-notes-modal.js:140`, `date-range-modal.js:116`, `export-options-modal.js:246`, `prioritize-modal.js:315`, `reset-updated-at-modal.js:130`, `search-suggestion-statistics-modal.js:269`. Check their focus and Enter behavior anyway; several are destructive (`.danger-btn`).

Also review:
- **Action rows built outside `.form-actions`.** The scan above only found `.form-actions` rows.
- **AI chat inline confirmations** (`#ai-chat-panel .ai-chat-confirmation .form-actions`). Proposed: same order and key rules.
- **The ontology editor and the command palette.** They're exempt from shared modal *styling* in `docs/ui/modals.md`. Proposed: the order and key rules still apply; their visual styling stays exempt.
- **Every destructive dialog:** does Enter currently trigger the red button? Fix any that do.
- **Menus:** walk every context menu and the app menu against rule 8.

### A4. Make it stick

1. **Document it.** Add a "Dialog and menu conventions" section to `docs/ui/modals.md` (or a sibling `docs/ui/dialog-conventions.md` linked from it and from `docs/ui/interaction-principles.md`) stating A2 **with its reasons**, as `interaction-principles.md` does.
2. **Check it automatically.** Add a test or ShockHarness rule that fails when:
   - a modal action row's rightmost button isn't its primary or destructive action, or
   - a destructive dialog's initial focus is the destructive button, or Enter triggers it.

   Run it in the existing gates.
3. **One source of truth.** Where practical, have `BaseModal` (or a shared helper) render the action row from a declaration (main action, Cancel, optional alternative, destructive flag), so order and focus come from one place instead of each modal's markup.
4. **Interaction principles:** these rules govern what's *on* a dialog. They don't add motion or emphasis, so they fit within `docs/ui/interaction-principles.md` as written.

### A5. Done when

- Every dialog and menu follows A2, with labels converted once the maintainer confirms the capitalization style.
- The conventions are documented with their reasons.
- The check runs in CI, and fails on a deliberately wrong test fixture.
- Browser smoke and the existing modal tests pass.

---

## B. The new mark

Built 2026-10-24 on its own (`brand/README.md`), before this part.

---

## Found when filed (2026-10-24)

- The `.form-actions` line numbers in A3 match the code, except `ai-agent-settings-modal.js`: its row is now at line 259 (the dialog was redesigned on `feature/ai-providers`), still Save · Cancel.
- `reminder-modal.js:956` uses `.reminder-form-actions`, not `.form-actions`.
- The "dismiss-only Close/OK buttons are not used" line that `errors-and-status-rule.md` replaces is `docs/ui/modals.md:137`.

## Questions for the maintainer

1. Title Case for all buttons and menu items (proposed), or sentence case?
2. Any dialog where you *want* the main action somewhere other than the right? Proposed: none, with no exceptions.
