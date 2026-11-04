# Floating messages

News, errors and lasting conditions float above the page as cards; nothing on the page moves for them (`docs/ui/modals.md`, "Errors and status"; agreed case by case 2026-10-24). Code: `app/static/js/modules/floating-messages.js`; every `ErrorHandler.show*Banner` call goes through it. Test: `scripts/browser-floating-message-regressions.mjs` (`floating-messages` suite).

## Where

- Upper-right corner, just left of the floating buttons (≡, ↑, ↓), the first card level with the first button. With the chat shown they follow the buttons beside it (`--global-controls-right` in `main.css`).
- On the phone (under 640 px): just under the search header, the page's width less its 8 px side padding.
- A new card goes below the others; when one leaves, the ones below move up. They fade in and out instead of sliding, so a card stands where it stays.
- Nothing shifts: no scroll, no layout change, and focus and the caret stay where they were (pressing a card's × does not take focus).
- The bottom-right notices (a new release, the backup reminder) are separate and stay where they are.

## How long

- News leaves after 4 s, or longer for a long message (about 17 characters a second), at most 10 s.
- An error is a red card with × and stays 10 s, until step 5 of the dialog conventions turns errors that need the user into dialogs.
- Hovering a card pauses its timer; moving away resumes it where it paused.
- A caller's own duration only says passing (any number above 0) or lasting (0); the time follows the rule above.
- A card can offer one action, a small outlined button after its text (the spec's `action`, `{ label, onSelect }` or null). Pressing it closes the card and does the action; focus stays where it was. The first: **Undo** on "Moved to `Projects/`" after a note is dragged into a virtual folder, which closes as soon as the user does anything else (a key or a click), so it never undoes something else (`docs/ready-to-build/virtual-folders.md §4`).

## Lasting: the connection

- A lost connection shows "Not saved, reconnecting…" for as long as it lasts, with no ×; editing is locked meanwhile (`docs/ui/state-handling.md`). Its tooltip gives the reason.
- When the connection is back, "Reconnected" takes its place, then leaves like news.
- Still lost after `STATUS_ESCALATE_SECONDS` (30), it opens a dialog over the card: "MetaList can't reach its server. Changes can't be saved until it's back; MetaList keeps trying." It has no buttons and closes by itself once the connection is back (`FloatingMessages.escalateAfter` / `endEscalation`). The diagram editor's failed saves escalate the same way (`docs/ui/excalidraw.md`).

## Progress

- While a dialog's action runs, a lasting card says so ("Opening vault…", "Creating vault…", "Preparing vault rename…", "Saving vault ports…", "Deleting vault…", "Restoring backup…", "Choosing a backup folder…", "Saving idle timeout…") and leaves when it ends (`FloatingMessages.showProgress` / `end`). The dialog writes no status line, its buttons stay dimmed, and it cannot be closed until the action ends. Progress cards are not kept for Recent Messages.
- Loading placeholders ("Loading vaults…") stay in their dialogs: they hold the place of what is loading. So do dialogs whose content is the progress (the password's "Encrypting notes…", the link-title retry, Version Info's update section) and Edit Tag Relationships' "Updating search index…" overlay.
- Test: `scripts/browser-progress-card-regressions.mjs` (`progress-cards` suite).

## Background work

Decided 2026-11-02 (the maintainer): "if there's stuff being computed in the background, I would like the user to have some awareness of that." Work the server does beside the user's shows as a lasting card per piece of work: its label, how far it got, how long it has run and, once some is done, about how long is left at that pace, over a bar that fills ("Reading document text: 3 of 7"; a moving bar while the total isn't known yet). The times stand just above the bar, without words: the time spent at its left ("0:12") and the time left at its right after a `~` ("~0:16", none before an estimate); their tooltips say what they are (2026-11-03). The card keeps one width (420 px; the page's width on the phone): sized to its text, it grew and shrank as the numbers changed. The import's own bar keeps them in its line ("· 0:12 so far, about 0:16 left"). It leaves when the work is done. Work done within a second shows no card, so nothing flickers. The page asks once as it loads, then with each status poll (2026-11-03: work started with a restart showed no card until the first poll, 5 seconds in).

- Where: in the window's lower left, just above the folders' pull tab, and clicks go through it; at the top right it covered the search bar and the menu (the maintainer, 2026-11-02). It stays there whether the folders show or not, and never covers the tab (2026-11-03). On the phone, along the bottom.
- The server lists its work as it goes (`app/services/background_work.py`, `GET /background-work`: key, label, done, total, elapsed seconds). The page asks with every status poll, every half second while there is work, and right after the user started some (an import, dropped files) (`background-work-cards.js`; the wording in `background-work-text.js`; the card, `FloatingMessages.showWorkProgress`).
- Today: **Reading document text** (a PDF's, Word document's or RTF's text kept for search, after an import or a drop and at login for any not read yet or read by an older reader), **Updating previews** (preview notes made or made again by a newer version, after login: `docs/ready-to-build/folder-import-and-file-previews.md`, "Text and preview versions"), and **Importing files**, shown on the Import walkthrough's own bar while it is open (no card meanwhile).
- What shows on the page comes first (the maintainer, 2026-11-02): reading document text waits until an import has finished, and runs in a process of its own at low priority (`file_text_worker.py`). In the server's process it had starved every request: a 4 KB image waited 10 to 15 seconds behind 15 MB of PDFs.
- Resumable: each PDF's text is kept as soon as it is read, so after a restart only the PDFs not read yet are read (a folder may hold 300).
- Tests: `tests/unit/test_background_work.py`, `tests/unit/test_file_text_search.py`, `tests/unit/background_work_cards.test.mjs`, `scripts/browser-background-work-regressions.mjs` (`background-work` suite).

## Recent Messages

- `Recent Messages` in the command palette lists the last 20 messages, newest first, each with the time it showed (the connection card too).
- Kept in this page's memory only; signing out or reloading forgets them.
