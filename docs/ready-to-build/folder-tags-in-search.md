# A folder tag in the search includes the folders below it, and the folder is search text

**Status:** Agreed with the maintainer 2026-11-10. Ready to build.

Written from a read-only look at the repo; filed from `docs/inbox/` on 2026-11-11, with the references checked (§8).

Changes: the 2026-10-30 ruling that search never matches by prefix (`docs/ready-to-build/import-export-launch.md` §9 item 9), for folder tags only; `docs/ready-to-build/virtual-folders.md` §0 ("This stays") and §3 (the chip, exact folder only); and §4 of `docs/ready-to-build/search-links.md`, which left folder contexts out of `[[` suggestions.

---

## 0. Today (from the code)

- **Search matches tags exactly, "never a shorter prefix"** (`docs/ui/search-semantics.md`, Tag Terms).
- **Clicking a folder narrows the folder context to it and the folders below it,** its search emptied (`docs/ready-to-build/virtual-folders.md`). The tree already includes subfolders; the search box doesn't.
- **The folder is kept apart from the search,** per search context: `folderFilters` in `app/services/tab_state.py` (`set_folder_filter`, `move_folder_filters`, `drop_folder_filters_under`), shown as a chip (`Projects/ ×`).
- **A search context is a folder context (tree shown) or a plain search;** several folder contexts may exist (`folderContexts`). A folder context is named by its folder, then what is typed (`Projects/ @todo`), `/` with none.
- **Folder counts** (`(3/17)`) and dimming: `app/services/virtual_folders.py` (`folder_note_totals`). The search never adds or removes a folder from the tree.
- **Rename tag does not rewrite saved searches** (confirmed 2026-11-11, `search-links.md` §9). This change depends on that rewrite.

## 1. A search term ending in `/` includes the folders below it

- **`Projects/` finds notes in `Projects/` and in every folder below it** (`Projects/Client-A/`, `Projects/Client-A/2026/`).
- **Only folder tags,** those ending in `/`. `Projects/` does not match the plain tag `Projects/notes`.
- **`-Projects/` leaves out the folder and everything below it.**
- **Every other term stays exact.** `work` still doesn't match `work-archive`.
- **It matches effective tags,** inherited ones included, as search and folder membership already do.
- Why: the tree already works this way; a trailing `/` already means "folder"; and search links and saved searches can then reach a folder exactly as the tree does.
- Given up: searching for "exactly this folder, not below". The tree can't do it either.

## 2. The folder is search text, not a chip

- **Clicking a folder replaces the folder context's search with the folder:** `Projects/`. The top, `/`, empties it. A clean start is the existing rule: a folder never opens narrowed by a search typed elsewhere.
- **Typing narrows it as before:** `Projects/ @todo`.
- **No folder chip and no separate folder per search context.** What the search box shows is what's searched. Deleting `Projects/` from the text does what the chip's `×` did.
- **A folder context is still a search context with the tree shown.** Typing `Projects/` in a plain search narrows it the same way, without the tree.
- **Named by its search,** as every search context is: `Projects/ @todo`; `/` when the search is empty, as today.
- **Stored folders are converted once** into search text (a folder context's folder put at the front of its search), and `folderFilters` goes. No outside users yet: no lasting compatibility.

## 3. What the tree reads from the search

- **The chosen folder comes from the search:** one positive folder term marks that folder; none marks `/`. Two (`A/ B/`, notes in both), or folders joined by `OR`, mark none.
- **Counts and dimming ignore the search's folder terms** and read the rest. Otherwise searching `Projects/` would dim every other folder to `(0/17)`. This matches today, where the chip isn't part of the search.
- **The tree lists the same folders as today.**

## 4. Renames and deletions

- **Renaming or moving a folder rewrites it in every search context's search,** subfolder terms included (`Projects/Client-A/` moved into `Archive/` makes `Archive/Client-A/`). This replaces `move_folder_filters`. A parent's term isn't touched: moving `Projects/Client-A/` leaves `Projects/` as it is.
- **One rewrite** for this, for Rename tag on saved searches, and for search links in notes: only tag terms change, never quoted text.
- **Deleting a folder leaves searches as typed** (decided 2026-11-11), as deleting a tag does: `Projects/Client-A/ @todo` stays and finds nothing once the folder is gone, rather than widening to every `@todo` note. Search links naming it find nothing too. Undoing the deletion needs no repair. `drop_folder_filters_under` goes with the chip and is not replaced. Renaming or moving a folder still rewrites searches (above): the folder still exists.

## 5. Search links

`[[search:Projects/]]` now shows what clicking Projects shows. A folder context's search is offered in `[[` suggestions like any other search context; this replaces the search-links note's "not the folder context".

## 6. Invariants

1. A term ending in `/` matches that folder and every folder below it; every other tag term matches exactly.
2. A folder is never chosen anywhere but in the search text.
3. Clicking a folder never shows it narrowed by a search typed elsewhere.
4. The tree's counts never depend on the search's own folder terms.

## 7. Update the docs

`docs/ui/search-semantics.md` (Tag Terms), `docs/ready-to-build/virtual-folders.md` (§0 and §3), and the folder chip in `docs/ui/controls.md` if it is described there.

## 8. Checked against the code (2026-11-11, when filed)

- Every reference in §0 holds: `folderFilters`, `folderContexts`, `set_folder_filter`, `move_folder_filters` and `drop_folder_filters_under` in `app/services/tab_state.py`; `folder_note_totals` in `app/services/virtual_folders.py`; "never a shorter prefix" in `docs/ui/search-semantics.md`.
- **The folder already includes the folders below it:** `search_in_folder` (`virtual_folders.py`) adds the folder and each folder tag under it to every clause, as OR. §1 moves that into search matching; `search_in_folder` goes with the chip. `virtual-folders.md` §3's "exact folder only" was already replaced by its "Folder contexts" section (2026-11-07).
- **New notes:** a note made in a folder view is filed in the folder chosen, not below it (`search_for_new_note`). With the folder as search text, a new note takes `Projects/` from the search like any other tag of it: the same result.
- The folder chip is described in `virtual-folders.md` ("Folder contexts", §3) and `docs/ui/state-handling.md`, not in `docs/ui/controls.md`.

**Decided 2026-11-11:** a term ending in `/` includes the folders below it whether Virtual Folders is on or off. The setting only shows or hides the tree, so a search or a search link (`[[search:Projects/]]`) means the same either way. Subfolders stay findable without the tree: typing `Projects` in the search suggests every folder tag under it (`import-export-launch.md` §9 item 9).

**Decided 2026-11-11:** deleting a folder leaves searches as typed (§4). Nothing is open.

