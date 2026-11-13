# Menus and settings

Use this reference to explain MetaList accurately. It describes user capabilities,
not permission or tools for you to execute every operation. You can answer and
request one supported menu/dialog opening. You cannot submit a form, change
settings, run a shell command, or mutate notes through this help response. Do not
claim that you inspected current notes or settings: none are supplied here.
Prefer user-facing steps over implementation details. If the reference does not
answer a question, say what is unknown; do not invent syntax or controls.

Sources: docs/ui/command-palette.md

# Command Palette

Open with `⌘ + /` or the menu (`≡`) button in the upper right.

## Undo/Redo Boundary
Opening or dismissing the command palette does not clear undo/redo. Global actions establish their own boundaries; bulk tag proposal actions clear the existing stacks only after successful changes and create no undo entry. Failure, cancellation, or no changes preserves history. See [undo/redo scope](state-handling.md#bulk-operations-are-outside-ordinary-undoredo).

## Tag proposal controls

- **Accept or Reject AI-Proposed Tags…** (tags the AI chat proposed, not yet accepted) selects acceptance/removal, current context/entire vault, and an exact case-insensitive tag filter (blank means all proposals). Apply executes directly without another confirmation, model call, or progress/cancellation modal; the normal busy spinner remains visible until completion. How many proposals changed shows as a corner card and the dialog stays open; a refused Apply opens the error dialog over it.
- **Reject All AI-Proposed Tags (Current Context)…** asks for confirmation, then removes every pending proposal in the active search context. It uses the same atomic bulk path and requires no configuration form or model call. After confirmation, the normal busy spinner replaces the confirmation without opening a second modal.
- **AI Tagging Vocabulary…** opens AI Agent Settings on its **Tagging** tab: existing tags only, or existing and new tags. The tagging instructions are built in and cannot be edited.
- Generate proposals by explicitly requesting them in AI chat. Generation is not a menu action.

## Semantics
- Query is an unordered bag of words.
- AND-only matching against manually-authored tags.
- While you are mid-token (no trailing space), it behaves as a prefix filter.

## Results
- Booleans toggle with `Enter`.
- Boolean labels describe the next action: `Show …` while hidden and `Hide …` while visible.
- Selects cycle with `Enter` (and adjust with `←`/`→`).
- Actions run with `Enter`.

## Sort Order
- The notes-view background and side-rail right-click menus also offer **Sort by**: Normal, Datetime Created, Datetime Last Updated, Alphabetical, Content volume and, while Notes with Files is on, File Size, then **Reverse Order**, a check item that combines with any of them (Normal too: the manual order bottom to top). Reversed, Alphabetical is Z to A, the date orders start from the oldest, and Content volume and File Size from the smallest; date separators flip with the notes. Picking another order keeps Reverse Order. The current mode is ticked and disabled. Choosing a mode updates the same saved per-tab setting as the command palette; Normal restores manual order.
- `Sort order` is a per-search-context, server-owned view setting. Duplicating a search context copies its sort mode; a new one, a reference view included, starts in Normal order.
- Modes are exposed as distinct actions: `Sort Order: Normal`, `Sort Order: Datetime Created`, `Sort Order: Datetime Last Updated`, `Sort Order: Alphabetical`, `Sort Order: Content Volume` and (while Notes with Files is on) `Sort Order: File Size`, plus `Sort Order: Reverse`, which turns Reverse Order on or off.
- Datetime Created orders roots newest-first by each root note's own creation timestamp; children do not affect its position or date group.
- Datetime Last Updated orders roots newest-first by the latest update timestamp anywhere in the root's subtree, including the root and all descendants. Date groups use that same timestamp.
- Changing a reference between link (`[[UUID]]`) and embed (`![[UUID]]`) is an edit: it changes what shows, so it advances the note's update time, as adding or removing references, changing their targets or editing surrounding content does.
- In alphabetical mode, root notes are ordered by root-note content without rewriting the stored manual order.
- In content-volume mode, roots are ordered largest-first by the total plain-text character count of every note in each root subtree. HTML markup does not count, and equal totals preserve manual root order. Search phrases include `character count`, `content volume`, `length`, and `longest`.
- File Size (only while Notes with Files is on) orders roots largest-first by the total size of the files the filter keeps in each root and its children. Each note shows its total in a pill and each counted file its size. Ending the filter returns to Normal.
- The server returns the ordered root window plus `sortMode`/`rootSortBuckets`; the client inserts day-separator rows between visible roots.
- In a non-normal sort order, new root notes are limited and editing freezes the order: Datetime Created and Datetime Last Updated allow a new root note only at the top (`Enter` outside edit mode, Add Note, pasting into a new note), never below a root note; Alphabetical, Content volume and any reversed order (Normal too) allow no new root notes. Child notes can always be added. Blocked actions show a banner. While a note is edited, it stays in place even if saving changes its sort position (in date orders, under its neighbour's date header); after leaving edit mode it moves to its sorted place and the screen stays on the surrounding notes. Details: `help-notes` (Sorted search contexts).
- When a non-normal sort mode is active, a gray chip at the right end inside the search input names it (`Created`, `Updated`, `A–Z`, `Length`, `File size`; reversed: `Created ↑`, `Updated ↑`, `Z–A`, `Size ↑`, or `Reversed` for Normal reversed; the full name is its tooltip). Its `×` returns to Normal order, not reversed. Untagged notes shows the same kind of chip, `Untagged`, before it, and a date range its own (`Updated · today`) between them.
- Changing sort mode is treated as a global view-context switch: the search context's scroll state resets and undo/redo history is blanked for it.
- A search context keeps its sort order (Reverse Order too) until its chip's × ends it or another order is picked: a new search keeps it, and so does switching to another search context and back. A new blank search context starts in Normal order. Following a reference and coming back keeps the sort.

## Date Range
- **Date Range** (after Sort by in the background, side-rail and search-box right-click menus) shows only the root notes whose date is in a range, each with its children. First the date, ticked: **Last Updated** (the latest update anywhere in the root's subtree) or **Created** (the root's own creation, or the date of its own `@datetime` tag, such as `@datetime=2026-10-24`; sorting by Created still uses the creation). Then the range: **Any Date** (no filter), **Today**, **Last 7 Days**, **Last 30 Days**, **This Year** (counted back from today, today included), and **Custom Range…**, a dialog with Last updated/Created and From and To dates (both included; either may be left empty). Picking the other date moves the active range to it; with no range it is used for the next one.
- Palette actions: `Date Range: Last Updated`, `Date Range: Created`, `Date Range: Any Date`, `Date Range: Today`, `Date Range: Last 7 Days`, `Date Range: Last 30 Days`, `Date Range: This Year`, `Date Range: Custom Range…`.
- It combines with a search, Untagged notes and any sort order.
- A gray chip inside the search input names it (`Updated · today`, `Created · Oct 1–22`, `Updated · since Oct 1`); the full wording is its tooltip and its `×` shows every date again.
- Like a sort order it is kept per tab until its `×` ends it, through a new search and switching tabs; a new tab starts without one; following a reference and coming back keeps it.

## Notes With Files
- **Notes with Files** (after Date range in the background, side-rail and search-box right-click menus) shows only the notes with an attached file, or a file of one kind, each with the notes above it: **All Notes** (no filter), **Any File**, then every type the notes use, most files first (**ZIP Files**, …), with **Images**, **PDFs**, **Markdown Files** always listed. A note counts by a `[[file]]` link or `![[file]]` embed in its own text; **Images** also finds pictures pasted into a note. Markdown files are known by a `.md` or `.markdown` name.
- Palette actions: `Notes with Files: All Notes`, `Notes with Files: Any File`, `Notes with Files: Images`, `Notes with Files: PDFs`, `Notes with Files: Markdown Files`.
- It combines with a search, Untagged notes, a date range and any sort order; a new search keeps it (pick Images, then type a search, to find those notes with a picture), and it stays with its search context.
- A gray chip inside the search input names it (`Files`, `Images`, `PDFs`, `Markdown Files`); its `×` shows every note again.
- A note being edited stays in view even when saving puts its date outside the range; after leaving edit mode it leaves the view.
- Export, Print, find (⌘F) and the AI chat's view use the search context's range.

## Untagged Notes View
- `View: Untagged Notes` temporarily overrides the displayed results with notes that have no non-meta effective tags while preserving the active search context and its search. Its search box is visually blank because the preserved query is not active.
- `View: All Notes` returns to the underlying search context. The active untagged view also appears as an `Untagged` chip inside the search input, before any sort chip.
- It belongs to its search context: switching to another search context and back keeps it, and so do a reload and clicking the search context already shown. A duplicated search context copies it; a new one, a reference view included, starts without it. Following a reference and coming back keeps it.
- Changing the search input, the chip's ×, `View: All Notes` and Reset Current View Filters end it. Changing it resets the active display's scroll state and undo/redo context.

## Config
- Tag mappings live in `app/static/config/command_palette_tags.json`.
- `Find in List` opens the find bar, as `Cmd+F` does (`docs/ui/find.md`).
- Any word of a command's name finds it in the palette (`edit` finds `Edit Tag Relationships…`), besides the topic words listed for it (`ontology`, `synonym`).
- Search `LLM` or `OpenAI` to find `AI Agent Settings` for API key and model configuration.
- Endpoint definitions (behavior/labels) live in code.
- Palette preferences (`pref.*`) and command usage history are persisted per vault in the main SQLite DB via `/api2/auth/client-state*`, not in browser `localStorage`.
- `Theme`: `System` (default), `Light`, `Dark`, `Fathom` (code editor, monospace, dark), `Phosphor` (green terminal, monospace, dark, nothing animates), `Vellum` (warm paper, book serif, light) or `Ye Olde Scrypte` (painted manuscript, light); Enter cycles it.
- `Stats Style`: `Strip` (default), `Tiles` or `Ledger`, how `@stats` and `@sum=…` look; Enter cycles it.
- The palette keeps its order while open: using a command never moves its row; uses count from the next opening.
- `Animated transitions` is on by default and controls UI motion such as tag-bar edit transitions, note expand/collapse transitions, the login screen fading out over the notes, and the page cross-fading (300 ms) when `Theme` changes.
- `Dictation Settings…` sets the spoken phrases for pasted dictated text: the phrase that starts tags in a note (`start tags`), the phrases that start and end a quote (`quote`, `end quote`), and the phrase that excludes the next search term (`minus`). Each is words of letters, 2 to 64 characters; the quote and exclusion phrases must differ. Save applies them, Escape or a click outside closes without saving.
- `Visual Cues…` opens one window of independent checkboxes, all on by default and saved immediately. Under Drag and drop: `Drag ghost` (a dashed outline of the dragged note and its visible children follows the pointer), `Drop indicator` (a grey landing line plus a faint outline on the note it lands beside or under), and `Direction cursor` (the mouse cursor itself becomes an up, down, indent or outdent icon for a possible move; impossible moves and the option turned off keep the usual grabbing hand). They change only what is shown; dragging works the same. Close the window with Escape or by clicking outside it.
- `Note Layout & Appearance…` stores vault-scoped presets for top-level note size, child indentation, vertical spacing, note corners, and tag style. The defaults are `Larger`, `Standard`, `Comfortable`, `Round`, and `Pills` respectively. Note corners can be `Subtle`, `Rounded`, or `Round`; tag style shows visible note tags as outlined `Pills` or `Plain text` in both themes.
- `Search Suggestion Stats & Settings…` is the single suggestion-personalization control surface. Its ordered 1–365 day slots and default-on time-window-label and one-credit-per-note-per-search-context toggles save immediately when changed. The modal also displays retained daily tag-credit statistics and provides the confirmed activity reset. An empty slot list disables personalization; the default slots are 1, 7, and 30 days.
- `Show/Hide AI Chat` controls the resizable right-side chat panel.
- `AI Chat: Summarize Now` replaces every turn the AI still sees with a summary the user can read (also on right-clicking a completed answer). With nothing new since the last summary it says "Nothing to summarize yet". See the AI help topic on long chats.
- `AI Agent Settings`: four folder tabs and one Save. **Keys**: a switch per provider (OpenAI, Anthropic, Google), each with its API key and usage and billing link. **Privacy**: the cloud privacy rules (blacklist and whitelist). **Reading**: web access, and Model window used (a percentage of each model's context window, one limit for answers and tagging). **Tagging**: which tags the AI may propose, existing tags only or existing and new tags. `Cloud AI Privacy…` opens it on Privacy and `AI Tagging Vocabulary…` on Tagging. Model and thinking level are picked only beside chat Send; picking a model picks its provider. See `docs/ui/ai-chat.md`.
- AI prompts and skills are built in and cannot be edited, so the AI behaves the same for every user; there is no prompt editor.
- Session Idle Timeout… is disabled by default. It is a vault-scoped server setting stored in `app_settings` and managed via `/api2/auth/settings/session-timeout`. Expiry requires browser reauthentication but preserves the hydrated server cache for a fast login; explicit logout still purges decrypted runtime state.
- On first launch after this change, the browser imports any legacy command-palette `localStorage` values into the vault DB and then clears those legacy keys.

## Utility Actions
What each utility action does (backups, import and export, vaults, inserting things, trimming files, prioritizing and alphabetizing) is in the menu-actions help topic.

## Collapse/Expand All
"(current view)" means the full active search context (not just rendered DOM).
The implementation uses `POST /api2/notes/set-collapsed-in-context`.

- **Expand all root notes** and **Collapse all root notes** update only the roots in that context. Child and deeper descendant notes retain their saved states.
- **Fully expand all notes** and **Fully collapse all notes** recursively update every descendant under those roots, including descendants that are not currently rendered because an ancestor is collapsed.

These are treated as **global** actions:
- The client bumps the undo-context epoch.
- The server clears undo/redo history for the active undo context.
