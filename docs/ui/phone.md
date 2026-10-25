# Phone

Under 640 px wide MetaList becomes a read-only view of the notes plus capture: a phone on the
local Wi-Fi, opened from its home screen. Desktop is unchanged. Built 2026-10-24 as a prototype,
"blocked in": what is left is in [phone-later.md](../future-plans/phone-later.md). The decided
mock: [phone-mocks.html](phone-mocks.html).

## Layout
- The layout comes from CSS (`@media (max-width: 640px)` in `main.css`), so it holds from the
  first paint; `app/static/js/modules/phone/phone-mode.js` adds the behavior at the same width
  (`PhoneMode.init`, started by both `main.js` and the login path in `auth.js`).
- **Top:** the search bar alone on a black header. Search terms show as blue pills, each with ×
  (an exclusion struck through); the view chips (sort, date range, files, untagged) show as grey
  pills beside them; the count is at the right. Tapping the pills shows the text for typing, with
  the usual suggestions; leaving the field turns it back into pills. × drops one term and searches
  again (`phone-search-terms.js` splits a search into terms).
- **Rows:** notes as on the desktop, without tag chips; the expand arrow sits inside the row.
- **Hidden:** tabs, the floating buttons (≡, chat, scroll) and the AI chat.
- **Bottom bar:** ☰ at the left opens the menu sheet; a black ＋ at the right opens capture;
  between them "Read-only" while a note shows its tags. Floating notices and reminders sit above it.

## Tapping
- A tap on a note never selects or edits it. It shows the note's **own** tags as pills under it
  (not inherited ones) and expands it if it has children; a second tap hides the pills and leaves
  it expanded (the arrow collapses it).
- Tapping a tag pill searches for it. A temporary developer switch picks what it does: replace the
  search (default) or narrow it (`localStorage` key `metalist.dev.phoneTagPills` = `narrow`).
- A long press opens no menu: the menus offer editing, which the phone never does.
- **Back:** a search becomes a history step once it has stopped changing for a second, or at once
  before a pill starts a new search; back restores the previous search.

## Menu sheet (☰)
Sort order (Normal, Created, then Updated · A–Z · Size), Reverse, Date Range ›, Notes with
Files ›, Untagged Notes, then **Lock** and **Sign Out**. Picking an option applies it and closes
the sheet; tapping outside closes it. Lock and Sign Out both log out: each vault has its own
address, so the vault stays picked and getting back in is just the password.

## Capture (＋)
A full-screen sheet: the text box (focused), "Tags (optional)" where typed tags become pills, with
suggestions from the vault's tags, and Cancel · Save at the lower right (the shared dialog row,
`modals/action-row.js`). Save is dimmed, its tooltip saying "Write the note first.", until the note
has text. Save creates a new note at
the top with the text and the tags; with no tags it is tagged **`@inbox`**, a reserved meta tag
(meta tags are not inherited, so search `@inbox` for what to sort).

## Logging in on a phone
- The vault's HTTPS address on the local network, e.g. `https://10.0.0.31:9443` (each vault has
  its own port). The certificate is MetaList's own: Safari warns once; after accepting, refresh.
- The login form carries the vault's name as a hidden username, so iOS saves one password per
  vault and fills it in.
- The manifest (`app/static/manifest.json`) is `display: standalone`, so Add to Home Screen opens
  MetaList full screen with its icon (desktop Chrome may offer to install it too).

## Tests
`BROWSER_TEST_SUITE=phone npm run test:browser` (`scripts/browser-phone-regressions.mjs`) at
iPhone size with touch: first paint, layout, search pills, tapping, tag pills both ways, back, the
sheet, capture and `@inbox`, no long-press menu, Lock and Sign Out. Unit: `phone_search_terms`,
`phone_startup`, and the login form's username (`test_login_page_first_paint.py`).
