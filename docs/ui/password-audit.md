# Password Audit

One command that checks every password in the vault, says in one line how they stand, and leads straight to each one that needs attention, with a safe way to replace it. Agreed with the maintainer 2026-11-12; built on `feature/password-audit`.

## Where it lives

- **`Password Audit…` in the command palette only.** Not in a right-click menu: it is not done often enough.
- It starts checking the moment it opens. Nothing to configure first.
- **A movable panel, not a dialog** (z-index 2400, below floating notes). It can be dragged aside and the list stays usable behind it, so a note opened with `Go to` can be read and edited with the panel still open. Clicks inside it are exempt from the list's own click handling (`mouse-events.js`).

## What it checks

Every password in the vault: whole `@password` notes, and each `((…))` region of a note tagged `((@password))` (`help-meta-tags.md`). The check runs on the server, which holds the unlocked vault and already uses zxcvbn, so passwords are not sent to the browser in bulk.

- **Weak:** a zxcvbn score below 3, or below 4, as chosen in the panel and remembered per vault (`pref.password_audit.weak_below`, 3 to start). The note's username and words are zxcvbn's user inputs, so a password made of them (`Lisbon2024` in a note about Lisbon) scores as weak. The vault's own password must score 4 (`PASSWORD_MIN_ZXCVBN_SCORE`); below 3 is the usual line for site passwords.
- **Reused:** the same password in more than one place, compared exactly. Often worse than weak: one breach opens every place it is used.
- **Old:** its note unchanged for over a year. This is the note's last change, so editing anything else in the note restarts the count; a date per password would need a schema change and was not wanted.
- **Leaked, opt-in:** `Check leaks` in the panel, off by default, remembered per vault (`pref.password_audit.check_leaks`). Asks Have I Been Pwned's range API with hash prefixes only; see "Outbound Leak Checks" in `docs/security/README.md`. An unreachable service shows `(leak check unavailable)` in the summary and the rest is still checked.

## What it shows

- **One summary line:** `42 passwords: 3 leaked, 5 reused, 7 weak, 12 old`. A password can be in more than one group.
- **A group each,** in that order: leaked, reused, weak, old. Each row names its note by its first line and tags, never the password itself.
- **`Go to`** opens the top-level note the password is in, as following a link to it does: a `Source note` view with the back chip, the notes folded or unfolded as they were. The panel stays open where it is, to pick the next one; back steps through each view to the search. (Changed 2026-11-12 from a floating window, which showed only the hidden password.)
- **Switching the threshold** regroups from the scores the audit already has, asking the server nothing. Turning `Check leaks` off drops its group; only turning it on asks Have I Been Pwned.
- Running it again re-checks everything.

## While it is open

Agreed with the maintainer 2026-11-13 ("keep track of its state when it opened and then just check differences"). The panel updates itself as passwords are edited, added or deleted, here, in another tab or on another computer:

- **What sets it off:** an answer here that carries a new update id (`api-client.js`), or a new `notes_revision` in the status the app polls every few seconds (`polling-service.js`); both go through `notes-change-signal.js`. It waits 2 seconds after the last change, so a password is checked once typing pauses.
- **Only what changed is checked:** the server remembers each password's score and each Have I Been Pwned answer from the audit that opened the panel (`SensitiveMemo`s in `app/usecases/password_audit.py`, forgotten when the panel opens again and when the vault locks). An update scores only passwords that are new or changed and asks only about new ones; reused and old are worked out again over every password, since one edit can make another note's password reused.
- **On screen:** the panel is drawn again in place: no `Checking…`, nothing highlighted, the panel where it was, the list's scroll and the focused button kept. Rows join, leave or change groups; the summary follows.
- **Replace… follows its password** by a `passwordId` (a keyed hash; the key never leaves the server), so editing the note around it keeps the form and the new password, and Save puts it where the password is now. Save refuses any other password. If the password left its note, the form stays at the top, `This password is no longer in its note.`, with the new password to copy, since it may already be in use on the site.
- **A password kept after a replacement** is listed in a group of its own, `Replaced, to delete`, never as weak or reused: a reminder to delete it once the new one works.

## Replacing a password

A new password in MetaList does not change it on the website. Replacing every weak one at once would leave notes holding passwords that no longer work. So replacing is one password at a time, guided:

1. `Replace…` on a row generates a strong password, with the generator's defaults (`Generate Random Password…`).
2. Copy it, and change the password on the site.
3. Then `Save`: the note gets the new password, and the old one goes into a new `@password` note under it, first line `Replaced YYYY-MM-DD: ((old))`, hidden like any password. Both happen as one undo step. Delete that note once the new password works. The old password goes into a note, not only into undo history, which may not survive a restart.

## The reminder

A card in the notice stack, made as the backup reminder is: `Time to check your passwords: the last audit was 4 months ago.` with `Audit Now` and `×`.

- **Only when the vault holds a password** (an `@password` note or a `((@password))` region; ones kept after a replacement don't count).
- **`Password Audit Reminder`**, a palette setting per vault (`pref.password_audit_reminder`): Off, Monthly, Every 3 months (the default), Every 6 months, Yearly.
- **Never audited: due at once** (`they have never been audited`). Otherwise due once the last audit (`pref.password_audit.last_audited_at`) is older than the period; opening the audit counts as running it and restarts it. While the last audit left passwords leaked, reused or weak (`pref.password_audit.open_issues`), it is due after a month at most and says how many: `5 still need attention.` Not waiting for zero, which would nag, nor resetting the full period on a glance.
- **`×` hides it for a week** (`pref.password_audit_reminder_hidden_until`), then it comes back if still due.
- It is checked when the app opens, when the tab comes back, when a dialog or the menu closes, and on the first click or key after a while; it never polls.

## Privacy

- Results name notes by their first line and tags, as the rest of MetaList does. No password appears in the panel, in logs, in problem reports or in anything sent to the AI.
- The leak check sends hash prefixes only, and only when turned on.

## Invariants

1. No password, and no whole hash of one, leaves the computer.
2. Nothing is replaced without the person saving it, one password at a time.
3. The password a note held before a replacement can be recovered.

## Code

- Server: `app/usecases/password_audit.py` (finding, scoring, the leak check, `CmdReplacePassword`); `scoped_password_regions` in `app/services/content_formatting.py`; routes `POST /api/notes/password-audit`, `GET /api/notes/password-count`, `POST /api/notes/{id}/password-replace` in `app/api/routes/notes.py`.
- Client: `app/static/js/modules/password-audit/` (`password-audit-panel.js`, `password-audit-reminder.js`, `password-audit-reminder-schedule.js`); opened from `command-palette-controller.js`.
- Tests: `tests/unit/test_password_audit.py`, `tests/unit/password_audit_reminder_schedule.test.mjs`; browser suite `password-audit` (`scripts/browser-password-audit-regressions.mjs`).
