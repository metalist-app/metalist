# MetaList mark: trimmed bars, a small-size variant, and the icon set

**Status:** Agreed with the maintainer 2026-10-23. Ready to build, not started. Filed here from `docs/inbox/` on 2026-10-23, with its paths checked against the repo (see "Found when filed" in §6).
**Scope:** Replace the current mark with a slightly refined version, add a one-bar variant for very small sizes, and produce the full set of icons the web app, a future phone app, and the project's public profiles need, from SVG sources and in a way that can be repeated. The app's interface does not change.

Written without looking closely at the code. Check every path below before relying on it; build only what is missing.

---

## 1. The mark: what changes

Today the mark is a block M over a thin bar and a thick bar, and the bars are wider than the M: `app/templates/_logo_mark.html` and `app/static/img/metalist-logo-{black,white}.svg`, viewBox `0 0 340 223`, bars at `x=0 width=340`.

**New mark (the only geometric change: the bars stop where the M stops).** Normalized to start at 0:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 279 223">
  <title>MetaList</title>
  <polygon points="0,0 69,0 139,50 210,0 279,0 279,136 195,136 195,87 139,128 83,87 83,136 0,136"/>
  <rect x="0" y="159" width="279" height="16"/>
  <rect x="0" y="197" width="279" height="26"/>
</svg>
```

The M is unchanged, only shifted left by 30 units. The thin-over-thick bars keep their thickness and spacing.

**Small-size variant: one bar.** At 16–24 px the two bars blur into one, so the smallest sizes use:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 279 192">
  <title>MetaList</title>
  <polygon points="0,0 69,0 139,50 210,0 279,0 279,136 195,136 195,87 139,128 83,87 83,136 0,136"/>
  <rect x="0" y="162" width="279" height="30"/>
</svg>
```

**Rule:** the full mark wherever it renders at about 32 px or larger; the one-bar variant at 24 px and below (favicons, menu-bar or tray icons, any tiny UI use). Never both side by side.

**Colors:** black or white only, as today (`#000000` / `#ffffff`). Icons put the white mark on a black tile.

## 2. Where it's used today: update in place

- `app/templates/_logo_mark.html`: the inline SVG on the login and locked screens. Switch to the new geometry and `viewBox="0 0 279 223"`.
  - `.login-logo-mark` in `app/static/css/main.css` renders it at `width: 100%`. The new mark is narrower (279 vs 340 units), so the M will grow unless the container narrows to match.
  - Keep the M about the size it is now, and check anything sized from the logo's width (the login progress bar is described as "the logo's width").
- `app/static/img/metalist-logo-{black,white}.svg` and the `-512.png` and `-1024.png` versions: regenerate from the new source.
- `app/static/img/favicon.ico`: referenced from `base.html`, `locked.html`, `namespace_deleted.html`, `namespace_renamed.html` (with `?v=${asset_version}`), allowed without auth in `app/api/middleware/auth.py`, and used by `scripts/browser-smoke.mjs`. Keep that path working.
- Docs that describe the logo: `docs/ui/login-screen.md` ("Code"), `docs/AI-SUMMARY.md` (login screen line).

## 3. New files to produce

Keep the **SVG sources** in one place (for example a `brand/` or `docs/brand/` folder, your call). Generate every raster from them with a small script, so a later tweak is one edit plus one command. No hand-exported PNGs.

| Asset | Contents | Notes |
|---|---|---|
| `metalist-mark-{black,white}.svg` | full mark | sources |
| `metalist-mark-small-{black,white}.svg` | one-bar variant | sources |
| `metalist-wordmark-{black,white}.svg` | **Later, not this pass** (decided 2026-10-23). Full mark + "MetaList" in **Archivo ExtraBold (800)** | **Text converted to outlines**, so it never depends on an installed font. Mark height about the text's cap height; gap about half the M's leg width. Confirm Archivo's license (Google Fonts, SIL OFL) allows this before shipping. |
| `favicon.svg` + `favicon.ico` (16, 32, 48 inside) | one-bar variant | Always on a tile, never transparent (decided 2026-10-23): the white one-bar mark on a small black rounded tile, the same in light and dark browser themes. Add `<link rel="icon" type="image/svg+xml" href="…favicon.svg">` beside the existing `.ico` link. |
| `apple-touch-icon.png` 180×180 | full mark, white on a black square, **no transparency** | iOS rounds the corners itself. Add `<link rel="apple-touch-icon">`. |
| Web app manifest icons 192, 512, and 512 maskable | white on black | Maskable: keep the mark inside the central 80% safe zone. Add a manifest only if the app doesn't have one; check first. |
| App store masters (future phone app) | iOS 1024×1024 PNG, square, no alpha; Google Play 512×512; Android adaptive icon foreground (108 dp canvas, mark inside the 66 dp safe zone) on a solid black background layer | No mobile project exists in this repo yet. Produce the masters now so the phone app can pick them up. |
| Profile avatar 1024×1024 PNG | full mark, white on a black square | For the GitHub organization and PyPI. The maintainer uploads it by hand. |

Mark size inside square tiles: about 60% of the tile width, centered optically. The bars make the shape bottom-heavy, so nudge it up slightly rather than centering it mathematically.

## 4. A short usage page

Add a brief doc next to the sources:
- which file to use where (the 32 px / 24 px rule)
- clear space (at least the gap between the two bars on every side)
- black or white only
- "don't recolor, stretch, outline, or add effects"
- how to regenerate the rasters

Also note that the MIT license covers the code, not the logo or name. Point to `TRADEMARK.md` once it exists.

## 5. Done when

- The login and locked screens show the new mark at about today's visual size, with nothing else on those screens shifting.
- Browser tabs show the one-bar favicon in both a light and a dark browser theme.
- All assets in §3 except the wordmark exist, generated by one script from the SVG sources.
- Docs updated (§2, §4); `scripts/browser-smoke.mjs` still passes.

## 6. Open questions for the maintainer

Found when filed (2026-10-23):

- The paths in §2 are right: `_logo_mark.html` (`viewBox="0 0 340 223"`, the M at x=30–309, bars `x=0 width=340`), included by `index.html` and `locked.html`; `.login-logo-mark` at `main.css:110`; the favicon links in `base.html`, `locked.html`, `namespace_deleted.html` and `namespace_renamed.html`; `/favicon.ico` in `app/api/middleware/auth.py:43`; the sanitizer probe in `scripts/browser-smoke.mjs` loads `/static/img/favicon.ico`.
- `app/static/img/metalist-logo-{black,white}.svg` are not the bare mark: they carry a padded `viewBox="-30 -30 400 283"` and a filled background square. Nothing in the app, scripts or docs references them or their `-512`/`-1024` PNGs. Decide whether they are replaced by the new sources (§3) or kept, regenerated, for some outside use. **Decided 2026-10-23: replace them** (and their `-512`/`-1024` PNGs) with the new generated files; nothing in the repo uses them, so nothing else changes.
- There is no web app manifest, `apple-touch-icon` link, `TRADEMARK.md`, or `brand/` folder yet.
- The loading view's progress bar is "the logo's width" (`docs/ui/login-screen.md`, `docs/AI-SUMMARY.md`): with narrower bars it narrows too unless the container keeps today's width. That is an on-screen change, so it follows `docs/ui/interaction-principles.md` (list the cases, agree them) before it is built.

From the design:

1. **Favicon on a tile or transparent?** Decided 2026-10-23: **always on a tile**, never transparent. Today's favicon is a white mark on a transparent background, which disappears on light tab bars; the new one is the white one-bar mark on a small black rounded tile, so it reads on light and dark tabs and matches the app icon. No `prefers-color-scheme` switching.
2. **Ship the wordmark in this pass or later?** Decided 2026-10-23: **later.** Nothing in the app uses it; it is for a future landing page, store listings or a README header, and built later it starts from the final mark. This pass builds every other asset in §3.
