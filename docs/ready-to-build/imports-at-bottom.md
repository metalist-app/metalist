# Imports go to the bottom of the list

**Status:** Agreed with the maintainer 2026-11-07. Ready to build. Changes where imports place notes (`docs/ready-to-build/import-prefix-folder.md`, `bookmark-import.md`, and the folder import).

Written from a read-only look at the repo. Check the code references before relying on them.

---

## 0. Today (from the code)

- Imports put their notes at the top of the list, in the source's order (`app/usecases/import_obsidian_vault.py` and `app/usecases/import_bookmarks.py`, module docstrings).
- When the walkthrough finishes it opens a new search context of the imported notes and shows the folder tree (`command-palette-controller.js`, `afterImport`); at the limit of search contexts it refreshes the list as it is.
- No screen says the import is done; the wizard closes on the imported notes (`import-wizard-steps.js`).
- Where the old-MetaList import (`legacy-import-modal.js`) places notes: check.

## 1. The problem

Someone who works with nothing in the search treats the whole list as their working list. After an import, its notes sat on top of it, and for a day or two it looked to them as if their own notes had disappeared.

## 2. The rule

- **An import's notes go to the bottom of the list,** after every existing root note, in the source's order as today.
- **Every walkthrough import:** an Obsidian vault, any folder, Markdown, bookmarks. Importing again too: new and changed items go to the bottom.
- **Single drops stay at the top:** a file or link dropped on the notes column is something added now. A folder dropped on the column is an import, so it goes to the bottom.
- **Why the bottom:** the top of the list is what the person is working on now; an import is material from elsewhere, usually older. Nobody's own notes move.
- If the old-MetaList import also puts notes at the top, it follows the same rule.

## 3. Found by its folder, not its place

Every import has its own folder by default (the prefix folder), and the import turns the folder tree on; that's where people look for it. The search context the walkthrough opens is unchanged.

## 4. Said, not asked

- **No checkbox or choice** for top or bottom (ask only what applies).
- **The Summary says it,** before Import: "The notes go into `My-Vault/`, at the bottom of your list."
- **A short floating message when it finishes** (proposed): "Imported 340 notes into `My-Vault/`." With no prefix folder: "… at the bottom of your list." Not a done screen.

## 5. Existing vaults

No conversion. An earlier import still at the top can be moved by hand.

## 6. Invariants

1. An import never moves or pushes down the person's own notes at the top of the list.
2. An import keeps the source's order within itself.
3. Where an import went is told, never asked.

## 7. Done when

1. Every walkthrough import, and importing again, adds its notes after the last existing root note, in the source's order.
2. Single file and link drops on the column still land at the top.
3. The Summary and the finish message say where the notes went.
4. The import docs say so; tests cover an import into a vault with notes, an empty vault, importing again, and a single drop.

## 8. Checked 2026-11-07 (filed from the inbox)

Filed as ready to build: most of it was built the same day (`082eacb8`, from the maintainer's request in a session), the rest is not.

- **Built:** an import of several notes goes after the list's last root note, in the source's order (`app/usecases/import_obsidian_vault.py`, `root_records`; Import… for an Obsidian vault, Markdown or any folder, a dropped folder, bookmarks through `import_bookmarks.py`). Import… still opens its own search context; a dropped folder stays in its context and scrolls to the first imported note. Tests: `tests/unit/test_obsidian_import.py`. Documented in `docs/ui/command-palette.md` (Import…) and the help (`help-menus.md`).
- **Different from §2:** the rule built is by count, as the maintainer asked ("unless they're imported one at a time"): one imported note goes at the top, several at the bottom. So a walkthrough import or a dropped folder that brings in a single note goes at the top, where §2 puts every walkthrough import and every dropped folder at the bottom. Single file and link drops (not imports) are unchanged.
- **The old-MetaList import** is offered only to an empty vault (`app/api/routes/legacy_import.py`, a vault with notes is never offered it) and installs a whole namespace, so there is no list for it to go above; nothing to change.
- **Importing again:** an import only adds (bookmarks bring everything in again under a new import tag; `import_obsidian_vault.py` updates nothing in place), so "new and changed items go to the bottom" is the same as every import going to the bottom.
- **The tree after an import (§0, §3):** since folder contexts (2026-11-07, `docs/ready-to-build/virtual-folders.md`), an import no longer shows the tree: it opens its own plain search, and the folders tab opens a folder context to find the import's folder.
- **Not built:** §4's Summary line ("… at the bottom of your list", `import-wizard-steps.js`, `importPreviewHtml` and `bookmarksPreviewHtml`, which say only "Everything goes into the folder …" today) and the floating message when it finishes.
- **Open, for the maintainer:**
  1. Keep the count rule (one note at the top), or put every walkthrough import and dropped folder at the bottom, even a single note, as §2 says?
  2. Build §4's Summary line and finish message now?
