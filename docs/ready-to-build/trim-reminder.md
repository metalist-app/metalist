# Trim reminder, and Trim that never breaks undo

**Status:** Agreed with the maintainer 2026-10-27. Small; ready to build. §1 is agreed; the details in §2 are proposed, so adjust any that read badly.

Written from a read-only look at the code, without running it. Check every reference before relying on it; build only what's missing.

---

## 0. Background

- Removing a note's last reference to a file never deletes the file. The only cleanup is the manual `Trim Unused Files…` (`trim_unused_files` in `app/services/file_storage.py`). It deletes every file row no note's content references, all at once.
- **Every backup is the whole archive**, notes and all files, and that stays so: people must never have to get the choice of what to back up right. (A future backup that MetaList runs to cloud storage itself could upload each file once; that's not today.) So files nothing uses ride along in every backup, and backups grow for nothing until someone trims.
- Fix in the docs: `docs/ui/command-palette.md` calls `Trim Unused Files…` "the only automatic cleanup path". It's manual.

## 1. The reminder (agreed)

- Like **Backup Reminder**: once the files no note references add up to **10 MB**, a card offers to trim them.
- **Trimming stays a person's decision.** The card only asks; nothing is deleted automatically.

## 2. Details (proposed)

- **The card:** same style and corner as the backup reminder. `12 MB of files aren't used by any note.` with **`Trim Unused Files…`**, which opens the usual confirmation, and a dismiss.
- **The confirmation says what goes:** `Delete 4 unused files (12 MB)? This cannot be undone.`
- **After a dismiss,** the card comes back only once another 10 MB has piled up, so it never nags.
- **Per vault,** on by default, with an off switch next to `Backup Reminder` in the command palette.
- **The total** is the stored size of files no note's content references. Work it out cheaply, from the file registry and the existing reference index, not by rereading every note on every save.

## 3. Trim must not break undo or the copied note

Two holes are likely. Please confirm each with a test first:
1. **Undo:** delete a note that has an attachment, trim, then ⌘Z. The note comes back, but its file is gone ("missing reference").
2. **The copied note:** copy or cut a note with an attachment, trim, then paste. The paste points to a deleted file.

**Rule:** Trim never deletes a file that a ⌘Z or a paste could bring back. Either skip files referenced by the undo history (every open tab) and by the copied note, or clear those first and say so in the confirmation. Your choice; skipping is kinder.

## 4. Tests

- Unused files at 9 MB show no card; at 10 MB they show it, with the right total.
- Dismiss at 12 MB: no card at 15 MB, a card again at 22 MB.
- `Trim Unused Files…` from the card deletes those files, and the card goes away.
- Off: no card at any size.
- Delete a note with an attachment, trim, ⌘Z: the attachment still renders.
- Copy a note with an attachment, delete the original, trim, paste: the attachment renders.

## 5. Checked 2026-10-27 (filed from the inbox)

- Confirmed: `trim_unused_files` in `app/services/file_storage.py`; the Backup Reminder card to follow (`docs/ui/command-palette.md`).
- **Fixed on filing:** `docs/ui/command-palette.md` called `Trim Unused Files…` "the only automatic cleanup path"; it is the only cleanup path, and a manual one.
- Not built: the reminder; §3's undo and copied-note holes are unconfirmed (confirm each with a test first, as §3 asks).
- **Open (§2, marked proposed):** the card's wording and corner, the confirmation's wording, the 10 MB step after a dismiss, and the off switch beside Backup Reminder.
