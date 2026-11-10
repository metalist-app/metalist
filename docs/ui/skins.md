# Skins

A skin changes how MetaList looks from top to bottom: painted art, fonts, cursors. It is chosen under `Theme`, in the command palette and the right-click `Themes` menu, next to `System`, `Light` and `Dark`. MetaList has one, `Ye Olde Scrypte`, a late-medieval manuscript (internally `illuminated`: the saved value and file names).

Skins are reviewed and ship with MetaList; nobody installs one. A contributed skin comes in as a change to this repo, so its art is served by MetaList (the page's content security policy allows nothing else) and a skin that breaks something is caught in review.

## What a skin is

- `app/static/css/skins/<name>.css`, linked from `app/templates/base.html`. Every rule starts with `html[data-skin="<name>"]`, so with another theme chosen the file does nothing and its art is never downloaded.
- `app/static/img/skins/<name>/`, its art.
- Any font it uses, in `app/static/fonts/<font>/` with its licence beside it: a skin never names a font that only some systems have.
- One entry in `app/static/js/modules/theme-choices.js` and in the allowed values of `pref.theme` (`app/services/client_state_service.py`).

A skin is drawn over the light theme: choosing one sets `data-theme="light"` as well as `data-skin`. Everything that asks for the theme (exports, diagrams, Excalidraw) sees light.

Printing and exported HTML are their own documents and never carry a skin.

## What a skin can reach

- Cursors: MetaList's own styles ask for `var(--skin-cursor-pointer, pointer)`, `var(--skin-cursor-default, default)` and `var(--skin-cursor-text, text)`.
- Colours: the theme variables (`--bg-color`, `--text-color`, `--search-shell-surface`...).
- The first letter of the opening notes (the list's first, and each one after an ornament): `app/static/js/modules/skin-initials.js` marks them with `data-initial="T"` while a skin is on.

## What the browsers require

- **A cursor image is at most 32x32 CSS pixels.** Chrome and Firefox swap a larger one for the regular cursor wherever it would stick out of the page, so it reverts near the window's edges.
- **Firefox gives `::first-letter` only to the block that holds the text itself,** not to an ancestor, and ignores `line-height` on a floated first letter. `skin-initials.js` finds and marks that block (`data-initial-host`), however the note's text is wrapped; the letter's box is padding around a 1px letter. The mark, like old-English words, is removed before a note is edited or saved.
- **An `@container` or hover rule in `main.css` can outrank a skin's base rule.** State `:hover` explicitly where a skin wants no change.

## Ye Olde Scrypte

- From a window 1180px wide: parchment, torn left and right edges over a dark desk, vines tiled down both sides, knotwork corners at the top, and lilies, grapes and birds on the joins between vine tiles.
- The first letter of the list's first note, and of the note after each ornament, is a 40px painted capital, open or folded. A note being edited has none. A note whose first letter is followed by punctuation gets a boxed letter instead, and code, JSON, CSV, Mermaid and LaTeX notes get none.
- After every fourth top-level note, a painted ornament, from twelve in a fixed order, so one comes back only after 48 notes. Position is counted from the top of the whole list (`ModeContext.getRootWindowStart`), because on a long list the page holds only a window of it.
- The quill is the pointer, and the painted hand points at what can be clicked. Both are 48px and drawn on the page where the mouse is (`skin-pointer.js`), since a real cursor that size reverts near the window's edges; the real cursors are blank pictures whose names say which to draw. Resize arrows, `wait` and the like stay the browser's own.
- Fold arrows are pairs of pictures, closed and open (a bud and a flower, a shut door and an open one), sixteen in all, dealt to notes like cards from a shuffled deck: each once, then a reshuffle. A note keeps its card while the page is open.
- The script is Eagle Lake (SIL Open Font License, shipped unaltered with its licence in `app/static/fonts/eagle-lake/`), so Windows, macOS and Linux draw the same letters.
- While a note is edited it is in MetaList's regular font and size; the script is for reading.
- Struck-out words are scribbled over in ink; while editing they keep a plain line.
- Code, tables, diagrams and embeds have no panel of another colour behind them, only the parchment. Colours that mean something (a highlight, a diff, a chess board) stay.
- A note's words are drawn as old English (`app/static/js/modules/skin-olde-words.js`, its tables in `skin-olde-vocabulary.js`): you as thou or thee, the as ye, has as hath, she walks as she walketh, and old spellings by a word's ending (mutation as mutacioun, walked as walk'd). A capitalised word inside a sentence is taken for a name and keeps its spelling. Only the drawing changes. Code, links, tables of data and references keep their exact text. Each swapped word is a span holding the real word: editing and saving restore it (`dom-utils.setNoteEditable`, the differential view, and `sanitizeNoteHtmlForStorage` as the last guard). Copying gets the real words without any handling: a note's text can be selected only while editing, and Copy on a note is built by the server from the saved note. Find and search highlights see the drawn words.
- Not skinned yet: the command palette, dialogs, the `[[` and tag suggestions, dark colours, the phone layout.
