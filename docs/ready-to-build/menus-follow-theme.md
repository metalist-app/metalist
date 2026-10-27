# Menus and modals follow the Light/Dark theme

**Status:** Agreed with the maintainer 2026-10-26. Small; ready to build.
**Scope:** colors of menus, modals, sheets, dropdowns and editors. Update `docs/AI-SUMMARY.md` (the "theme-independent dark shell" line) and any UI doc that describes modal or menu colors.

Written without running the code. Check every reference before relying on it; build only what's missing.

---

## 1. Today (to verify)

- **Modals are dark in every theme on purpose:** `app/static/css/main.css`, "Shared modal shell. Modal contents are intentionally dark in every app theme" (`--modal-*` tokens; `.modal`, `.phone-sheet`, `.phone-capture`). `docs/AI-SUMMARY.md` calls it "the theme-independent dark shell."
- **The right-click menu's CSS already uses theme colors** (`.context-menu` → `--bg-color`, `--text-color`, `--border-color`, white in Light theme). **Yet the maintainer sees menus dark in Light theme.** Find which menus and why (another rule or token, a menu rendered inside the modal shell, the System theme's resolution, or something else) and fix the cause.
- **The ontology editor** keeps its own visual system (an explicit exception to the dark shell).
- **The login and loading screen** is always dark.

## 2. The change

- **Every menu, modal, sheet, dropdown and editor follows the current theme** (Light or Dark; System resolves to one of them). That includes right-click menus and submenus (including the note menu's Created/Updated footer), the command palette, settings and other dialogs, the phone sheets and capture (capture goes away in `phone-same-app.md`), suggestion lists, the paste "Apply as…" card and **the ontology editor**.
- **One exception: the login and loading screen stays dark** in every theme, as now.
- **Keep the unification:** one shared token set, with Light values beside the Dark ones, so feature CSS keeps using the same names.
- **Keep the separation:** in Light theme, menus and modals get a visible border and shadow (and modals the dimmed backdrop) so they stand clearly above the page.

## 3. Why

- Platforms do this: on macOS, Windows and phones, menus and dialogs follow the system appearance.
- A dark panel opening over a white page is the strongest possible contrast, many times a session; it's jarring.
- A Light theme that menus ignore looks like a bug.
- The dark shell came from unifying modal styles, not from a decision about light versus dark.

## 4. Tests

- In Light theme, every menu, submenu, modal, sheet, suggestion list and the ontology editor render light; in Dark theme, dark. Switching the theme while one is open updates it, or it renders in the new theme the next time it opens.
- System theme follows the operating system's appearance for all of them.
- The login and loading screen is dark in all three settings.
- Text and controls meet contrast requirements in both themes (danger red, accent, muted text, disabled items).

## 5. Checked 2026-10-27 (filed from the inbox)

- Confirmed: the shared modal shell (`main.css`, "Shared modal shell. Modal contents are intentionally dark in every app theme"), its `--modal-*` tokens (`--modal-surface: #10151d` and on), the "theme-independent dark shell" line and the ontology editor exception in `docs/AI-SUMMARY.md`, and the paste "Apply as…" card (`paste-format-offer-service.js`).
- Confirmed: `.context-menu` uses `--bg-color`, `--text-color` and `--border-color`, which `html[data-theme="light"]` sets to white, `#333333` and `#dddddd`. So the plain right-click menu should already be light in Light theme.
- **Which menus look dark in Light theme (maintainer, 2026-10-27): the command palette.** Its colours are written into its own rules (`main.css`, `.command-palette-panel` `#0b0b0b`, `.command-palette-input` `#000`, text `#e6e6e6`, the suggestion rows likewise), using neither the `--modal-*` tokens nor the theme's, so it is dark in every theme. Move it onto the shared tokens with the modals. When building, open every other menu, submenu and list in Light theme too: any with fixed colours of their own follow the same fix.
