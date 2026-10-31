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
- Bracket wrappers (`[foo]`, `{foo}`, `((foo))`) are **not** part of search syntax.

### Super Tag Searches
- `jogging:miles>2`, `jogging:miles<=5mg`, `jogging:miles=3`, `jogging:miles?`, `jogging:miles`,
  `date>=2024-01`, with an optional `-` or `+` before them.
- The tag comes first; a property name starts with a letter; a value may contain `:`
  (`run:start>10:30pm`) but not `<`, `>`, `?` or `=`.
- Or no tag: `:version`, `:version=0.24.5`, `:version>0.24` (a property on any tag), but
  not `:version?`.
- An unfinished term does not run: `jogging:` and `jogging:miles>` while typing. Once a
  space follows it, the warning says how to finish it ("Name a property after the colon",
  "Write a value after >"). A term with two properties says "Search one property per term".
- Semantics: `docs/ui/search-semantics.md` (Super Tag Searches).

### Text Terms
A text term is a quoted string using either quote character, as long as the opener and closer match:
- Double-quoted: `"some text"`
- Single-quoted: `'some text'`
- Negated forms: `-"some text"`, `-'some text'`
- Quoted text, tags and property names may use any script (`"naïve"`, `日記:時間>2`; since 2026-10-30, before which non-ASCII characters were dropped, so `"naïve"` searched for `nave`). A search is kept in one Unicode form and matches note text in either form of an accented letter (`docs/ui/tag-bar.md`, Whitespace + Tokens).

**Planned (decided 2026-10-30):** a quote straight after `=` opens a tag's value, not a text term: `author="Ursula Le Guin"` is one tag with that value, `author "Ursula Le Guin"` a tag plus a text search (`docs/ready-to-build/quoted-tag-values.md`).

Escapes inside quoted text (backslash approach):
- Within `"..."`: allow `\\` and `\"`
- Within `'...'`: allow `\\` and `\'`

Searching for quote characters without escaping:
- Search for a literal `"`: use single quotes: `'"'`
- Search for a literal `'`: use double quotes: `"'"`

## Normalization
- Runs of whitespace are normalized to single spaces.
- Leading/trailing whitespace is trimmed, except the text of an open last quote, which keeps its trailing space.
- The verifier actively rewrites the input while typing (cursor/selection is preserved).

## Pasting Dictated Text
- Pasting (never typing) cleans up dictated text, for example from Superwhisper: `Neural network, neural network. Neural-Dash Network.` becomes the existing tag `neural-network`. Punctuation and filler words are dropped, spoken "dash"/"hyphen"/"underscore"/"slash" join words, the longest run of words matching an existing tag becomes that tag (spelled as used most often, also when the tag is one word: "to do" gives `todo`), "at" before a built-in meta tag gives that meta tag ("at to do" gives `@todo`), "or" becomes `OR`, the exclusion phrase ("minus" by default) excludes the next term, and the quote phrases ("quote … end quote" by default; all set in Dictation Settings) make a text search. Words matching no tag are dropped. A spoken word that is a tag stays that tag. One undo restores the pasted text. Full rules: `docs/ui/dictation-paste.md`.

## Completeness + Warnings
The verifier produces:
- `normalizedText`: the normalized query string.
- `sanitizedText`: only complete terms, an open last quote closed: what runs.
- `closedText`: the normalized text with an open last quote closed (or removed when empty): what the field holds once the user moves on (`closeOpenSearchQuote` in `search-events.js`).
- `endsInOpenQuote`: whether the last term is an open quote.
- `isComplete`: whether the full query is syntactically complete.
- `warningMessage`: user-facing warning text (or `null`).

Rules:
- **Open quotes**: an open quote reaches the end of the query, so only the last term can be one. It counts as closed and searches as you type, after the usual pause, with no warning: `"neur` searches `"neur"`, `-"dra` hides notes containing "dra". Its text is taken as typed, a trailing space included (`"fat ` marks a word edge); a backslash typed last is left out until the next character, and `\"` and `\\` inside work as usual. A quote with nothing in it yet (`"`, `-"`) is incomplete, not warned, and runs nothing new.
- **Closing an open quote**: when the user moves on with a quote open (Enter, a click on a note or anywhere else in the page, a menu, another search context, a new or duplicated one), the closing quote (the mark that opened it) is added, in the field and in the search context's saved search; a quote with nothing in it is removed. Switching to another app or window is not moving on. When the open quote's search has already run, nothing is searched again, so a click on a note still opens it.
- **Empty quoted strings**: incomplete and warned.
  - Examples: `""` and `''` → warn `Enter text inside quotes`
- **Dangling prefixes**: `+` or `-` must be directly followed by its tag or quoted text; a space after it (`- tag`) is not accepted as `-tag`. A lone prefix at the end is still being typed: incomplete, not warned. Once a term follows a prefix and a space, the field shows "In a search, + or - must be directly followed by the tag or quoted text, with no space (for example -tag)", the query is incomplete (nothing new runs), and that term is left out of the sanitized text, so it is never searched with the opposite meaning (a restored `- tag` does not run as `tag`). If such a search is still sent (pressing Enter, or adding a note while it is the search), the server's rejection appears as a polite banner with the same explanation.
- **Empty OR clauses**: leading, trailing, or consecutive `OR` is incomplete and
  warned.

## Implementation
- Verifier: `app/static/js/modules/mode-manager/services/search-syntax-service.js`
- Input enforcement + warning rendering: `app/static/js/modules/mode-manager/services/search-input-service.js`
