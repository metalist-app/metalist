# Importing the same source again

**Status:** Agreed with the maintainer 2026-11-02. Ready to build, apart from §7. Applies to every import source: Obsidian vault, Markdown folder, Any folder, and browser bookmarks (`bookmark-import`, handed over the same day). Replaces the launch plan's "Importing the same vault twice" (`docs/ready-to-build/import-export-launch.md` §5: "import as a copy" or "cancel", with a fingerprint of each import).

Written from a read-only look at the repo; filed from `docs/inbox/` on 2026-11-02, with the references checked (§9).

---

## 0. Today (from the code)

- Nothing handles a second import. The prefix folder step offers to add to an existing folder (`docs/ready-to-build/import-prefix-folder.md` §2), so a second import of the same vault brings every note in again beside its first copy.
- Every imported note carries one import tag, `imported:source={source}:at={time}` (`app/services/obsidian_import/notes.py`, `SOURCE_TAG_FORMAT`). Its values inherit through children (`docs/ui/search-semantics.md`).
- A note carries each tag at most once; the same tag twice is planned, not built (`docs/future-plans/same-tag-twice.md`).

## 1. The rule: an import never overwrites or deletes

The maintainer: "an immutable philosophy and never overwrite or delete things", with ways for users to find duplicates and deal with them themselves.

- **An import only adds.** It never changes what a note says and never deletes a note, whatever happened in the source.
- **The one thing it may do to an existing note** is add a value to that note's import tag (§4).
- Editing and deleting by hand are unchanged; this is about imports.
- Considered and dropped: overwriting changed items. It could lose edits made in MetaList, and a Markdown file split into several notes can't be replaced in place safely.

## 2. Recognizing an item already imported

- **Each imported note keeps its origin:** a file's path within the vault or folder, or a bookmark's address. Every note made from one file keeps that file's path.
- **And what it was:** a fingerprint of the file's content as imported; for a bookmark, its title and folders.
- **Matching is against earlier imports of the same source:** the same vault or folder (its path where the server knows it, else its name), or any earlier bookmark import.
- The Summary names the earlier import it matched ("imported 2026-11-01 09:10").
- A file renamed or moved in the source has a new path, so it counts as new. Accepted.

## 3. What a second import does

| Item | What happens |
|---|---|
| **New** (no match) | Comes in as usual |
| **Unchanged** | Skipped. Nothing is touched |
| **Changed** (content differs; a bookmark's title or folders differ) | **Comes in as a copy:** new notes beside the old ones, carrying the new import's tag. The old ones are marked `replaced` (§4) |
| **Gone from the source** | Stays. Marked `removed` (§4) |

- **The Summary shows the counts first:** "1,300 files: 60 new, 12 changed (come in as copies), 1,228 unchanged (skipped), 5 no longer in the folder."
- **The changed items' list opens,** as a kind does in the file-type checklist, each with a box, ticked at first; unticking one leaves it out of this import.
- The prefix folder step's "add to it" now means this: only new and changed items come in.

## 4. The marks

- **The old version of a changed item:** its import tag gains `replaced=<the new import's time>`, for example `imported:source=obsidian:at=…:replaced=…`.
- **An item gone from the source:** its import tag gains `removed=<the new import's time>`.
- **A value, not a second tag,** because a note carries each tag once. It touches only the outdated notes, not every unchanged one.
- On a file split into several notes, the mark goes wherever that file's import tag is.

## 5. Cleaning up

- **One search finds the outdated versions:** notes whose import tag has a `replaced` value. The user selects and deletes them by hand, or keeps them to compare.
- **Another finds what left the source:** the `removed` value.
- *Check* the exact search syntax for "this tag has this value at all", and make sure both searches work. If they need anything new in search, say so in the doc rather than inventing syntax.
- Not part of this: a "find duplicates" view pairing each replaced note with its newer copy. Possibly later.

## 6. Invariants

1. An import never changes what a note says and never deletes a note.
2. The only change an import makes to an existing note is adding `replaced` or `removed` to its import tag.
3. An unchanged item is never imported twice.
4. A changed item always arrives as new notes; its old version stays until the user deletes it.
5. The Summary shows new, changed, unchanged and removed counts before anything happens.

## 7. Still open (your call, recorded in the doc)

- **Where the origin and fingerprint live:** as values on the import tag, or out of sight in a record of each import. A file path may not be a valid tag value.
- **How a hosted import recognizes the same folder:** the browser gives the folder's name, not its path. Suggested: by name, with the match shown on the Summary.

## 8. Done when

1. A second import of an unchanged vault, folder or bookmarks file adds no notes and changes none.
2. Changed files and bookmarks come in as copies, and their old versions carry `replaced`; items gone from the source carry `removed`; no note's content changes.
3. The Summary shows the four counts, and the changed list can be opened and unticked.
4. Both cleanup searches find exactly the marked notes.
5. `docs/ready-to-build/import-export-launch.md` §5 points to this in place of "import as a copy or cancel"; tests cover new, unchanged, changed, removed and a renamed file.

## 9. Checked against the code (2026-11-02, when filed)

The references in §0 hold: `SOURCE_TAG_FORMAT` (`imported:source={source}:at={at}`) in `notes.py`, with the time to the minute (`SOURCE_TAG_TIME_FORMAT`, `%Y-%m-%dT%H:%M`); `docs/future-plans/same-tag-twice.md` exists. The prefix folder's "add to it" is built: `ImportFolderRequest.addToExisting` (`imports.py`), checked in `import_obsidian_vault.py`.

Found:

- **§5's searches need nothing new.** `imported:replaced` finds notes whose import tag has a `replaced` value, any value (`docs/ui/search-semantics.md`, `jogging:miles`), and likewise `imported:removed`. Checked: `imported:source=obsidian:at=2026-11-02T08:46:replaced=2026-11-03T09:00` reads as three values, `replaced` a date and time.
- **Values inherit through children,** so `imported:replaced` also finds every note under a replaced file's notes. For a file split into several notes that is the whole file, as §4 wants.
- **The import tag can't tell two imports apart on its own:** it holds no vault path, and its time is to the minute, so two imports in one minute share it. Recognizing "the same vault" (§2) needs the origin recorded somewhere; that is §7's first question.
- **A hosted import of a folder isn't built** (`folder-import-and-file-previews.md` §4), so §7's second question waits for it.
- **Open, not in the note:** adding `replaced` or `removed` changes the note's tags. *Ask* whether that should count as a change to the note (its modified time, a sort by modified, sync), or leave the note's dates as they were.
