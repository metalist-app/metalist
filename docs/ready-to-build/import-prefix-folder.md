# A prefix folder for every import

**Status:** Agreed with the maintainer 2026-11-01. Ready to build. Applies to every folder import: an Obsidian vault, a Markdown folder, and a folder of any files (`folder-import-and-file-previews`, handed over the same day). Builds on folder tags ending in `/` (`virtual-folders`, the same day).

Written from a read-only look at the repo; filed from `docs/inbox/` on 2026-11-01, with the references checked (§6).

---

## 0. Today (from the code)

- Every imported note gets a source tag, `imported:source={source}:at={time}` (`app/services/obsidian_import/notes.py`, `SOURCE_TAG_FORMAT`).
- Each file's folder becomes a folder tag (`folder_tag_for`); **files at the top of the vault get none**, so they're the only imported notes outside the folder structure.

## 1. The rule

The import walkthrough asks for a **prefix folder** that everything goes under. Every folder tag the import writes starts with it: a vault called `My Vault` gives `My-Vault/` to files at its top and `My-Vault/Projects/Client-A/` below. The whole import is then one folder: one place to find it, move it or rename it.

## 2. The walkthrough step

- **Default: the vault's or folder's name,** made a valid tag the way the import makes folder tags (spaces become dashes).
- **Editable,** and it may be a path (`Imports/Obsidian/`).
- **Blank means no prefix:** top-level files get no folder tag, as today.
- **If the folder already exists** (the same vault imported twice, say), the step says so, with a checkbox, ticked at first, to add to it: the notes go in together. Unticked, the user changes the name (decided 2026-11-01).
- **A path is cleaned up part by part** the way folder names are (spaces become dashes, disallowed characters removed), so every part is a valid tag part (decided 2026-11-01).
- The summary before importing shows the prefix with the rest.

## 3. Not the source tag

The source tag stays as it is: it says where a note came from and when. The prefix says where the notes live.

## 4. Invariants

1. With a prefix, every imported note has a folder tag starting with it.
2. The user sees and can change the prefix before anything is imported.
3. The source tag is unaffected.

## 5. Done when

1. Every folder import has the prefix step, defaulting to the folder's name.
2. All folder tags, top-level files included, start with the prefix; a blank prefix behaves as today.
3. An existing folder of that name is announced, with keep or rename.
4. `docs/ready-to-build/import-export-launch.md` and `docs/ready-to-build/obsidian-mapping.md` (rows B3 and B4) describe it; tests cover the default, an edited path, a blank prefix and an existing folder.

## 6. Checked against the code (2026-11-01, when filed)

The references in §0 hold: `SOURCE_TAG_FORMAT` and `folder_tag_for` are in `app/services/obsidian_import/notes.py`; `_folder_tag` gives `""` at the vault's top. Each folder name is made a tag part by `_tag_text` (spaces become dashes), with renames and dropped names reported, which is what §2's default should reuse.

Found:

- **Builds on `feature/virtual-folders`:** folder tags end in `/` only on that branch (`_folder_tag`), and "the folder already exists" (§2) is easiest answered by its `all_folder_tags()` (`app/services/virtual_folders.py`), which reads the search index's tag counts.
- **Where the step goes:** the import wizard's steps are in `app/static/js/modules/wizard/import-wizard-steps.js`, shared by the import wizard and the new vault wizard; the prefix travels with the other choices (`source`, `folderPath`, `split`, `content`) to `ImportFolderRequest` (`imports.py`).
- **`obsidian-mapping.md` B3** still says the folder tag is "to become `Projects/Client-A/`"; on the branch it already is.

### Decided (the maintainer, 2026-11-01)

- An existing folder of that name: adding to it is the default, as a ticked checkbox the user can untick (§2).
- A prefix given as a path (`Imports/Obsidian/`) is cleaned up part by part as folder names are (`_tag_text`), since only that makes it a valid tag (§2).
