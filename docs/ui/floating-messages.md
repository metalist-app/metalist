# Floating messages

News, errors and lasting conditions float above the page as cards; nothing on the page moves for them (`docs/ready-to-build/errors-and-status-rule.md` §2.2, placements 1 and 2; agreed case by case 2026-10-24). Code: `app/static/js/modules/floating-messages.js`; every `ErrorHandler.show*Banner` call goes through it. Test: `scripts/browser-floating-message-regressions.mjs` (`floating-messages` suite).

## Where

- Upper-right corner, just left of the floating buttons (≡, chat, scroll), the first card level with the first button. With the chat shown they follow the buttons beside it (`--global-controls-right` in `main.css`).
- On the phone (under 640 px): just under the search header, the page's width less its 8 px side padding.
- A new card goes below the others; when one leaves, the ones below move up. They fade in and out instead of sliding, so a card stands where it stays.
- Nothing shifts: no scroll, no layout change, and focus and the caret stay where they were (pressing a card's × does not take focus).
- The bottom-right notices (a new release, the backup reminder) are separate and stay where they are.

## How long

- News leaves after 4 s, or longer for a long message (about 17 characters a second), at most 10 s.
- An error is a red card with × and stays 10 s, until step 5 of the dialog conventions turns errors that need the user into dialogs.
- Hovering a card pauses its timer; moving away resumes it where it paused.
- A caller's own duration only says passing (any number above 0) or lasting (0); the time follows the rule above.

## Lasting: the connection

- A lost connection shows "Not saved, reconnecting…" for as long as it lasts, with no ×; editing is locked meanwhile (`docs/ui/state-handling.md`). Its tooltip gives the reason.
- When the connection is back, "Reconnected" takes its place, then leaves like news.
- Escalation to a dialog after `STATUS_ESCALATE_SECONDS` comes with step 5.

## Recent Messages

- `Recent Messages` in the command palette lists the last 20 messages, newest first, each with the time it showed (the connection card too).
- Kept in this page's memory only; signing out or reloading forgets them.
