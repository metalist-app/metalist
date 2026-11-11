# Search Semantics

Built 2026-10-30: the `@datetime` tag, which dates a root note for the Created date range (`docs/ui/tag-bar.md`, Date meta tag). Summaries of a property over the notes found were dropped (2026-10-30) and belong to charts (`docs/future-plans/charts.md`).


This document describes **server-side search behavior** (what matches what).

For input grammar, normalization rules, and completeness gating, see:
- `docs/ui/search-syntax.md`

## Term Types

Search queries are a whitespace-separated list of terms.

### Tag Terms (unquoted)
- A term ending in `/` is a folder (built 2026-11-11, `docs/ready-to-build/folder-tags-in-search.md`): `Projects/` finds notes in `Projects/` and in every folder below it (`Projects/Client-A/`), `-Projects/` leaves them all out, whether or not the folder tree is shown. It is the one exception to exact matching: `Projects/` doesn't find the plain tag `Projects/notes`, and `work` still doesn't find `work-archive` (`SearchIndex._search_term_posting_locked`). Ready to build (agreed 2026-11-11): folder terms in one clause add results (`A/ B/ @todo` finds to-dos in A or B), every other term still narrows, and a new note gets every folder of the clause: `docs/ready-to-build/folders-tab-and-multiple-folders.md`.
- `foo` and `+foo` are equivalent (required tag).
- `-foo` excludes notes that have tag `foo`.
- A tag with a value, `name=value` (`@code=python`, `@size=2`), can be searched whole
  (`@code=python` finds Python notes only) or by its name alone: a tag without `=`
  also matches every `tag=value` (`@code` finds every `@code=<language>` note, `-@code`
  excludes them all, `priority` finds `priority=high`). The family is the part before
  `=`, never a shorter prefix (`@cod` finds nothing). One `=` can be typed in a search
  tag, as in the tag bar; it is never a tag's first character. Ontology rules still
  match tags exactly.

Tag matching uses the note’s tag-bar string (`notes.tags`) tokenized with the same
rules as the tag bar:
- Wrapper tokens (e.g. `{{foo bar}}`) contribute inner terms (`foo` and `bar`).
- `/* ... */` comment regions are ignored.

In addition, notes implicitly inherit **non-meta** tag terms from their parents:
- A note’s effective tags are its own plus the non-meta tags it inherits from its parents. Nothing comes through an embed (`![[UUID]]`) or a link (`[[UUID]]`): if note A embeds or links to note B and B has tag X, a search for X finds B, not A, and A isn't in B's folder or its count (the maintainer, 2026-11-03: an embed is a window onto another note, not a statement that the host is about it too; before, an embed passed its source's tags and its whole subtree's, so a search for a tag listed every note embedding the note that had it. Links stopped passing tags on 2026-10-31). Adding, removing or changing an embed or link never changes which searches, folders or counts a note is in. A note whose only tags came through an embed is now untagged. Accepted and proposed tag contributions remain separate until combined for search.
- Tags starting with `@` (meta tags like `@monospace`) are **not** inherited.
- Tag-bar `/* ... */` comments are **not** inherited (they only affect text search for the note that contains them).

Ontology rules also add **inferred tags** before search matching:
- Implication + matcher rules are applied per note, and inferred tags are added to the effective tag set.
- See `docs/design/ontology-rules-v1.md` for the rule language and semantics.

### Untagged Notes View
- `View: Untagged Notes` is a view that belongs to its search context (kept when you leave the context and come back, after a reload and in a duplicate; decided 2026-11-02, `docs/ui/state-handling.md`), selected from the command palette, not an `@untagged` search token.
- Selecting it preserves the active search context and its search while temporarily showing notes whose full effective tag set has no non-meta tags. The search box is visually blank while this override is active because the preserved query is not being applied.
- Inherited and ontology-inferred tags count as tags; formatting/meta tags beginning with `@` do not.
- The dismissible `Untagged Notes` pill returns to the search context's underlying view and restores its query in the search box. Changing the search input, `View: All Notes` and Reset Current View Filters also end it; clicking a search context does not.
- Changing the search input keeps the active search context's sort order and date range (decided 2026-11-02, `docs/ui/state-handling.md`); each ends with its chip's `×`.

### Notes With Files
- **Notes with Files** in the right-click menus and the palette (`Notes with Files: Images`, …) keeps a search to the matches whose own text links to or embeds an attached file, or a file of one kind (images, PDFs, Markdown files; Images also counts a picture pasted into the note), with the notes above them. Without a search it alone picks the notes. It is not a search term: a chip in the search box shows it, and a new search keeps it (`docs/ui/command-palette.md`, Notes With Files).

### Search Suggestions
- Search-bar tag suggestions are segment-aware for connector-separated tags.
- A suggestion must leave at least one matching note in the active `OR` clause, satisfying every completed tag, text term, and exclusion. For example, after `prediction-future`, typing `security` only suggests `computer-security` if that combination actually matches a note. Partial tag overlap alone is insufficient. Matching uses the same effective tags as search, including inheritance, references, and ontology inference. This filtering happens before personalization and the visible limit; note-tag recommendations can still propose new combinations.
- For a blank query or the first tag prefix in a query, ordered calendar-day windows promote matching tags into the first suggestion slots. The default is `[1, 7, 30]`, and the command-menu editor can add, remove, or reorder 1–365 day windows; an empty list disables personalization.
- Prefix matching happens against the complete candidate set before the visible suggestion limit is applied, so an interacted `shortcut` cannot be discarded merely because 50 unrelated tags rank above it globally and leave frequency-ranked `short-story` first.
- Case-equivalent tags are collapsed in suggestions, and the most-used spelling is shown.
- Enter and the arrow keys act only on a suggestion list built for the text in the box. While the list for what you just typed is on its way, the one on screen is for older text: Enter then closes it and keeps what you typed (it does not add a note), and the arrows wait for the new list.
- Searches themselves never earn credit. Intentional note engagements—edit selection, manual expansion, full-screen view, shell/todo command execution—increment the note's raw explicit/inherited searchable tags once per active search context and search flow. Leaving for another search context or executed search and later returning starts a new flow, so a later shell run can count again. Successfully adding explicit tags separately credits only those newly added tags; removals and case-only changes are neutral. Accepting a search suggestion by mouse or keyboard credits that selected tag once, with no engagement-flow deduplication. Clicking a search context credits each known positive tag term in its executed query once; excluded tags and quoted text are ignored. Programmatic search-context restoration/switching, collapse, search execution, hover, render, and scroll are neutral.
- After one or more completed tags, the remaining candidates (those that still leave results) are ordered by overlap with the typed tags: notes carrying both the candidate and the typed tags, divided by notes carrying either (Jaccard), then case and alphabetical tiebreaks (`SearchIndex.suggest_tag_completions`). This favors specific companions over tags common everywhere. An offline experiment found it a good compromise: ordering by specificity (lift) surfaces forgotten rare tags more often after a narrower first tag, but makes common second tags after a broad first tag cost about 1.4 more keystrokes; see `docs/design/search-suggestion-learnings.md`.
- Activity uses sparse per-calendar-day counts. A window sums the relevant daily buckets, selects its highest-count matching tag, and excludes tags chosen by earlier windows. No decay calculation or all-time score exists; in the same experiment, smooth recency decay did not beat the fixed windows. The latest 365 populated days are retained, so unused calendar days consume no buckets.
- In password-protected namespaces, all retained daily buckets live together in one authenticated encrypted payload. The database exposes only one random row UUID, ciphertext, nonce, and authentication tag—never dates, tag names, counts, queries, or changed-tag metadata.
- A typed prefix can match either the start of the full tag or the start of any connector-separated segment.
  - Example: `wor` suggests `workspaces` and `databricks-workspaces`.
  - Example: `orksp` suggests neither.
- `@` (meta) tags are suggested from the built-in list (`@markdown`, `@size=2`…) and from
  the `@` tags notes carry, with each valued tag's family: `@c` suggests `@code` and
  `@code=python`, `@code` suggests `@code=python` and `@code=javascript`. Plain tags with a
  value are suggested whole (`priority=high`), without their family name.
- The server returns at most `MAX_SEARCH_SUGGESTIONS` suggestions; the default is 20.
- This affects suggestions only; tag search matches effective tag terms exactly, except that
  a tag without a value also matches its `tag=value` family (above).

### Creating Notes From Search
- New notes created while a positive tag search is active are initialized from
  the positive tags and text terms in the **first clause only**. Later `OR`
  clauses are not copied into the new note.
- If an existing case-equivalent tag spelling is already common in the namespace, that spelling is used for the new note. Example: searching `ml3` adds `ML3` when existing notes use `ML3`.
- If the new note already inherits a case-equivalent non-meta tag from an ancestor, the inherited tag is treated as satisfying the search and is not duplicated.
- A property term with a named tag and an exact value is copied whole: `jogging:miles=3` and `book:author="Le Guin"` give the new note those tokens (before 2026-10-31 the main add-note path dropped them, and the note left its own search at once).
- **A search no new note can match refuses new notes at the top** (decided 2026-10-31), as a sorted view does: a property term in the first clause other than a named tag with an exact value (`jogging:miles>3`, `:foo="ba"`, `jogging:miles?`, bare `jogging:miles`, `=MAX`/`=MIN`, a stats term such as `@sum:calories>2000`). Enter, pasting or dropping files at the top and the command palette show the banner "New notes cannot be added in this search: a new note would not match jogging:miles>3.", and Add Note at Top is hidden in the view and note menus. Excluded terms (`-jogging:miles>3`) and later `OR` clauses never refuse. Children and siblings of nested notes are still added. Code: `findUnfillableSearchTerm` (`search-syntax-service.js`), `rootNoteCreationBlockReason` (`root-note-creation-service.js`).

### Moving Notes During Search
- A note outdented while a search is active never leaves the results, wherever it lands (under a grandparent or as a root note). If the note matched before the move and would not match at its new place, it gets, as its own tags, the tags it misses for the part of the search (`OR` clause) it matched; it gets nothing when it still matches there, through inherited tags or another clause.
- A note shown only as context above a match (it did not match itself) keeps its tags.
- A note's own text moves with it, so a move never adds `/* ... */` comments. Undo restores both the place and the tags.
- Reordering among siblings and indenting cannot drop a note from the results, so they add nothing.

### Comment Terms

Built 2026-11-11 (the maintainer: "so I can find everything that got /*help*/ added").

- `/*help*/` finds the notes whose own tag-bar `/* ... */` comments contain `help`: in any case, anywhere in a comment, also inside words. `/*help*/` finds `/*help*/`, `/*Help me*/` and `/*helpful links*/`, never a note that only says "help" in its text or in a tag's value (`title="help"`). A note's comments are its own: nothing inherits them.
- `-/*help*/` leaves those notes out; `+` is dropped, as for quoted text. Spaces inside are kept (`/*help me*/`), runs of them read as one.
- No tag starts with `/` or holds `*`, so `/*…*/` in a search is always a comment. One not yet closed searches as if closed while typing (`/*hel`), as an open quote does; `/* */` asks for the words.
- Not highlighted in notes: the match is in the tag bar.
- A note made, pasted or outdented under the search gets the comment itself (`/*help*/`) unless one of its comments already contains it, as a quoted phrase gives `/*phrase*/`.
- Implementation: `parse_search_query` (`app/services/search_query.py`, comment terms kept with the quoted phrases as `/*words*/`), `SearchIndex._text_term_matches_locked` and `comment_term_matches` (`app/services/text_terms.py`), the search box's `readCommentTerm` (`search-syntax-service.js`). Tests: `tests/unit/test_comment_search_terms.py`, `tests/unit/search_comment_terms.test.mjs`.

### Text Terms (quoted)
- Required text: `"some text"` or `'some text'`
- Forbidden text: `-"some text"` or `-'some text'`
- An open last quote searches as typed, before the closing quote: `"neur` searches `"neur"`, a trailing space included (`docs/ui/search-syntax.md`, Completeness).

Text matching is:
- Case-insensitive (`casefold`).
- Against **visible text**, extracted by stripping HTML (scripts/styles ignored).
- Also against tag-bar `/* ... */` comment text (whitespace-normalized).
- Also against the URL of a web link whose label hides it (for example a link
  pasted from a web page that shows a video title): the note is searched as
  "Video title (https://...)".
- Also against the names of files the note references (`[[id]]` or `![[id]]`, which
  MetaList shows by the file's name): `"congratulation"` finds a note holding
  `0025018697_CongratulationLetter.pdf`. Names are read from the files database the
  first time a note is indexed (in an encrypted vault, once it is unlocked) and kept in
  memory (`FileRegistry.referenced_file_names`); a file's name never changes after upload.
- Also against the words of the emails the note references (`.eml` files, docs/ui/references.md,
  "Email files"): their subject, From, To, Cc, body (an HTML body as its text) and attachment
  names (2026-10-29). `app/services/email_search_text.py` reads each email once, through the
  file registry's reader (`FileRegistry.read_stored_file`, which `file_storage` installs), and
  keeps its words in a sensitive cache, emptied when the vault locks; only files whose kind can
  be an email (`other`, `text`) are read. An email's content never changes in place.
- Also against the text of the PDFs the note shows (built 2026-11-01; Word and RTF to follow):
  each PDF's text is extracted once in the background when it arrives (or after login, for
  files already in MetaList), up to 5 MB, and kept encrypted with the file beside a bloom filter
  of its 4-letter pieces (`file_texts`, files database version 13). At login only the filters
  are loaded; a quoted term of 4 or more characters reads a file's text only when its filter says
  it may be there, a shorter one reads every file's, so the results are those of reading every
  file whole. Text read stays in a 64 MB cache emptied when the vault locks. A PDF not read yet
  (just added, just after login) matches by name only until it is; an open view doesn't change
  when that happens, the next search finds it. A scan or a PDF that can't be read matches by
  name only. `app/services/file_text_search.py`; tests: `tests/unit/test_file_text_search.py`.
  Where a required phrase is in a file's text, a snippet of it shows under the file's card (see
  docs/ui/references.md, "File text snippets"). Find in the list (`Cmd+F`) finds file text too (docs/ui/find.md, "Inside files").
- Also against the titles of web pages linked in the note: for each `http(s)` URL
  in the note (written out, or hidden behind a link label), the page title
  MetaList has already fetched and stored. Titles are fetched when a URL on its own
  line is first displayed, so a note matches by title once its title has been
  fetched; a title fetched later makes the note match from then on. Titles are not
  available while the namespace is locked. The URL itself remains searchable.
- A space at the edge of the quotes marks a word boundary on that side: `"fat "` needs
  the word to end there (a space, punctuation or the end of the text follows), so it
  matches "fat cat" and "fat." but not "father"; `" fat"` needs it to start there, so
  it does not match "sulfate"; `" fat "` matches only the word "fat". Without edge
  spaces a term matches anywhere, also inside words (`"fat"` matches "father").

### Highlighted Phrases
The required quoted phrases of the search, from every `OR` clause, are marked in soft
yellow (a dark gold in the dark theme) wherever they occur in the notes list: in each
note's text, in embedded notes, in a matching note's children shown with it, and in
tag-bar comments. A mark follows the matching rules above (any case, also inside words,
edge spaces for word edges); a phrase running through formatting or across a line
break is one mark. Excluded phrases and tags are never marked.

- The note being edited is not marked; leaving edit mode marks it again.
- Full screen, floating windows, export, print and copied text are not marked.
- Marks are painted over the text (`search-highlight-service.js`, the CSS Custom
  Highlight API): no note's HTML changes, and nothing moves or scrolls.
- The server sends the phrases with each view (`searchHighlightPhrases`, its own
  reading of the search), so the browser never parses the search itself.
- Phrases the browser cannot see are not marked: a web page title or a hidden link
  URL the note matched by.

### Super Tag Searches
Super tags carry values (`jogging:miles=3`, `drug:dosage=10mg`; see Super Tags in the tag
bar's reference and `docs/design/tag-properties.md`). A search compares a note's own values:

- `jogging:miles>2`: notes whose `jogging` has `miles` over 2. Operators: `>`, `<`,
  `>=`, `<=`, `=`.
- `jogging:miles?`: notes carrying `jogging` themselves (not only inheriting it) with no
  `miles`: incomplete data to fill in.
- `jogging:miles`: notes whose `jogging` has `miles`, with any value.
- `date>=2024-01`: a valued tag's own value (`date=2024-03-05`); `>`, `<`, `>=`, `<=`.
  (`date=2024-01` stays the valued tag it has always been.)
- `:version`, `:version=0.24.5`, `:version>0.24`, `-:version`: the property on any tag
  (built 2026-10-29): every tag carrying `version` counts, units and MAX/MIN as on a tag.
  There is no tag to read upward from, so implications play no part. `:version?` is
  refused ("A search for a missing property needs its tag"). A bare `:` suggests the
  property names used anywhere, most used first; then units, MAX and MIN as after a tag
  (`tag_properties.parse_tagless_property_term`, `SearchIndex._property_tags_locked`).
  Before, the search box had read `:version` as the tag `version`. Tests:
  `tests/unit/test_tagless_property_search.py`, `tests/unit/search_syntax_service.test.mjs`.
- `-` excludes, spaces combine, `OR` separates clauses, as for tags:
  `jogging:miles>2 jogging:duration<40`, `jogging -jogging:miles>10`.
- **Chained conditions** (built 2026-10-31): `book:title="Dune":year>1960`,
  `:foo="bar":baz>3:zed<100`. One tag on the note meets every condition, where separate
  terms may each be met by a different tag: `:foo="bar":baz>3` finds `x:foo=bar:baz=5`,
  not `x:foo=bar y:baz=5`; with `jogging => exercise` and `cycling => exercise`,
  `exercise:miles>2:duration<40` finds `jogging:miles=3:duration=30`, not
  `jogging:miles=3 cycling:duration=30`. A chain takes comparisons, `=` and a bare name
  (`jogging:miles>2:duration`); `?`, `MAX` and `MIN` go in terms of their own, each
  property is named once, and stats terms compare one figure. `-` leaves out only notes
  where one tag meets them all. Ontology rules keep one property per condition.
- Values are compared by kind: numbers, dates (`2024-01` is its first day; a year alone,
  `2026`, is a number), date-times (`2024-01-15T10:30`), times of day (`10:30`, `22:30`,
  `10:30pm`, `10am`; `12am` is midnight) and text (any case). A value of another kind is
  skipped: `miles>2` ignores `miles=far`.
- Units are labels: `drug:dosage>5mg` compares only `mg` values; `drug:dosage>5` compares
  every unit (`10mg`, `10kg`, `10`), which shows when a search should name one.
- Values follow their tag (agreed 2026-11-01): a search reads a note's own values and
  those it inherits from its parents, as tags are, never through embeds or links (2026-11-03). The nearest
  value wins: a child of a 3-mile run has `miles=3`, unless it writes its own
  (`jogging:miles=1`); a nearer ancestor's value hides a farther one's. So
  `jogging:miles>2 knee` finds the knee note under a 3-mile run (a note embedding the run
  doesn't match `jogging:miles=3`), and an import's search (`imported:source=…:at=…`) shows every
  note under the imported files, not grey bars. `jogging:miles?` (a missing value) and
  stats figures (`@sum:…`) stay the note's own; `=MAX` and `=MIN` keep the notes with the
  extreme value, a run and the notes under it. Before, a value matched only the note it
  was written on. Implementation: `SearchIndex._tree_clause_note_ids` reads
  `NoteStore._read_inherited_values` outside the index's lock, as stats figures are read;
  tests: `tests/unit/test_inherited_values_search.py`.
- A note added while such a search is active gets the term's tag and value
  (`jogging:miles=3` adds `jogging:miles=3`). A search whose term names no value a new
  note could carry (`jogging:miles>2`) refuses new notes at the top (Creating Notes From
  Search above); a child added under a result gets the tag only.
- **Quoted values** (built 2026-10-31): `author="Ursula Le Guin"` and
  `book:title="Dune: Messiah"` hold spaces and colons. A quoted value is a text match
  inside the value, like a quoted text search (`:foo="ba"` finds `foo=bar`, `foo=bag` and
  `foo=aba`; `author="Ursula"` finds Ursula Le Guin); a bare value is exact. Quotes never
  change a value: `zed:foo="asdf-jkl"` and `zed:foo=asdf-jkl` are the same tag.
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
  the values notes give the property, quoted when needed, after `MAX` and `MIN` when the
  property has a number, date or time value (a bare partial matches a value's start, a
  quoted one anywhere in it). The list shows only the name, unit or keyword. Picking one earns no
  activity credit.

### Stats Figures
Built 2026-10-28. The stats tags show figures of a note's subtree (`docs/ui/content-formatting.md`,
Stats of a subtree); a search compares them in the super tag form, with a stats tag as the tag
(`app/services/subtree_stats.py` `stats_figure_values`, `SearchIndex._stats_clause_note_ids`):

- `@sum:calories>2000`: notes whose `@sum` shows a calorie total over 2000. The same for
  `@count:calories>3`, `@avg:calories<600`, `@min:calories<100`, `@max:calories>1000`.
- **Only notes showing that figure match:** a note carrying `@sum=calories`, or a plain `@sum`
  that shows calories (it covers every property with numbers under the note). The figure is
  never computed for other notes, so the month and the log above a day never match. `@stats`
  is not searched this way: a note with only `@stats` doesn't match `@sum:calories>2000`.
- `@sum:calories` with no comparison finds the notes showing that figure, as `jogging:miles`
  does. `-` excludes, spaces combine, `OR` separates clauses; `=MAX` and `=MIN` keep the
  largest and smallest figure among the notes the rest of the clause finds
  (`@sum:calories=MAX` is the biggest day).
- **The figure as shown:** counted as the footer counts (own and descendants' values, never
  inherited, never through links or embeds; average, min and max per note), rounded as it
  shows. Units as for values: `@sum:fat>10g` compares the grams total only. A dash never
  matches: a day with no meals has no average. A 0 is a number: `@sum:calories=0` finds the
  days nothing was logged in.
- **A found note shows the notes under it** (the meals that make up the day), as a tag search
  shows a found note's children, which inherit its tags.
- A property and a number are required: `@sum>2000`, `@sum:calories?` and
  `@sum:calories>lots` are refused with how to write the term. `@sum=calories` alone stays a
  tag search.
- Live: an edit under a found note changes its figure, and the next refresh shows whether it
  still matches. A note added while such a search is active gets nothing from it.
- **Suggestions:** after `@sum:` the search box suggests the properties notes carry the tag for
  (`@sum=calories`), then every property with numbers in the vault, most used first; after
  `=`, `MAX` and `MIN`. Tag suggestions read the rest of the clause without the stats terms.

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
- Within a visible root, excluded child/sibling branches are rendered as redacted placeholders on the client (fixed-height grey lines) rather than disappearing. A grey line shows nothing of what the note holds: no text, link icon, checkbox, picture or embed (fixed 2026-10-31: those showed through where they started at the note's top; the search-highlight browser suite's grey bars case).
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

Embeds (`![[UUID]]`) and links (`[[UUID]]`) pass no tags (2026-11-03; links since 2026-10-31):
- A search for a tag finds the note that has it and the notes below it, never a note embedding or linking to one. `-tag` doesn't leave out a note embedding a note with the tag. An embed in a matching note still shows its source and children; a search for the source's tag finds the source.
- The host's own content still counts: an embedded picture file makes it `@image`, Notes with Files reads its own references, and quoted text search reads its own text (never an embed's).
- Super tag values follow tags: only a note's own and its ancestors' (Super Tag Searches).
- Inherited-tag metadata, suggestions, folder membership and counts, and Untagged Notes use the same computed tags. Ontology inference runs per note after inheritance.
- Updates are maintained in memory on tag changes and moves (a note and the notes below it); editing a note's text, collapse/expand and deletion recompute nothing. Implementation: `NoteStore._propagate_inherited_tag_terms_locked` (parents first); tests: `tests/unit/test_reference_tag_inheritance.py`, `tests/unit/test_inherited_values_search.py`.
