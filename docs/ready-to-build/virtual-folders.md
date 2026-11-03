# Virtual folders from tags (experiment)

**Status:** Agreed with the maintainer 2026-11-01. **An experiment:** the maintainer will try it for a few hours and may drop it. Ready to build behind a menu toggle, **Virtual Folders**: off by default, turned on by an import (decided 2026-11-01). The folder-tag convention in §1 is worth keeping even if the tree is dropped.

Written from a read-only look at the repo; filed from `docs/inbox/` on 2026-11-01, with the references checked (§10).

---

## First try (2026-11-01, branch `feature/virtual-folders`)
Built for the maintainer to try: §1's trailing slash in the import (`_folder_tag`), §2's tree
(`virtual-folders-service.js`, `app/api/routes/virtual_folders.py`, `app/services/virtual_folders.py`)
with the column moved right, §3's filter chip, and the toggle (palette: Show/Hide Virtual Folders;
an import turns it on). **Nothing is stored:** the toggle and each tab's filter live in the
server's memory (a restart turns the tree off), so dropping the branch leaves the database as it
was. The filter narrows the view, find and the current-view commands; exports and the AI read the
search alone. Not built yet: §4 drags, §5 renames, §6 New Folder, the new search-context icon.

## 0. Today (from the code)

- Tags may contain `/` and end with one; only a leading `/` is refused, since it opens a regex in rules (`tag-token.js` `isValidTagToken`; `app/services/tag_ontology.py` `_is_valid_tag_token`). *Check* that a trailing `/` survives the tag bar, search and suggestions.
- The Obsidian import gives each file its folder as a tag, `Projects/Client-A`, with no trailing slash (`app/services/obsidian_import/notes.py`, `folder_tag_for`). Obsidian's nested tags (`#a/b`) come in as `a/b`, so the two look identical.
- Search matches tags exactly, never by prefix (`docs/ui/search-semantics.md`, Tag Terms; `docs/ready-to-build/import-export-launch.md` §9 item 9). This stays.
- Tag rename exists in Edit Tag Relationships and updates rules mentioning the tag (`docs/design/ontology-rules-v1.md`).
- View-indicator chips (date range, Notes with files, Untagged, sort) sit in the search box with an `×` (`docs/ui/controls.md`).
- Clicking a link opens its note in the temporary reference-source context (`docs/ui/references.md`).

## 1. A tag ending in `/` is a folder

- `Projects/Client-A/` is the folder `Client-A` inside `Projects`. The path is only the tag's name; no rules are added.
- **The trailing slash makes it a folder;** `a/b` stays an ordinary tag.
- A parent folder exists if any folder tag below it does: `Projects/Client-A/` alone shows `Projects` with `Client-A` inside.
- **The Obsidian import writes folder tags with the trailing slash.** Update `folder_tag_for`, its tests, `docs/ready-to-build/import-export-launch.md` and `docs/ready-to-build/obsidian-mapping.md` (row B3). Nested tags unchanged.
- **Tags already imported without the slash:** no conversion (decided 2026-11-01: the maintainer re-imports their vaults once the import writes the slash). There are no outside users yet. No permanent alias.

## 2. The folder tree

- **The setting** (decided 2026-11-01): **Virtual Folders**, a menu toggle like the other views'. Off by default; an import turns it on, so the imported vault's folders show at once. Turning it off hides the tree; it stays off until turned on or another import.

- **Always visible in the left margin** while the setting is on and the current results contain folder tags. Desktop only: the side margins already hide on narrow windows. Nothing on the phone.
- **The notes column moves right to make room** (the maintainer, 2026-11-01): with Virtual Folders on, the column sits right of center instead of centered, giving the tree more width. It moves whenever the toggle is on, whether or not the current results have folders, so a search never shifts the column (`docs/ui/interaction-principles.md`: only the person's action changes the screen; turning the toggle on is that action). How far right, and what happens on windows too narrow for both, are agreed with the other on-screen cases before code.
- **Which folders:** those found among the current search's results; with an empty search, every folder.
- **Expands and collapses like a file explorer:** a folder lists its subfolders first, then its notes.
- **A folder's notes:** those carrying that folder tag themselves, each one line, drawn the way a link draws a note's first line (cut with `…`). Children that inherit the tag aren't listed; they come with their parent.
- **Clicking a note** opens it exactly as clicking a link to it does.
- An ordinary folder icon. The search-context trigger's stacked-folder icon changes, so the two don't read as one thing: **two stacked cards with a small magnifying glass on the front one** (saved searches you flip between; decided 2026-11-01 as a first try, to change later if it doesn't read). **Built 2026-11-02:** the search contexts have the cards and magnifier; the stacked folders are the virtual folders' (Show → Virtual Folders, and the pull tab that shows and hides the tree, a full-height panel whose width drags: `docs/ui/controls.md`, Pull tabs). The tree's heading reads Virtual Folders. **Folder counts under a search** (built 2026-11-02; the maintainer: a `(0)` read as an empty folder): a folder the search narrows shows the notes clicking it would show out of all it holds with no search, `(3/17)`, folders below it included; one whose notes all match shows plain `(17)`, as every folder does with no search. The top, `/`, does the same (`(54/1,240)`). A folder holding notes none of which match is dimmed (as a new folder is, without its italics) but stays in the tree, still clickable and a drop target: the search never adds or removes a folder. The count's tooltip says it in words ("3 of 17 notes match this search", "17 notes"). The server sends each folder's total beside its count (`noteTotals`, `folder_note_totals` in `app/services/virtual_folders.py`, cached apart from the search's counts so neither evicts the other); `countHtml` and `.is-unmatched` in `virtual-folders-service.js` and `main.css`. Tests: `tests/unit/test_virtual_folders.py` (the totals).

## 3. Clicking a folder filters

- **It narrows the current results to notes in exactly that folder,** shown as a view-indicator chip in the search box (`Projects/ ×`). The search text and the search context don't change; `×` removes the filter.
- **Exact folder only:** `Projects/` shows notes filed directly in it, not those in `Projects/Client-A/`. Subfolders are a click away in the tree.

## 4. Drag and drop moves

| Drag | Result |
|---|---|
| A note **from a folder in the tree** onto another folder | It leaves the folder it was dragged out of and joins the target; any other folder it is in stays |
| A note **from the notes column** onto a folder | "Put it in exactly this folder": all its folder tags are replaced by the target |
| A **folder** onto another folder | Every tag starting with its path is renamed under the target: `Projects/Client-A/` into `Archive/` turns `Projects/Client-A/…` into `Archive/Client-A/…`, subfolders included, on every note |

- A folder can't be dropped into itself or one of its subfolders.
- If the target already exists, the two merge, after one confirmation.
- Each drag is one undo step.
- From the notes column, only a root note can be dropped on a folder: a child inherits its parent's folder tag, so a new one would put it in two folders, not move it. A child dragged over the tree highlights no folder and says why (the maintainer, 2026-11-02).
- A note dropped from the column under a folder filter leaves the column; the target's count updates at once and a floating message ("Moved to `Projects/Client-A/`") offers Undo. Details and what is still open: `docs/ready-to-build/virtual-folders-note-drag.md`.
- Files and folders dropped from the desktop onto a folder (files tagged with it, a folder through the import walkthrough under it): `docs/ready-to-build/desktop-drops-into-folders.md`.
- A locked root note (multi-view) follows the existing rules: tag changes to it are refused like any other edit to it.

## 5. Renaming folders

Rename a folder or subfolder in the tree: every tag starting with its path is renamed on every note, along with the rules mentioning them, through the existing tag rename. Renaming onto an existing folder merges. One undo step.

## 6. Empty folders

- A folder exists only while some note carries its tag; moving the last note out removes it from the tree.
- **New Folder** creates a folder held only in that view's memory, to drag things into. It disappears on changing the search context or another action. **Draw it dimmed or in italics** until a note is in it.

## 7. A note in two folders

Allowed: a second folder tag added by hand puts the note in both folders. The two note rules in §4 keep "move" well defined; with one folder they give the same result.

## 8. Invariants

1. A folder is a tag ending in `/`; folders are never stored apart from tags.
2. Clicking a folder narrows the results to exactly that folder, never its subfolders, and never changes the search context.
3. A folder move or rename renames the tags on every note that has them, in one undo step, losing nothing.
4. A note moved within the tree leaves only the folder it was dragged from; a note dropped from the notes column ends up in exactly the target folder.

## 9. Done when

1. The Virtual Folders toggle turns the tree on and off; off, nothing of it shows. An import turns it on.
2. The import writes `Projects/Client-A/`; nested tags stay `a/b`. Existing folder tags are not converted (re-import).
3. The tree, filter chip, note previews and link-style opening behave as in §2–§3.
4. All drags in §4 and renames in §5 work, with merges confirmed and each one undoable in one step.
5. New Folder behaves as in §6.
6. Tests cover moves, renames, merges, the refused self-drop and the two-folder case; the behavior is described in `docs/ui/`.

## 10. Checked against the code (2026-11-01, when filed)

- **Trailing `/`:** confirmed valid. `isValidTagToken` (`app/static/js/modules/tag-token.js`) and `_is_valid_tag_token` (`app/services/tag_ontology.py`) refuse only a leading `/`; the search syntax accepts `Projects/` and `Projects/Client-A/` as complete terms. Not yet tried: the tag bar's display of such a token, and suggestions.
- **The import's folder tag:** `folder_tag_for` (`app/services/obsidian_import/notes.py`) only wraps `_folder_tag`, which builds every file's folder tag; §1's change belongs in `_folder_tag`. The obsidian-mapping row B3 and `import-export-launch.md` §2.1 still say `Projects/Client-A`.
- **Search stays exact:** as §0 says (`docs/ui/search-semantics.md`, Tag Terms; `import-export-launch.md` §9 item 9).
- **View-indicator chips:** `docs/ui/controls.md` (lines on view indicators); a folder chip joins Untagged, the date range, Notes with files and the sort chip.
- **The search-context trigger's stacked-folder icon:** `docs/ui/controls.md`; §2 asked for it to change, and it did (2026-11-02).
- **Renaming many tags at once is new:** Edit Tag Relationships renames one tag at a time (`docs/design/ontology-rules-v1.md`, "Editing the focused tag"). §4's folder move and §5's rename rename every tag starting with a path; that's new, built on the one-tag rename.
- **Undo:** a tag rename today is not on the ⌘Z history (nothing in the docs says it is); §4–§5 ask for one undo step each, which is new too.
- **"Locked root note (multi-view)" (§4):** multi-view editing is in `docs/ready-to-build/multi-view-editing.md`, not built; the rule applies once it is.
- **On-screen behavior:** the tree's drags, the chip and opening a note move things on screen, so their cases are agreed before code (`AGENTS.md`, "On-screen Behavior Follows the Interaction Principles").

### Open (ask the maintainer)
1. ~~Tags the import already made without the slash~~: **decided 2026-11-01, no conversion**; the maintainer re-imports.
2. ~~The setting~~: **decided 2026-11-01**, Virtual Folders, a menu toggle, turned on by an import (§2).
3. ~~The search contexts' icon~~: **decided 2026-11-01**, stacked cards with a magnifying glass, a first try (§2).

