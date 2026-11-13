# Two More Skins: Phosphor and Vellum

**Status:** Agreed with the maintainer 2026-11-12. Ready to build.
**Scope:** two new skins, made the way `docs/ui/skins.md` describes. **Phosphor** is a retro terminal over the dark theme. **Vellum** is warm paper over the light theme.

## 1. Why

Fathom is the crafted dark theme and Ye Olde Scrypte the playful one; Light has only the plain theme beside it. Vellum fills that gap as a calm light theme for long reading. Phosphor is for fun, and programmers will like it.

## 2. Phosphor

- **Base theme: dark.** A near-black screen, one green for the text, and a faint glow on the letters.
- **One hue carries everything,** so nothing may depend on colour alone:
  - Text, tags and headings come in brighter and dimmer greens.
  - Links are underlined.
  - The caret is a block, or at least a wide caret.
  - A selection is inverse: black on green.
- **Colours that mean something stay:** `@red`, `@green`, `@blue`, highlights, diffs and a chess board. Re-tune each one to read on black at 4.5:1 or better, as Fathom did for the grey.
- **Notes in the system's own monospace,** the same exception Fathom has (agreed with the maintainer 2026-11-12). The rest of MetaList keeps its own font, as in Fathom.
- **No flicker or other animation, ever,** with or without `prefers-reduced-motion`.
- **Scanlines and a vignette:** optional, and barely visible if used.
- **Speed:** a long list must scroll as smoothly as in Dark. If a text shadow on every note slows it, drop the glow from notes and keep it on the chrome.
- **Green.** Amber is left for later.

## 3. Vellum

- **Base theme: light.** Cream paper, dark brown ink, and soft muted colours for links, tags and accents.
- **Not the manuscript.** No art, torn edges, ornaments, painted initials, drawn cursors or old-English words; `isManuscript: false`. It's a quiet theme for long reading and writing.
- **The page a shade darker than the notes,** like Fathom's panel and editor. The note being edited is a slightly lighter sheet.
- **Notes in a book serif,** shipped in `app/static/fonts/<font>/` with its licence: an Open Font License serif such as Literata or Source Serif 4 (*proposed*, builder's pick). The rest of MetaList keeps its own font.
- **Re-tune `@red`, `@green` and `@blue`** so they read on cream.

## 4. Both

- **Values and labels:** `phosphor` / `Phosphor` and `vellum` / `Vellum`, in `SKINS` (`theme-choices.js`) and in the allowed values of `pref.theme`.
- **Order in Theme:** Fathom, Phosphor, Vellum, Ye Olde Scrypte (*proposed*).
- **Same reach as Fathom:** dialogs, menus, the command palette and suggestion lists use the skin's colours.
- **Every text colour is 4.5:1 or better** on the background it sits on.
- **Own colours.** If a palette comes from an existing theme, put its licence and credit beside the CSS, as `fathom.LICENSE.txt` does. Use no other theme's name.
- **Documentation:** a section for each in `docs/ui/skins.md`, `help-menus.md` (the `Theme` line), and the release's lines in `CHANGELOG.md`, from which the release-notes help is generated (see §7).

## 5. Invariants

1. Every text colour in either skin is 4.5:1 or better on its own background.
2. Phosphor never animates.
3. Nothing in Phosphor depends on colour alone.
4. Vellum has none of the manuscript's art or behaviour.

## 6. Open

- An amber Phosphor, as a second skin or a choice inside it: later, if wanted.
- Everything marked *proposed* is for the builder to try.

## 7. Checked against the code (2026-11-12)

Filed from `docs/inbox/` on 2026-11-12. Not built.

- **Right as written:** `SKINS` in `app/static/js/modules/theme-choices.js` (`label`, `baseTheme`, `isManuscript`); `fathom.LICENSE.txt` beside `app/static/css/skins/fathom.css`; fonts in `app/static/fonts/<font>/` (only `eagle-lake` today).
- **Where `pref.theme`'s values live:** `app/services/client_state_service.py` (`"pref.theme": {"system", "light", "dark", "illuminated", "fathom"}`).
- **Corrected:** `help-releases.md` is generated from `CHANGELOG.md` by `scripts/sync_release_notes_help.py` and is never edited by hand; §4 now says so.
- **`help-menus.md` is full:** 31,983 of its 32,000 characters. Naming two more skins on its `Theme` line takes it over, so part of it has to move to another help topic first (as `tags` was split, `docs/AI-SUMMARY.md`).
- **The monospace exception (§2):** `docs/ui/skins.md` allowed a system font for Fathom alone (agreed 2026-11-11). The maintainer agreed on 2026-11-12 that Phosphor takes the same exception; `tests/unit/test_skins.py`, which checks it for Fathom, has to allow Phosphor too.
- **Tests to extend:** `tests/unit/test_skins.py` (each skin linked from `base.html`, its fonts, its colours) and the `skin` browser suite (`scripts/browser-skin-regressions.mjs`).

