# User-defined styles: `@style=name`, a safe subset of CSS (future plan)

**Status:** **Direction only. Don't build yet.** The direction is agreed with the maintainer (2026-10-25); details are open (§5). File it in `docs/future-plans/`. Sent now so related work (skins, menus following the theme, sharing setups) doesn't close off this direction. Related: `docs/design/skins-brainstorm.md`.

Written without running the code. References are from reading it; verify before relying on them.

---

## 1. The idea

- Today a rule like `bug => @red` makes every note tagged `bug` red, but only through MetaList's built-in `@` tags, a fixed set.
- **Users want their own looks,** and **shared setups** (tag structures and rules exchanged as files, a separate future plan) should be able to carry how their tags look, not only how they relate.
- **The `@` tags stay reserved,** like the search keywords `OR`, `max` and `min`. Users never add new `@` tags.

## 2. Naming: one reserved `@style` tag, user-named values (agreed)

- **`@style` is a single reserved tag; its value is a style name the user defines:** `bug => @style=alert`, `@ai => @style=borrowed`.
- The reserved vocabulary doesn't grow; the names belong to the user.
- Styles are triggered the usual way: a tag on the note, or a rule implying `@style=…`. They compose with everything else.

## 3. Styles are real CSS, restricted to a safe subset (agreed)

- **Real CSS rather than a simplified vocabulary:** less to learn for people who know CSS, and more powerful.
- **Why restrict it:** CSS runs no code, but unrestricted CSS in a shared setup could still **contact other servers** (`url(…)` reveals when notes are opened; clever selectors can leak page content), **fake interface** (a drawn "session expired, enter your password" box), or **hide or rearrange content.**
- **The safe subset:**
  - **Users write declarations only, never selectors.** A style is a list of `property: value` lines; **MetaList generates the selector,** scoped to notes carrying that `@style` value.
  - **Allowed (starting list):** text color, background color, font weight, font style, text decoration, border and its parts, border radius, opacity (with a floor so text can't vanish), and similar purely visual properties.
  - **Never allowed:** `url()` in any form, `content`, `position`, `z-index`, transforms, `display` or `visibility` that hide notes, `@import`, `@font-face`, animations, and anything else that loads resources or moves things.
  - **Checked with a real CSS parser on the server,** against an allow-list, with a clear message on rejection; never pattern-matched text.
  - **Defense in depth:** the Content Security Policy (`app/security/http_headers.py`) should block style-triggered loads from other servers even if a check were missed.

## 4. Styles in shared setups (agreed)

- A shared setup can carry **style definitions** alongside the rules that use them.
- **Import review:** styles are shown like rules, **with a preview**, and accepted per item. A name collision with one of the recipient's styles is flagged (namespace, rename or keep theirs). Disallowed CSS is rejected at import with a message; nothing is half-applied.

## 5. Still open

1. The exact allow-list and value limits (the opacity floor).
2. **Light and dark:** a style written for one theme may be unreadable in the other. One definition or two per style, or a computed dark version.
3. Several `@style` values on one note: which wins, or how they combine.
4. Whether the built-in color tags (`@red` and so on) become predefined `@style` values.
5. Where styles are edited: beside the tag editor, or a separate style list.

## 6. Invariants (agreed)

1. `@` tags stay reserved; users name styles only as `@style` values.
2. A user style is declarations only; MetaList writes and scopes the selector.
3. No style can load anything from another server, add text, or move or hide notes.
4. Imported styles are previewed and approved per item, like rules.

## 7. Checked 2026-10-27 (filed from the inbox)

- Filed as a future plan, as its status asks. Confirmed: `docs/design/skins-brainstorm.md` and the Content Security Policy in `app/security/http_headers.py` exist.
