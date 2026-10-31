# Search bar typing and suggestions

Use this reference to explain MetaList accurately. It describes user capabilities,
not permission or tools for you to execute every operation. You can answer and
request one supported menu/dialog opening. You cannot submit a form, change
settings, run a shell command, or mutate notes through this help response. Do not
claim that you inspected current notes or settings: none are supplied here.
Prefer user-facing steps over implementation details. If the reference does not
answer a question, say what is unknown; do not invent syntax or controls.

Sources: docs/ui/search-semantics.md, docs/ui/controls.md

Search syntax and what a search finds are in the search help topic.

## Suggestion ranking

- Search-bar tag suggestions are segment-aware for connector-separated tags.
- A suggestion must leave at least one matching note in the active `OR` clause, satisfying every completed tag, text term, and exclusion. For example, after `prediction-future`, typing `security` only suggests `computer-security` if that combination actually matches a note. Partial tag overlap alone is insufficient. Matching uses the same effective tags as search, including inheritance, references, and ontology inference. This filtering happens before personalization and the visible limit; note-tag recommendations can still propose new combinations.
- For a blank query or the first tag prefix in a query, ordered calendar-day windows promote matching tags into the first suggestion slots. The default is `[1, 7, 30]`, and the command-menu editor can add, remove, or reorder 1–365 day windows; an empty list disables personalization.
- Prefix matching happens against the complete candidate set before the visible suggestion limit is applied, so an interacted `shortcut` cannot be discarded merely because 50 unrelated tags rank above it globally and leave frequency-ranked `short-story` first.
- Case-equivalent tags are collapsed in suggestions, and the most-used spelling is shown.
- Enter and the arrow keys act only on a suggestion list built for the text in the box. While the list for what you just typed is on its way, the one on screen is for older text: Enter then closes it and keeps what you typed (it does not add a note), and the arrows wait for the new list.
- Searches themselves never earn credit. Intentional note engagements—edit selection, manual expansion, full-screen view, shell/todo command execution—increment the note's raw explicit/inherited searchable tags once per active search context/search flow. Leaving for another search context or executed search and later returning starts a new flow, so a later shell run can count again. Successfully adding explicit tags separately credits only those newly added tags; removals and case-only changes are neutral. Accepting a search suggestion by mouse or keyboard credits that selected tag once, with no engagement-flow deduplication. Clicking a search context credits each known positive tag term in its executed query once; excluded tags and quoted text are ignored. Programmatic search-context restoration/switching, collapse, search execution, hover, render, and scroll are neutral.
- After one or more completed tags, the remaining suggestions (only tags that still leave results) are ordered by how closely their notes overlap with the notes matching the tags already typed, so specific companions come before tags that are common everywhere.
- Activity uses sparse per-calendar-day counts. A window sums the relevant daily buckets, selects its highest-count matching tag, and excludes tags chosen by earlier windows. No decay calculation or all-time score exists. The latest 365 populated days are retained, so unused calendar days consume no buckets.
- In password-protected vaults, all retained daily buckets live together in one authenticated encrypted payload. The database exposes only one random row UUID, ciphertext, nonce, and authentication tag—never dates, tag names, counts, queries, or changed-tag metadata.
- A typed prefix can match either the start of the full tag or the start of any connector-separated segment.
  - Example: `wor` suggests `workspaces` and `databricks-workspaces`.
  - Example: `orksp` suggests neither.
- Right-clicking a search suggestion (Control-click on a Mac) opens its tag menu: Edit Tag Relationships, then **Why suggested** below it. The search and the list stay as they were; `Escape` closes only the menu. A right-click earns no activity credit.
- **Why suggested** says what MetaList's ranking used (not the AI): how often you worked with the tag in a personalization window (`You've worked with it 12 times in the last 7 days`), the notes it shares with the tags already in the search, how many notes the search so far finds it on, how many notes leaving it out removes, or that a first tag is listed by use; last, how many notes searching for it finds.
- Right-clicking a tag already typed in the search box opens its menu with **About this tag** below Edit Tag Relationships: how many notes searching for it finds (or `No note has this tag`, often a typo), how many notes it shares with the other tags in the search, what leaving out a `-tag` removes, which synonyms and implying tags it also finds, and how often you worked with it recently.
- The server returns at most `MAX_SEARCH_SUGGESTIONS` suggestions; the default is 20.
- This affects suggestions only; actual tag search matching remains exact against effective tag terms.

## Search Bar

From docs/ui/controls.md.

### Search Input Behavior
- The search field keeps a muted search icon inside the input before and during typing; hovering the field shows a `Search` tooltip.
- Pressing `Enter` while focused in the search input creates a new **root** note.
- Pressing `Esc` while focused in the search input blurs the field and dismisses search suggestions, without clearing the current query or search results.
- The right side of the black search header shows only the result's root-note count.
  MetaList does not tokenize search results during startup, ordinary interaction,
  or snapshot refresh merely to populate this UI. The existing `Show/Hide search
  result count` preference controls the count.
- If the search query contains required tag terms (unquoted tokens like `asdf`), the new root note is created with those tags in its tag bar.
- When creating a child (`⇧ + ⌘ + Enter`) or sibling (`⌘ + Enter`) note under a note that already provides the required **non-meta** tags via inheritance, the new note is **not** redundantly tagged.
- **Sorted search contexts: adding and editing notes.** In any non-normal sort order a new or edited root note could land far from where you are, so:

  | Sort | While you edit a note | New root note at the top (`Enter` outside edit mode, Add Note, pasting or dropping into a new note) | New root note below a root note (`⌘ + Enter`, Split, paste as sibling) |
  |---|---|---|---|
  | Normal | — | allowed | allowed |
  | Datetime Created | order frozen (editing never changes it anyway) | allowed: it lands at the top | blocked |
  | Datetime Last Updated | order frozen | allowed: it lands at the top | blocked |
  | Alphabetical | order frozen | blocked | blocked |
  | Content volume | order frozen, also while editing a child note | blocked | blocked |

  - Child notes (`⇧ + ⌘ + Enter`, paste as child, or a sibling of a child note) can always be added: the sort orders only root notes.
  - A blocked action does nothing and shows a banner saying why (switch to Normal order, or add a child note). Pasting a copied note onto an empty note fills that note, so it is never blocked.
  - **Order frozen while editing:** the note you are editing (or the root note containing it) stays where it was, even when saving changes its date, name or size. In the date orders it shows under its neighbour's date header meanwhile.
  - **Leaving edit mode:** the note then moves to its sorted place, and the screen stays on the surrounding notes (like a mail app), so nothing you are looking at jumps. If the note keeps its place, your caret or reading line stays put as usual.
- Sort modes do not change canonical insertion behavior. New roots are still inserted into the manual root order first, then rendered in the active sort order.

### Search Suggestions
- Suggestions are **tag-only** (no text suggestions).
- For a blank search or the first tag prefix in a query, the first suggestion slots can be personalized from ordered activity windows. The default windows are 1, 7, and 30 calendar days.
- Case-equivalent tags are collapsed in the suggestion list, and the most-used spelling is shown.
- Search execution, typing, scrolling, hovering, rendering, collapsing, and programmatic search-context switches do not earn credit.
- Entering edit mode, manually expanding a note, entering full-screen note view, running a shell note, toggling todo/done, and successfully reordering/indenting/outdenting a note count as intentional note engagements. Structural no-ops do not count.
- Each engagement increments every raw searchable tag on the note, including inherited tags and meta tags, before ontology inference. This lets an `@shell` child under `shortcut` credit both raw tags without rewarding unrelated inferred tags.
- By default, each note can earn only one engagement credit in the same active search context and executed search, even when other notes are engaged between two interactions with it. The context limits repetition but does not filter the credited note tags. Leaving that context and later returning starts a fresh flow.
- Successfully adding one or more explicit tags awards one credit to each newly added tag. It does not re-credit tags already present or inherited from ancestors; removals and case-only changes award nothing.
- Accepting a search suggestion by click or `Enter` awards one credit to the selected tag every time. Clicking a search context awards one credit to each known positive tag term in that tab's executed query; excluded tags and quoted text do not earn credit.
- Counts are stored in sparse daily buckets. Days without activity have no bucket and do not consume retention capacity; the latest 365 populated days are retained.
- Each configured window chooses its highest-count matching tag, excluding tags already chosen by earlier windows. The remaining suggestions retain normal vault-frequency ordering.
- `Cmd/Ctrl+/` → `Search Suggestion Stats & Settings…` is the single place for suggestion activity controls. Changes to its ordered 1–365 day slots, default-on time-window labels, and default-on one-credit-per-note-per-search-context limit persist immediately. It also shows every retained populated date and tag-credit count and includes a confirmed `Reset Activity` action. Disabling the credit limit makes every qualifying interaction count; removing every slot disables personalization.
- Confirmations, errors, and completion notices use MetaList modals, login-state messaging, or banners; native browser `alert`, `confirm`, and `prompt` dialogs are forbidden by the development startup sanity gate.
- While typing a partial tag token, suggestions are segment-aware for connector-separated tags: a prefix can match the start of the full tag or the start of any connector-separated segment (`-`, `_`, `.`, `/`).
- Example: `wor` can suggest `workspaces` and `databricks-workspaces`; `orksp` suggests neither.
- When the active prefix starts with `@`, matching meta-tag suggestions are ordered by notebook usage frequency (note count), with alphabetical tiebreaks for equal counts.
- After completing a tag and adding a space, suggestions are ordered by tag co-occurrence with all existing tag tokens in the query (strict overlap count > Jaccard within overlap).
- Suggestions appear only when the search input is focused.
- Moving the pointer below the suggestion popup, or horizontally outside the centered notes column, hides open search suggestions while keeping focus in the search input. After that pointer dismissal, suggestions stay closed until the user resumes typing or clicks the search input again.
- Arrow keys move selection; `Enter` accepts the selected suggestion without adding a trailing space.
- Suggestion matching is broader than actual filtering: search results still match exact effective tag terms only.
