# Skins

A skin changes how MetaList looks from top to bottom: painted art, fonts, cursors. It is chosen under `Theme`, in the command palette and the right-click `Themes` menu, next to `System`, `Light` and `Dark`. MetaList has one, `Illuminated`, a late-medieval manuscript.

Skins are reviewed and ship with MetaList; nobody installs one. A contributed skin comes in as a change to this repo, so its art is served by MetaList (the page's content security policy allows nothing else) and a skin that breaks something is caught in review.

## What a skin is

- `app/static/css/skins/<name>.css`, linked from `app/templates/base.html`. Every rule starts with `html[data-skin="<name>"]`, so with another theme chosen the file does nothing and its art is never downloaded.
- `app/static/img/skins/<name>/`, its art.
- One entry in `app/static/js/modules/theme-choices.js` and in the allowed values of `pref.theme` (`app/services/client_state_service.py`).

A skin is drawn over the light theme: choosing one sets `data-theme="light"` as well as `data-skin`. Everything that asks for the theme (exports, diagrams, Excalidraw) sees light.

Printing and exported HTML are their own documents and never carry a skin.

## What a skin can reach

- Cursors: MetaList's own styles ask for `var(--skin-cursor-pointer, pointer)`, `var(--skin-cursor-default, default)` and `var(--skin-cursor-text, text)`.
- Colours: the theme variables (`--bg-color`, `--text-color`, `--search-shell-surface`...).
- The first letter of the opening notes (the list's first, and each one after an ornament): `app/static/js/modules/skin-initials.js` marks them with `data-initial="T"` while a skin is on.

## What the browsers require

- **A cursor image is at most 32x32 CSS pixels.** Chrome and Firefox swap a larger one for the regular cursor wherever it would stick out of the page, so it reverts near the window's edges.
- **Firefox gives `::first-letter` only to the block that holds the text itself,** not to an ancestor, and ignores `line-height` on a floated first letter. Name the inner blocks in the selector, and make the letter's box from padding around a 1px letter.
- **An `@container` or hover rule in `main.css` can outrank a skin's base rule.** State `:hover` explicitly where a skin wants no change.

## Illuminated

- From a window 1180px wide: parchment, torn left and right edges over a dark desk, vines tiled down both sides, knotwork corners at the top, and lilies, grapes and birds on the joins between vine tiles.
- The first letter of the list's first note, and of the note after each ornament, is a 104px painted capital. A note whose first letter is followed by punctuation gets a boxed letter instead, and code, JSON, CSV, Mermaid and LaTeX notes get none.
- After every fourth top-level note, a painted ornament, from twelve in a fixed order (`:nth-child(48n + ...)`), so one comes back only after 48 notes.
- The quill is the pointer, and the painted hand points at what can be clicked.
- Not skinned yet: the command palette, dialogs, the `[[` and tag suggestions, dark colours, the phone layout.
