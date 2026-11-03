# Passwords shown as dots, not blurred

**Status:** Agreed with the maintainer 2026-11-03. Ready to build. **Replaces** the blurred `@password` value (`docs/ui/content-formatting.md`, `@password`; `docs/ui/references.md`, links to `@password` notes; `docs/ui/tag-bar.md`).

Written from a read-only look at the repo. Check the code references before relying on them.

---

## 0. Today (from the code)

- The credential row puts the real password in the page as text and blurs it with CSS (`app/services/content_formatting.py`, the credential row; `app/static/css/main.css`, `.meta-credential-password .meta-credential-value { filter: blur(4px) }`, also on `.meta-credential-copied`). `.meta-credential-value` has `user-select: text`.
- A link to a password note does the same (`render_credential_link_row`).
- Copying reads `data-copy-value`, not the text (`app/static/js/modules/mode-manager/events/mouse-events.js`, `credential.copy`).
- Exports, prints and the AI show `CREDENTIAL_MASK` (8 bullets). A floating note's title replaces passwords with `••••` (`floating-note-dom.js`, `getFloatingNoteTitle`).
- The copy log records `valueLength`.

## 1. Why

Blur hides a password from a glance, not from the page. The real text can be selected, read aloud by a screen reader, and possibly matched by the browser's find (verify); its length and outline show through; blurred text in a screenshot or screen share can sometimes be recovered.

## 2. The rule

- A password value shows as `CREDENTIAL_MASK` (`••••••••`), always 8 bullets, whatever its length.
- The real value is never page text: only `data-copy-value` holds it.
- Clicking copies the real value, as now, with the same flash.
- An accessible label on the value: "Password, hidden, click to copy" (so a screen reader doesn't read eight bullets).
- Editing the note shows the real text, as now.

## 3. Where

- The note's own row, a link to it, an embed of it.
- The floating note title: `CREDENTIAL_MASK` instead of 4 bullets, so every hidden password looks the same.
- Unchanged: exports and prints (mask, or the real value when the user includes passwords), `@username` (shown in full).

## 4. Also

- The copy log drops `valueLength`.
- The password blur CSS goes.

## 5. Invariants

1. A password's text, length and outline never appear on the page; only the mask.
2. Every place that hides a password uses the same mask.
3. Copy gives the real value.

## 6. Not decided

- A Show button (eye) revealing the value for a few seconds: not part of this.

## 7. Done when

1. In view mode, a password row, a link to it and an embed of it show 8 bullets for passwords of any length; selecting the row and the browser's find never yield the real value; copying does.
2. A screen reader announces the label, not the bullets.
3. The floating note title shows 8 bullets.
4. `docs/ui/content-formatting.md`, `docs/ui/references.md`, `docs/ui/tag-bar.md`, the help search skill and the help say dots, not blur; `tests/unit/test_password_reference_links.py` and `scripts/browser-credential-link-regressions.mjs` check that the real value isn't in the page text.

## 8. Found while filing (2026-11-03)

- The code references hold: the credential row and `render_credential_link_row` (`app/services/content_formatting.py`), `CREDENTIAL_MASK` (8 bullets, same file), the blur on `.meta-credential-password .meta-credential-value` and its `.meta-credential-copied` variant (`main.css`), `credential.copy` logging `valueLength` (`mouse-events.js`), the floating title's `••••` (`floating-note-dom.js`, `getFloatingNoteTitle`). An embed of a password note draws the same row as the note's own.
- When passwords are redacted (exports, prints), `data-copy-value` already holds the mask, not the value.
- The help says "blurred" in more skills than the search one: `help-formatting.md`, `help-meta-tags.md`, `help-references.md`, `help-privacy.md` (it also says a blurred display is no substitute for vault encryption). All need the dots wording.
- Open: `copyable.copy` (`@copyable` values, not passwords) also logs `valueLength`. Only `credential.copy` is meant to drop it?
