# Rename "tabs" to "search contexts"

**Status:** Agreed with the maintainer 2026-10-25. Small; ready to build.
**Scope:** what the interface, help and docs call MetaList's tabs (a saved search plus its view options, listed under the folder icon left of the search field). Interface labels, command palette names, help pages, the AI's help guides and the docs; code identifiers only where convenient.

Written without running the code. Every reference below came from reading it and must be checked before relying on it.

---

## 1. Why

- **"Tab" now means two things.** The feature was named when several browser tabs on one vault weren't allowed, so MetaList's own tabs replaced them. With several views at once (`docs/ready-to-build/multi-view-editing.md`), browser tabs, the phone and MetaList's tabs coexist, and "tab" is ambiguous. The menus already show the clash: `Open ▸ New Tab` (a MetaList tab) beside `Open in New Tab` (a browser tab) in the vault and link menus.
- **"Search context" says what one is:** a search plus its view options. It's also what the maintainer already calls them. **"Context"** alone is accepted shorthand where space is short.
- Considered and set aside: "lenses" (too abstract), "views" (MetaList says "view options," and "view" now means one place the vault is open: a browser tab or the phone), "saved searches" (too literal), "spaces"/"workspaces" (suggest separate content).

## 2. What changes

- **Labels,** for example (verify each):
  - `Show ▸ Tabs` (view menu, `context-menu-registry.js`) → `Show ▸ Search Contexts`
  - `Open ▸ New Tab` → `Open ▸ New Search Context`
  - command palette `Show Tabs` / `Hide Tabs` (`endpoint-registry.js`, `pref.show_tab_ui`) → `Show Search Contexts` / `Hide Search Contexts`; keep the old words as search aliases in the palette so muscle memory still finds them
  - tooltips, empty states, confirmations and anything else that says "tab" for this feature
- **Help pages, help videos' text, and the AI's help guides.**
- **Docs:** `docs/ui/controls.md`, `docs/ui/state-handling.md`, `docs/ui/references.md`, `docs/ui/command-palette.md` and others that say "tab" for this feature. Some already say "search-context overlay"; make it consistent.
- **Code identifiers** (`tab_state.py`, `tabId`, `pref.show_tab_ui`, endpoints): **only when convenient,** for example when touching them for the multi-view work. Stored preference keys and saved data must keep working; don't break existing vaults for a name.

## 3. What doesn't change

- **"Tab" the key** (`Tab` toggles focus) and **browser tabs** (`Open in New Tab`, `Open Image in New Tab`) keep their names.
- **"View options"** (sort, date range, files, untagged) keep their name for now. Renaming them is undecided.
- **Don't introduce "view" as an interface word** for a browser tab or the phone; it's a design-doc term.

## 4. Tests

- No interface label, tooltip or help text uses "tab" for this feature.
- The command palette finds the commands by both the new names and "tab."
- Existing vaults' saved search contexts and the show/hide preference survive the change.

## 5. Checked 2026-10-27 (filed from the inbox)

- Confirmed: the view menu's `Show ▸ Tabs` (`id: 'show-tabs'`) and `Open ▸ New Tab` (`id: 'new-tab'`) in `context-menu-registry.js`; the palette's Show/Hide label built from `'Tabs'` for `pref.show_tab_ui` (`endpoint-registry.js`); `"label": "Show Tabs"` in `app/static/config/agent-menu-actions.json` (the AI help's menu catalog, which changes too).
- Browser tabs keep their names: `Open Image in New Tab`, `Open Link in New Tab`.
