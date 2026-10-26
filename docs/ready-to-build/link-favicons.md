# Show site icons (favicons) on links

**Status:** Agreed with the maintainer 2026-10-25. Ready to build, not started; filed here from `docs/inbox/` on 2026-10-25. Second to build, after `super-tag-last-values.md`.
**Scope:** where a link displays with its fetched title, show the website's small icon before the title.

Written without running the code. Check every reference before relying on it; build only what's missing. Document the result where link titles are documented.

---

## 1. Fetching

- **Source:** the icon declared in the page already fetched for the title (`<link rel="icon">`, `rel="shortcut icon"`, `rel="apple-touch-icon"` as a fallback; prefer a small size). If none, try the site's `/favicon.ico`.
- **Server-side only**, never from the browser, using the same protections as the title fetch in `app/services/link_titles.py` / `app/services/public_http.py`: redirect limit, the internal-address guard, a size limit (a small cap suits icons), timeouts.
- **Validate the image type** as `app/services/remote_image_proxy.py` does.
- **SVG:** icons in SVG can contain script. Either rasterize to PNG on the server or accept raster formats only. Never serve a fetched SVG as-is.
- **Failures** are quiet: no icon. Retry on the title fetch's schedule or less often.

## 2. Storage

- **One icon per website** (origin), not per link: many links to the same site share it.
- **Encrypted** per vault like `link_titles` (add it to `app/encryption_audit.py`'s coverage).
- Small: icons only (for example a few KB after normalizing to one small size).

## 3. Display

- A small icon, sized to the text, **before** the link title, wherever links render with fetched titles.
- **Dark theme:** many icons are dark on transparent; put a subtle light tile behind the icon so it stays visible.
- No icon available: show nothing (no placeholder).
- Must stay quiet in link-heavy notes: no extra spacing or borders beyond the small tile.

## 4. Privacy

Unchanged from titles: the browser never contacts the linked site; the server fetches, about once per site.

## 5. Tests

- A page declaring an icon: that icon is fetched, stored once per origin, and shown before the title.
- No declared icon: `/favicon.ico` is used; neither: no icon, no error.
- An SVG icon is rasterized or refused, never served as SVG.
- Oversized, wrong-type or redirect-looping icons are refused quietly.
- Two links to the same site cause one fetch and share the icon.
- Stored icons are encrypted (encryption audit passes).
- Dark theme: the tile keeps a dark icon visible.

## Found when filed (2026-10-25)

- The references hold: `app/services/link_titles.py`, `app/services/public_http.py`, `app/services/remote_image_proxy.py` and `app/encryption_audit.py` (which already covers `link_titles`).
- **A schema change:** one stored icon per origin is a new table (or new columns), so per AGENTS.md it bumps `CURRENT_DATABASE_VERSION` (now 11, `app/db/version.py`) with a migration step in `app/db/migrations.py`, keys the encryption audit on the new version, classifies every new column, and documents readable structural metadata in `docs/security/README.md`. Not "small" in that respect.
- Link titles are documented in `docs/ui/content-formatting.md` (and `docs/AI-SUMMARY.md`); it points here now.
