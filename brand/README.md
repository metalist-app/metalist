# The MetaList mark

A block **M** over two bars, thin over thick, the bars exactly as wide as the M.

## Sources

| File | What | Use it |
|---|---|---|
| `metalist-mark-black.svg`, `metalist-mark-white.svg` | the full mark | wherever it shows at about 32 px or larger |
| `metalist-mark-small-black.svg`, `metalist-mark-small-white.svg` | one bar instead of two | at 24 px and below (favicons, tray or menu-bar icons), where two bars blur into one |

Never show both versions side by side.

## Rules

- **Black or white only** (`#000000`, `#ffffff`). Icons put the white mark on a black tile.
- **Clear space:** at least the gap between the two bars, on every side.
- **Don't** recolor, stretch, outline, rotate, or add shadows or other effects.
- **On a square tile** the mark is about 60% of the tile's width, centered, and lifted
  slightly (2% of the tile) because the bars make it bottom-heavy. Platforms crop or round
  app icons, so they keep that margin.
- **The favicon** is the exception: its mark is 84% of its tile, as big as other sites'
  icons beside it in a tab bar (2026-10-24); the black tile still frames it on light tab bars.

## Generated files

Every raster, and `app/static/img/favicon.svg`, is drawn from these sources:

```bash
.venv/bin/python scripts/generate_brand_icons.py
```

Commit the regenerated files with the change to a source; `tests/unit/test_brand_icons.py`
fails when a committed icon no longer matches what the script draws.

| File | Size | Contents |
|---|---|---|
| `app/static/img/favicon.ico` | 16, 32, 48 | one-bar mark on a black rounded tile (the same in light and dark browser themes) |
| `app/static/img/favicon.svg` | any | the same, as a vector |
| `app/static/img/apple-touch-icon.png` | 180 | full mark on a black square, no transparency (iOS rounds the corners) |
| `app/static/img/icon-192.png`, `icon-512.png` | 192, 512 | full mark on black, for `app/static/manifest.json` |
| `app/static/img/icon-maskable-512.png` | 512 | the same, mark at 55% so it survives a circular crop |
| `generated/ios-app-icon-1024.png` | 1024 | App Store master for a future phone app, no transparency |
| `generated/google-play-icon-512.png` | 512 | Google Play master |
| `generated/android-adaptive-foreground-432.png` | 432 (108 dp at xxxhdpi) | adaptive-icon foreground, transparent, mark inside the 66 dp safe circle; its background layer is solid `#000000` |
| `generated/avatar-1024.png` | 1024 | profile picture for the GitHub organization and PyPI (uploaded by hand) |
| `generated/metalist-mark-{black,white}-{512,1024}.png` | 512, 1024 wide | the mark alone, transparent |

The `generated/` masters are not part of the installed app.

## License

The MIT license covers MetaList's code, not its name or this mark. A `TRADEMARK.md` saying
how others may use them does not exist yet; link it here once it does.

## Later (decided 2026-10-23)

- **A wordmark**, `metalist-wordmark-{black,white}.svg`: the full mark beside "MetaList" in
  Archivo ExtraBold (800), **text converted to outlines** so it never depends on an
  installed font; the mark about the text's cap height, the gap about half the M's leg
  width. Confirm Archivo's license (SIL OFL, Google Fonts) allows this before shipping.
  Nothing in the app uses it; it is for a landing page, store listings or a README header.
