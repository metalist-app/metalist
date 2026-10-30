# Search and views

Use this reference to explain MetaList accurately. It describes user capabilities,
not permission or tools for you to execute every operation. You can answer and
request one supported menu/dialog opening. You cannot submit a form, change
settings, run a shell command, or mutate notes through this help response. Do not
claim that you inspected current notes or settings: none are supplied here.
Prefer user-facing steps over implementation details. If the reference does not
answer a question, say what is unknown; do not invent syntax or controls.

Sources: docs/ui/search-syntax.md, docs/ui/search-semantics.md

Typing in the search bar and what it suggests (and why) is in the search-suggestions
help topic.

# Search Syntax

## Scope
- This document describes the **client-side search query syntax verifier**.
- It does **not** describe search semantics (what matches what).
- Search execution is gated by syntactic completeness: incomplete queries do not execute.
- Search queries do not provide created/updated date constraints.
- The untagged-notes view is also outside search syntax. Select it from the command palette rather than entering `@untagged`.

## Terms
Search queries are a whitespace-separated list of **terms** and optional `OR`
operators. Terms next to each other form an implicit-AND clause; `OR` separates
clauses.

When explaining a query, split at unquoted uppercase `OR` first and describe each
clause separately. Count clauses separately from terms: `OR` is a separator, not
a term or an extra clause. A quoted phrase is one text term, regardless of how
many words it contains. For example, `A B OR C` has two clauses and three terms.

### OR Operator
- Only exact uppercase, unquoted `OR` is an operator.
- Every clause must contain at least one term, so leading, trailing, and
  consecutive `OR` operators are invalid.
- `+OR` and `-OR` are invalid because uppercase `OR` is reserved and cannot be
  used as a tag.
- Lowercase or mixed-case forms such as `or` and `Or` remain ordinary tag terms.
- Quoted `"OR"` and `'OR'` remain ordinary text terms.

Examples:
- `A B C OR D E`
- `A OR B OR C D`

### Tag Terms
- `foo`
- `-foo`
- `+foo`

Notes:
- `+`/`-` semantics are out of scope here; they are just syntactic prefixes.
- Tag tokens follow the same character rules as tag-bar *non-wrapper* tokens.
- A tag with a value (`@code=python`) is searched whole or by its name: `@code` finds every `@code=<language>` note and `-@code` excludes them all; `@code=python` finds Python notes only. Typing `@c` or `@code` suggests `@code` and the languages in use.
- Bracket wrappers (`[foo]`, `{foo}`, `((foo))`) are **not** part of search syntax.

### Text Terms
A text term is a quoted string using either quote character, as long as the opener and closer match:
- Double-quoted: `"some text"`
- Single-quoted: `'some text'`
- Negated forms: `-"some text"`, `-'some text'`

Escapes inside quoted text (backslash approach):
- Within `"..."`: allow `\\` and `\"`
- Within `'...'`: allow `\\` and `\'`

Searching for quote characters without escaping:
- Search for a literal `"`: use single quotes: `'"'`
- Search for a literal `'`: use double quotes: `"'"`

Highlighting: the notes list marks each required quoted phrase (from every `OR` clause)
in yellow wherever it occurs: in note text, embedded notes, children shown with a match,
and tag-bar comments. Excluded phrases and tags are not marked, nor is the note being
edited (until the user leaves edit mode), full screen, floating windows, export or print.

## Normalization
- Runs of whitespace are normalized to single spaces.
- Leading/trailing whitespace is trimmed, except the text of an open last quote, which keeps its trailing space.
- The verifier actively rewrites the input while typing (cursor/selection is preserved).

## Pasting Dictated Text
- Pasting (never typing) dictated text, for example from Superwhisper, turns it into tags: "neural network minus python" becomes `neural-network -python`. The full rules are in the dictation help topic.

## Completeness + Warnings
The verifier produces:
- `normalizedText`: the normalized query string.
- `sanitizedText`: only complete terms.
- `isComplete`: whether the full query is syntactically complete.
- `warningMessage`: user-facing warning text (or `null`).

Rules:
- **Open quotes**: an open quote reaches the end of the query, so only the last term can be one. It counts as closed and searches as you type, after the usual pause, with no warning: `"neur` searches `"neur"`, `-"dra` hides notes containing "dra". Its text is taken as typed, a trailing space included (`"fat ` marks a word edge); a backslash typed last is left out until the next character, and `\"` and `\\` inside work as usual. A quote with nothing in it yet (`"`, `-"`) is incomplete, not warned, and runs nothing new.
- **Closing an open quote**: when the user moves on with a quote open (Enter, a click on a note or anywhere else in the page, a menu, another search context, a new or duplicated one), the closing quote (the mark that opened it) is added, in the field and in the tab's saved search; a quote with nothing in it is removed. Switching to another app or window is not moving on. When the open quote's search has already run, nothing is searched again, so a click on a note still opens it.
- **Empty quoted strings**: incomplete and warned.
  - Examples: `""` and `''` → warn `Enter text inside quotes`
- **Dangling prefixes**: `+` or `-` must be directly followed by its tag or quoted text; a space after it (`- tag`) is not accepted as `-tag`. A lone prefix at the end is still being typed: incomplete, not warned. Once a term follows a prefix and a space, the field shows "In a search, + or - must be directly followed by the tag or quoted text, with no space (for example -tag)", the query is incomplete (nothing new runs), and that term is left out of the sanitized text, so it is never searched with the opposite meaning (a restored `- tag` does not run as `tag`). If such a search is still sent (pressing Enter, or adding a note while it is the search), the server's rejection appears as a polite banner with the same explanation.
- **Empty OR clauses**: leading, trailing, or consecutive `OR` is incomplete and
  warned.

## Implementation
- Verifier: `app/static/js/modules/mode-manager/services/search-syntax-service.js`
- Input enforcement + warning rendering: `app/static/js/modules/mode-manager/services/search-input-service.js`


# Search Semantics

This document describes **server-side search behavior** (what matches what).

For input grammar, normalization rules, and completeness gating, see:
- `docs/ui/search-syntax.md`

## Term Types

Search queries are a whitespace-separated list of terms.

### Tag Terms (unquoted)
- `foo` and `+foo` are equivalent (required tag).
- `-foo` excludes notes that have tag `foo`.

Tag matching uses the note’s tag-bar string (`notes.tags`) tokenized with the same
rules as the tag bar:
- Wrapper tokens (e.g. `{{foo bar}}`) contribute inner terms (`foo` and `bar`).
- `/* ... */` comment regions are ignored.

In addition, notes implicitly inherit **non-meta** tag terms from parents and referenced notes:
- A note’s effective tags include its own tags plus non-meta tags inherited through its parents and note references (`[[UUID]]`, links and embeds). A reference contributes tags from its source and that source's complete descendant subtree, including further references within the subtree. It excludes tags inherited from ancestors above the source. Children of the referencing note inherit its effective tags normally. Accepted and proposed tag contributions remain separate until combined for search.
- Tags starting with `@` (meta tags like `@monospace`) are **not** inherited.
- Tag-bar `/* ... */` comments are **not** inherited (they only affect text search for the note that contains them).

Ontology rules also add **inferred tags** before search matching:
- Implication + matcher rules are applied per note, and inferred tags are added to the effective tag set.
- See `docs/design/ontology-rules-v1.md` for the rule language and semantics.

### Untagged Notes View
- `View: Untagged Notes` is a temporary view, not tied to a search context, selected from the command palette, not an `@untagged` search token.
- Selecting it preserves the active search context and its search while temporarily showing notes whose full effective tag set has no non-meta tags. The search box is visually blank while this override is active because the preserved search context's query is not being applied.
- Inherited and ontology-inferred tags count as tags; formatting/meta tags beginning with `@` do not.
- The dismissible `Untagged Notes` pill returns to the underlying search context and restores its query in the search box. Clicking any search context or changing the search input also dismisses the temporary view.
- Changing the search input additionally resets the active search context's sort mode to Normal before executing the search.

### Notes With Files
- **Notes with Files** in the right-click menus and the palette (`Notes with Files: Images`, …) keeps a search to the matches whose own text links to or embeds an attached file, or a file of one kind (images, PDFs, Markdown files; Images also counts a picture pasted into the note), with the notes above them. Without a search it alone picks the notes. It is not a search term: a chip in the search box shows it, and a new search keeps it (`docs/ui/command-palette.md`, Notes With Files).

### Creating Notes From Search
- New notes created while a positive tag search is active are initialized from
  the positive tags and text terms in the **first clause only**. Later `OR`
  clauses are not copied into the new note.
- If an existing case-equivalent tag spelling is already common in the vault, that spelling is used for the new note. Example: searching `ml3` adds `ML3` when existing notes use `ML3`.
- If the new note already inherits a case-equivalent non-meta tag from an ancestor, the inherited tag is treated as satisfying the search and is not duplicated.

### Moving Notes During Search
- A note outdented while a search is active never leaves the results, wherever it lands (under a grandparent or as a root note). If the note matched before the move and would not match at its new place, it gets, as its own tags, the tags it misses for the part of the search (`OR` clause) it matched; it gets nothing when it still matches there, through inherited tags or another clause.
- A note shown only as context above a match (it did not match itself) keeps its tags.
- A note's own text moves with it, so a move never adds `/* ... */` comments. Undo restores both the place and the tags.
- Reordering among siblings and indenting cannot drop a note from the results, so they add nothing.

### Text Terms (quoted)
- Required text: `"some text"` or `'some text'`
- Forbidden text: `-"some text"` or `-'some text'`

Text matching is:
- Case-insensitive (`casefold`).
- Against **visible text**, extracted by stripping HTML (scripts/styles ignored).
- Also against tag-bar `/* ... */` comment text (whitespace-normalized).
- Also against the URL of a web link whose label hides it (for example a link
  pasted from a web page that shows a video title): the note is searched as
  "Video title (https://...)".
- Also against the names of files the note references (a PDF or other file shown by
  its name): `"congratulation"` finds a note holding `0025018697_CongratulationLetter.pdf`.
  Find (⌘F) finds file names in the list too.
- Also against the titles of web pages linked in the note: for each `http(s)` URL
  in the note (written out, or hidden behind a link label), the page title
  MetaList has already fetched and stored. Titles are fetched when a URL on its own
  line is first displayed, so a note matches by title once its title has been
  fetched; a title fetched later makes the note match from then on. Titles are not
  available while the vault is locked. The URL itself remains searchable.
- A space at the edge of the quotes marks a word boundary on that side: `"fat "` needs
  the word to end there (a space, punctuation or the end of the text follows), so it
  matches "fat cat" and "fat." but not "father"; `" fat"` needs it to start there, so
  it does not match "sulfate"; `" fat "` matches only the word "fat". Without edge
  spaces a term matches anywhere, also inside words (`"fat"` matches "father").

### Super Tag Searches
Super tags carry values (`jogging:miles=3`, `drug:dosage=10mg`; see Super Tags in
`help-tags`). Call them super tags when explaining them. A search compares a note's own values:

- `jogging:miles>2`: notes whose `jogging` has `miles` over 2. Operators: `>`, `<`,
  `>=`, `<=`, `=`.
- `jogging:miles?`: notes carrying `jogging` themselves (not only inheriting it) with no
  `miles`: incomplete data to fill in.
- `jogging:miles`: notes whose `jogging` has `miles`, with any value.
- `date>=2024-01`: a valued tag's own value (`date=2024-03-05`); `>`, `<`, `>=`, `<=`.
  (`date=2024-01` stays the valued tag it has always been.)
- `:version`, `:version=0.24.5`, `:version>0.24`: the property on any tag. `:version?` is
  refused (a missing property needs its tag). A bare `:` suggests the vault's property names.
- `-` excludes, spaces combine, `OR` separates clauses, as for tags:
  `jogging:miles>2 jogging:duration<40`, `jogging -jogging:miles>10`.
- One property per term: `jogging:miles>2:duration<40` is refused with how to write it.
- Values are compared by kind: numbers, dates (`2024-01` is its first day; a year alone,
  `2026`, is a number), date-times (`2024-01-15T10:30`), times of day (`10:30`, `22:30`,
  `10:30pm`, `10am`; `12am` is midnight) and text (any case). A value of another kind is
  skipped: `miles>2` ignores `miles=far`.
- Units are labels: `drug:dosage>5mg` compares only `mg` values; `drug:dosage>5` compares
  every unit (`10mg`, `10kg`, `10`), which shows when a search should name one.
- Values belong to the note they are written on: a child of a 3-mile run inherits
  `jogging`, never `miles=3`.
- A note added while such a search is active gets the term's tag; an `=` term also gives
  it the value (`jogging:miles=3` adds `jogging:miles=3`). Other comparisons name no
  value, so the new note has the tag only.
- **Through implications:** a term about a tag also reads the values of every tag that
  implies it, synonyms included. With `jogging => exercise`, `exercise:miles>2` finds
  `jogging:miles=3`; with `trail-run => jogging`, `trail-run:miles=5` too. Ask at any
  level and find every specific instance. A note matches if any one value meets the
  term: `jogging:miles=1 cycling:miles=10` matches both `exercise:miles>2` and
  `exercise:miles<2` (give each activity its own note). `exercise:miles?` finds notes
  carrying a tag that implies `exercise` (or `exercise` itself) without `miles` on any
  of them. Only implication rules count, not text rules. While a vault is locked the
  rules cannot be read, so a term reads only its own tag.
- **MAX and MIN:** `jogging:miles=MAX` keeps the note (or notes, on a tie) with the
  largest `miles` among the notes the rest of the clause finds; `=MIN` the smallest.
  `jogging:miles=MAX date>=2026-01` is the longest run since January, `run:at=MAX` the
  latest. Through implications too (`exercise:miles=MAX`). `-jogging:miles=MAX` leaves
  the longest out. Values of several kinds: the kind most values are counts (`far` is
  skipped among numbers); units are labels and do not count. Exact capitals, as `OR`:
  `max` is text. They go after `=` only.
- **Suggestions:** after `exercise:` the search box suggests property names used with
  `exercise` and with the tags implying it (`miles` from `jogging`), most used first;
  after a number (`drug:dosage>5`) the units used with that property (`5mg`); after `=`,
  `MAX` and `MIN`. The list shows only the name, unit or keyword. Picking one earns no
  activity credit.

### Stats Figures
- `@sum:calories>2000` finds notes whose stats show a calorie total over 2000; also `@count:`, `@avg:`, `@min:`, `@max:`. Only notes showing that figure match (`@sum=calories`, or a plain `@sum` covering calories), never their parents; `@stats` is not searched. `@sum:calories` finds every such note; `=MAX`/`=MIN`, `-` and `OR` work as for super tags. The figure is the footer's, as shown; a dash never matches, 0 does (`@sum:calories=0`: days with nothing logged). A found note shows the notes under it. `@sum>2000` is refused: name a property. After `@sum:` the box suggests property names.

### UUID Terms
- UUIDs in positive terms are treated as direct note targets (including when pasted as `[[UUID]]`).
- This is additive with normal tag/text matching.

## Matching Rules

Terms within a clause are AND-ed:
- A note must contain **every required tag**.
- A note must contain **every required text term** as a substring.

Forbidden terms exclude matches from their own clause:
- A note must contain **none** of the forbidden tags.
- A note must contain **none** of the forbidden text substrings.

Exact uppercase, unquoted `OR` separates clauses, and a note matches if any
complete clause matches. For example:
- `A B C OR D E` means `(A AND B AND C) OR (D AND E)`.
- `A OR B OR C D` means `A OR B OR (C AND D)`.
- `A -X OR B` means `(A AND NOT X) OR B`; `-X` does not exclude a note that
  matches the `B` clause.

Leading, trailing, and consecutive `OR` operators are invalid. Lowercase `or`
is an ordinary tag term, and quoted `"OR"` is an ordinary text term. Uppercase
`OR` is reserved across tag-entry paths and cannot be created as a tag.

## Tree Inclusion

The UI renders a tree, so search returns context:
- All matching notes are included.
- All ancestors of a matching note are included (so matches are reachable).
- Non-matching descendants are not promoted to full matches just because an ancestor matched.
- Within a visible root, excluded child/sibling branches are rendered as redacted placeholders on the client (fixed-height grey lines) rather than disappearing.
- Clicking a redacted placeholder reveals the whole redacted set within that note's local subtree in the current search context; the revealed notes stay visually dimmed so excluded search context is still obvious.
- For UUID-direct targeting specifically:
  - The target note is included.
  - Its ancestors are included.
  - Its descendants are included and not redacted.
  - Non-matching sibling branches remain redacted according to normal search behavior.

## Windowing / Infinite Scroll

Results are still **windowed by root notes**:
- The server sends an initial window of matching roots.
- Scrolling near the end triggers additional root windows.

## Embedded References and Search

Note references (`[[UUID]]`), links and embeds alike, participate in tag inheritance:
- Non-meta tags on the source or its descendants supply required/forbidden tag hits for the host and its children, including through chains of references. For `foo → bar → baz`, a reference to `bar` matches tags on `bar` and `baz`, but excludes tags inherited from `foo`. Searching for a tag on `baz` includes the reference host; an expanded embed displays the full `bar → baz` subtree. Link-mode references retain their compact rendering.
- Canonical notes still inherit their own ancestors' tags. The referencing host also retains inheritance from its own parents. Source text does not supply required/forbidden quoted-text hits; source meta tags and comments do not pass through references.
- Subtree/reference cycles converge from direct tags, without importing parent inheritance. Removing a tag/reference clears stale contributions, including within cycles. An explicit reference to an ancestor still contributes that referenced subtree's tags.
- Inherited-tag metadata, suggestions, and Untagged Notes use the same computed tags. Ontology inference continues to run per note after inheritance.
- Updates are maintained in memory on edits, tag changes, moves, deletion, and restoration; collapse/expand does not rebuild tag inheritance.
