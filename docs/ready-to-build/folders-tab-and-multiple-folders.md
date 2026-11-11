# The folders tab only shows the tree, and several folders add results

**Status:** Agreed with the maintainer 2026-11-11. Ready to build.

Written from a read-only look at the repo. Check the code references before relying on them.

Changes: `docs/ready-to-build/virtual-folders.md`, "Folder contexts" (folder contexts as a kind, and what the folders tab does) and "no rules are added"; and `docs/ready-to-build/folder-tags-in-search.md` §3 (two folders mark none).

---

## 0. Today (from the code)

- **Folder terms are built** (`folder-tags-in-search.md`, 2026-11-11): `Projects/` includes the folders below it (`search_index._search_term_posting_locked`); a folder chosen in the tree is the search (`tab_state.choose_folder`); the tree reads it (`virtual_folders.chosen_folder_of`, `without_folder_terms`; `folder-search-terms.js`).
- **Folder contexts are still a kind:** the tree shows only while one does. Opening the folders tab switches to the folder context used last (or makes one); closing it switches to the plain search used last (or makes one). `folderContexts` and `recentTabs` in `app/services/tab_state.py`; `openFoldersTab`, `closeFoldersTab` (`keyboard-events.js`); `toggleFolderContextFromTab` (`virtual-folders-service.js`). Switching between the kinds moves the notes column sideways, the accepted exception in `docs/ui/state-handling.md`.
- **Whether the tree shows** isn't stored in the browser any more (`metalist.virtual_folders.shown`, unread).
- **`OR` separates whole clauses;** there are no parentheses (`docs/ui/search-semantics.md`).
- **A new note takes the search's tags** (`search_for_new_note`); an outdented note that would leave the results gets the tags it misses (`docs/ui/search-semantics.md`).
- **Search reads each note's effective tags** (own, inherited, implied by rules), and folder terms match by prefix there (`_search_term_posting_locked`), so a rule implying a folder already files notes in it. **Nothing outside search treats a folder as being in its parent:** no parent-folder implication was found, and `virtual-folders.md` says "no rules are added". So a rule on `Projects/` fires only for notes tagged exactly `Projects/`. Check this.

## 1. The folders tab shows or hides the tree, nothing else

- **Opening or closing it never switches, creates or closes a search context.**
- **No folder contexts as a separate kind.** Any search context can be looked at with the tree. Existing folder contexts become ordinary search contexts with the same search (converted once; no outside users yet). `recentTabs`' split by kind goes. Every context is named by its search.
- **The tree belongs to the view, not the context:** switching contexts leaves it shown or hidden, so the notes column no longer moves on a switch, and the exception in `state-handling.md` goes. Kept per view (each window) like its active search context, surviving a reload (decided 2026-11-11). The phone has no tree.
- **An import** no longer changes the tree.

## 2. Clicking a folder

- **A click replaces the current search context's search with that folder:** `Projects/`. What was typed there is gone; the maintainer accepts that. A clean start still keeps a folder from opening on zero notes. To keep a search, `+` duplicates the context first.
- **Clicking the only chosen folder again, or `/`,** empties the search (as today).
- **⌘-click (Ctrl-click off the Mac) adds or removes that one folder** and leaves the rest of the search alone: `Projects/ @todo`, ⌘-click Archive, gives `Projects/ Archive/ @todo`; ⌘-clicking Archive again takes it back out (confirmed 2026-11-11: add, not swap).
- ⌘-click on `/` removes every folder term and keeps the rest of the search: `Projects/ Archive/ @todo` becomes `@todo` (decided 2026-11-11). ⌘-click only ever changes folders; tags such as `@todo` stay.

## 3. Several folders add results

- **Folder terms in a search combine with each other as "any of";** everything else still narrows. `A/ B/ @todo` finds to-dos in A or B (or below either).
- **Why:** `OR` splits the whole search, with no parentheses, so `A/ OR B/ @todo` means "everything in A, or to-dos in B". Folders widening among themselves is the only way such a search reads naturally, and it matches selecting several folders in a file manager.
- **`-A/` still subtracts** A and everything below it.
- **Per `OR` clause:** each clause's folders combine on their own.
- **Given up:** asking for notes filed in both A and B.
- **One rule everywhere the search is evaluated:** results, the tree's counts, tag suggestions (which must leave at least one matching note), new-note refusal, embedded searches and search links, and what the AI reads.
- **The search help says it in one line:** folders add, tags narrow.

## 4. Where MetaList adds tags so a note matches

- **A new note under `A/ B/`** is filed in every folder of its clause, A and B, as it is today (decided 2026-11-11, instead of the first folder only that was proposed): the note takes what the search names, as with tags. The maintainer: more logically consistent, and the order of terms in a search must not start to matter; several folder terms at once is rare, for power users.
- **An outdented note** that would leave the results likewise gets every folder of the clause, when it is in none of them.

## 5. What the tree marks

- **Every positive folder term is marked,** several at once. None marks `/`.
- **With `OR` clauses,** the folders of every clause are marked (decided 2026-11-11): `Projects/ OR Archive/ @todo` marks Projects and Archive, where the results come from.
- **Counts and dimming still ignore the search's folder terms.**

## 6. A folder tag implies its parent folders

- **Being in a subfolder is being in the folder,** everywhere, not only in search: `Projects/Client-A/` implies `Projects/`.
- **So a rule on a folder reaches everything below it:** if `Projects/` implies `work`, a note in `Projects/Client-A/` gets `work`.
- **One rule covers search, rules, properties that come through rules, counts and suggestions.** Search's prefix matching becomes a consequence of it.
- **How is the builder's call:** a built-in implication from each folder tag to its parents, or rules matching folders by prefix as search does.
- **The tag bar doesn't list ancestor folders** (settled 2026-11-11 by what exists): the tag bar shows only the tags written in it, never inherited or implied ones (`docs/ui/tag-bar.md`). Ancestor folders behave as implied tags do in tag suggestions: left out with nothing typed, and `Already applies: implied by "Projects/Client-A/"` when typed.

## 7. Invariants

1. Opening or closing the folders tab never changes which search context is shown, or any search.
2. A folder chosen in the tree is always just a term in the search.
3. Folder terms in one clause widen; every other term narrows.
4. MetaList files a note in more than one folder on its own only when the search it is made or outdented under names several (§4).
5. Whatever applies to a folder applies to every folder below it.

## 8. Update the docs

`docs/ready-to-build/virtual-folders.md` ("Folder contexts"), `folder-tags-in-search.md` §3, `docs/ui/search-semantics.md` (folder terms), `docs/design/ontology-rules-v1.md` (folders imply their parents), `docs/ui/state-handling.md` (the exception goes), the search help, and the browser suites written for folder contexts.

## 9. Checked against the code (2026-11-11, when filed)

- **`search_for_new_note` no longer exists** (removed with `folder-tags-in-search.md`). A new note's tags come from `compute_initial_tags_for_new_note` (`app/usecases/search_comment_autofill.py`), which gives the note every positive tag term of the first clause: today `A/ B/` files it in both. §4 changes that.
- **Rules ignore parent folders, confirmed:** neither `app/services/tag_ontology.py` nor `app/services/ontology_rules_store.py` treats a folder tag specially, so a rule on `Projects/` fires only for notes tagged exactly `Projects/`. Only search widens a folder term to the folders below it (`SearchIndex._search_term_posting_locked`). §6 changes that.
- **Folder contexts as a kind, still there:** `_folder_contexts` and `recentTabs` in `app/services/tab_state.py` (a duplicate of a folder context is one); `openFoldersTab`, `closeFoldersTab` (`keyboard-events.js`); `toggleFolderContextFromTab` (`virtual-folders-service.js`, also the command palette); `isFolderContext` (`folder-context-state.js`).
- **Imports lean on them too:** where a dropped folder ends (`droppedImportView`, `dropped-import-view.js`, its `isInFolderContext` from `import-wizard-steps.js`; `desktop-drops-into-folders.md` §E: "the tree is showing … in the same folder context"). With §1 this reads "the tree is shown".
- **The tree marks one folder or none** today (`virtual_folders.chosen_folder_of`, `CHOSEN_NONE` for two folders or `OR`; `chosenFolderOfSearch` in `folder-search-terms.js`). §5 makes it a list.
- **Counts already ignore the search's folder terms** (`without_folder_terms` before `folder_note_counts`), as §5 keeps.
- **Every place a search is evaluated goes through the search index's clause matching** (results, counts, suggestions, embedded searches, the AI's view), so §3 belongs there, once.
- **Where "the tree is shown" is kept per view is new:** no per-view setting holds it today (`virtual-folders-state.js` says its old browser key is read by nothing).
- **The browser suites written for folder contexts** (folder-context, view-change-top, folder-note-drag, tab-switch, folder-drop) still test the chip removed with `folder-tags-in-search.md`; rewrite them once for this design, not twice.

### Open (ask the maintainer)

Decided 2026-11-11: the tree shown or hidden is kept per view (window) and survives a reload (§1). ⌘-click on `/` removes every folder term and keeps the rest (§2). A new or outdented note gets every folder of its clause (§4). `OR` marks every clause's folders (§5). The tag bar doesn't list ancestor folders: it lists no implied tag at all (§6). Nothing is left open.
