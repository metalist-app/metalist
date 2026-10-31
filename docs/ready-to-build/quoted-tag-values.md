# Tag values with spaces, in quotes (decided)

**Status:** Agreed with the maintainer 2026-10-30. Ready to build: step 1a of `docs/ready-to-build/import-export-launch.md`, right after Unicode tags and before the Obsidian import. Filed from `docs/inbox/2026-10-30-quoted-tag-values.md` on 2026-10-30 (see "Found when filed").

Written from a read-only look at the repo. Check the code references before relying on them.

---

## 1. The rule (as proposed)

- A value can be quoted to hold spaces: `author="Ursula Le Guin"`, `city="New York"`, `book:title="A Wizard of Earthsea"`.
- Quotes only in values, never in tag or property names; a value without spaces never needs them.
- A `"` directly after `=` (or, in a search comparison, after `<`, `>`, `<=`, `>=`; decided 2026-10-30) opens the value, which runs to the closing quote. `author="Ursula Le Guin"` is one tag with a value; `author "Ursula Le Guin"` (with a space) is a tag plus a quoted text search, as today.
- The same rule in every reader, browser and server: the tag bar tokenizer, search syntax and property comparisons, the ontology rule parser, paste/dictation cleanup, AI tag proposals, and the export's hidden metadata.
- The Obsidian import writes frontmatter values with spaces as quoted values instead of dashes.

Why, beyond the import: names, titles and places come up in one's own notes, and dashes lose information: `Jean-Paul Sartre` and `Jean Paul Sartre` would both become `Jean-Paul-Sartre`.

## 2. Three details added

1. **An open value quote behaves like an open text quote** (`docs/ui/search-syntax.md`, "Open quotes"). In search, `author="Ursula Le` at the end of the query counts as closed and searches as you type. When the user does something else with it still open (Enter, leaving the field, switching search contexts, clicking a note), the closing quote is added to the field and the saved query; an empty value quote (`author="`) is removed rather than closed into `""`. In the tag bar, leaving the token with the quote open closes it the same way. Use the same code path as text quotes where possible: one quote rule.
2. **Escapes inside a quoted value: `\"` for a quote, `\\` for a backslash** (`title="The \"Best\" Book"`), the same escapes search already allows inside quoted text (`docs/ui/search-syntax.md`, "Escapes inside quoted text").
3. **Double quotes only.** Search accepts `'…'` for text, but a single quote must not open a value: it would trip on apostrophes (`author=O'Brien`).

## 3. Left to you

- How the tag bar displays a quoted value when not editing (with its quotes, or as text with spaces). Keep the quotes when editing.

## 4. Done when

1. `author="Ursula Le Guin"` saves as one tag `author` with that value; searching `author="Ursula Le Guin"` finds the note, and `author="Ursula"` doesn't (exact value), unless property comparisons say otherwise.
2. `book:title="A Wizard of Earthsea"` works as a super tag property in the tag bar, search and ontology rules.
3. Typing `author="Ursula Le` in search narrows as you type; leaving the field gives `author="Ursula Le"`; `author="` alone is removed.
4. `title="The \"Best\" Book"` round-trips through saving, search and the export's hidden metadata.
5. `author=O'Brien` is an ordinary value; `author='Brien` doesn't open a quoted value.
6. `author "Ursula Le Guin"` is still a tag plus a text search.
7. Tests cover 1–6 in every reader listed in §1; `docs/ui/tag-bar.md`, `docs/ui/search-syntax.md` and `docs/design/tag-properties.md` describe quoted values.

## Found when filed (2026-10-30)

- **The references hold:** `docs/ui/search-syntax.md` has "Open quotes" (Completeness + Warnings) and "Escapes inside quoted text" (Text Terms). Today `"` is a disallowed tag character in the tag bar (`tag-syntax-service.js` `TAG_CONTAINS_DISALLOWED`) and in rules (`tag_ontology.py` `_DISALLOWED_TAG_CHARS`), so no stored tag contains a quote: nothing to migrate.
- **The server splits tag strings on whitespace in several places, not only in the tag-bar tokenizer.** `search_index.py` reads tags through `_tokenize_tag_bar`, but `content_formatting.py:1736` (`tags.split()`), `snapshot.py:1116` (`rec.proposed_tags.split()`) and the hydration fast path (`docs/AI-SUMMARY.md`: "plain tag strings bypass the tag-bar scanner via `str.split()`") split directly, and so may others. Each would cut `author="Ursula Le Guin"` into three pieces. **Find every place a tag string is split** (server and browser) and route it through one quote-aware tokenizer; keep the fast path fast (a tag string without `="` can still use `str.split()`).
- **Super tag properties split at "a colon followed by a letter"** (`docs/design/tag-properties.md`; `split_property_segments` in `tag_properties.py`, `splitPropertySegments` in `tag-syntax-service.js`). Inside a quoted value it must not: `book:title="Dune: Messiah"` is one value.
- ~~Quotes after a comparison~~ **Decided 2026-10-30:** a quote straight after `<`, `>`, `<=` or `>=` opens a value too, as after `=`: `author>"M"`, `book:title<="N"`. The rule is "a quote straight after an operator opens a value".
- **Left to the implementer (§3):** how the tag bar shows a quoted value when not editing; it is shown at the early look.
