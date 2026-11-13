# Password Audit

**Status:** Agreed with the maintainer 2026-11-12 (brainstorm; §7 answered the same day). Ready to build.

The goal: one command that checks every password in the vault, says in one line how they stand, and leads straight to each one that needs attention, with a safe way to replace it.

---

## 1. Where it lives

- **`Password Audit…` in the command palette only.** Not in a right-click menu: it is not done often enough (the maintainer, 2026-11-12).
- It starts checking the moment it opens. Nothing to configure first.

## 2. What it checks

Every password in the vault: whole `@password` notes, and each `((…))` region of a note tagged `((@password))` (`help-meta-tags.md`). The check runs on the server, which holds the unlocked vault and already uses zxcvbn (`app/services/auth_service.py`), so passwords are not sent to the browser in bulk.

- **Weak:** a zxcvbn score below 3, or below 4, as chosen in the panel (§7, question 4). The note's username and words are passed as zxcvbn's user inputs, so a password made of them (`Lisbon2024` in a note about Lisbon) scores as weak.
- **Reused:** the same password in more than one place, compared exactly. Often worse than weak: one breach opens every place it is used.
- **Old:** its note unchanged for over a year (§7, question 2).
- **Leaked, opt-in:** checked against Have I Been Pwned's range API (k-anonymity). Only the first 5 hex characters of each password's SHA-1 hash leave the computer, never the password or its whole hash; the comparison happens here. Off unless turned on, because it is a request to an outside service.

## 3. What it shows

- **One summary line:** `42 passwords: 3 leaked, 5 reused, 7 weak, 12 old`. A password can be in more than one group.
- **A group each,** in that order: leaked, reused, weak, old. Each row names its note by its first line and tags, never the password itself.
- **`Go to`** opens the top-level note the password is in, as following a link to it does: a `Source note` view with the back chip, the notes folded or unfolded as they were. The panel stays open where it is, to pick the next one; back steps through each view to the search (the maintainer, 2026-11-12, changed from a floating window, which showed only the hidden password).
- Running it again re-checks everything.
- **A password kept after a replacement** (§4) is listed in a group of its own, `Replaced, to delete`, never as weak or reused: it is a reminder to delete it once the new one works.

## 4. Replacing a password

A new password in MetaList does not change it on the website. Replacing every weak one at once would leave notes holding passwords that no longer work. So replacing is one password at a time, guided (the maintainer, 2026-11-12):

1. `Replace…` on a row generates a strong password, with the generator's defaults (`Generate Random Password…`).
2. Copy it, and change the password on the site.
3. Then `Save`: the note gets the new password, and the old one goes into a new `@password` note under it, first line `Replaced 2026-11-12`, hidden like any password. Delete that note once the new password works (§7, question 3).

## 4a. The reminder

Agreed with the maintainer 2026-11-12. A card in the notice stack, made as the backup reminder is: `Time to check your passwords: the last audit was 4 months ago.` with `Audit Now` and `×`.

- **Only when the vault holds a password** (an `@password` note or a `((@password))` region; ones kept after a replacement don't count).
- **`Password Audit Reminder`**, a palette setting per vault: Off, Monthly, Every 3 months (the default), Every 6 months, Yearly.
- **Never audited: due at once.** Otherwise due once the last audit is older than the period; opening the audit counts as running it and restarts it. While the last audit left passwords leaked, reused or weak, it is due after a month at most and says how many: `5 still need attention.` (the maintainer, 2026-11-12: not waiting for zero, which would nag, nor resetting the full period on a glance).
- **`×` hides it for a week**, then it comes back if still due.

## 5. Privacy

- The audit's results name notes by their first line and tags, as the rest of MetaList does. No password appears in the dialog, in logs, in problem reports or in anything sent to the AI.
- The leaked check sends hash prefixes only, and only when turned on.

## 6. Invariants

1. No password, and no whole hash of one, leaves the computer.
2. Nothing is replaced without the person saving it, one password at a time.
3. The password a note held before a replacement can be recovered.

## 7. Decided (the maintainer, 2026-11-12)

1. **A movable panel, not a dialog.** It can be dragged aside and the list stays usable behind it, so a note opened with `Go to` can be read and edited with the panel still open (z-index 2400, below floating notes).
2. **"Old" is the note's last change.** No schema change. Editing anything else in the note restarts the count; tracking each password's own date would need a stored date per password (a version bump and migration, AGENTS.md) and was not wanted.
3. **The replaced password goes into a note under it** (§4), not only into undo history, which may not survive a restart.
4. **The weak threshold is chosen in the panel:** below 3 or below 4, remembered per vault. Switching it regroups from the scores the audit already has, asking the server nothing, leaks least of all; only turning the leak check on asks Have I Been Pwned (the maintainer, 2026-11-12). The vault's own password must score 4 (`PASSWORD_MIN_ZXCVBN_SCORE`, `app/config.py`); below 3 is the usual line for site passwords. Which one it starts on is the builder's to propose.
