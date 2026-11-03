# Tags

Use this reference to explain MetaList accurately. It describes user capabilities,
not permission or tools for you to execute every operation. You can answer and
request one supported menu/dialog opening. You cannot submit a form, change
settings, run a shell command, or mutate notes through this help response. Do not
claim that you inspected current notes or settings: none are supplied here.
Prefer user-facing steps over implementation details. If the reference does not
answer a question, say what is unknown; do not invent syntax or controls.

Sources: docs/ui/tag-bar.md

Tag relationships (implications, synonyms, rule syntax, and renaming or deleting
a tag in Edit Tag Relationships) are in the ontology help topic. Built-in `@` tags
(formatting, renderers, `@todo`, `@datetime`) and Add Style are in the
meta-tags topic; what the tag bar suggests, and why, is in the tag-suggestions topic.

## Overview
- Each note has a tag string (`notes.tags`) that round-trips through the view snapshot (`snapshot.notes[*].tags`).
- The tag bar editor enforces a small grammar in the browser so invalid characters/sequences are removed as you type.
- When leaving the tag bar (Tab toggle or click-away) the input is **sanitized**: incomplete/broken items are removed.
- Pasting (never typing) dictated text into the tag bar turns it into tags ("neural network at to do" gives `neural-network @todo`). The full rules are in the dictation help topic.
- When tags are shown in the note list, one line of tags shares the note's existing row height; the row grows only when its tags wrap onto additional lines.

## Whitespace + Tokens
- Outside of `/* ... */` comments, tags are separated by whitespace.
- Double-click selects an entire tag, including `@`, connectors such as `-`, `_`, `.`, `/`, and assignment values such as `@size=2.0`. Inside a scoped wrapper, it selects the individual tag without the wrapper. Comments retain ordinary word selection. The search input uses the same interaction with its own query grammar.
- Runs of whitespace are normalized to single spaces.
- Wrapper tokens may contain internal spaces (e.g. `{{@red @monospace}}`), which are preserved (normalized) inside the wrapper. This means a wrapper token can contain multiple tags.
- A normal tag token allows letters in any script and emoji (`Café`, `日記`, `🏃`) and disallows: `: , " \\ > < [ ] { } ( ) * | ; ~ ``. The one exception is `:` making a super tag (below). Invisible characters (zero-width spaces, direction marks) are dropped, any space separates tags, case is ignored in every script (`Straße` and `STRASSE` are one tag), and an accented letter typed or pasted in either form is the same letter.
- One `=` is allowed inside regular or meta tags when valid tag characters occur on both sides (for example `abc=xyz` or `@size=2.0`). It cannot appear at the start/end, and multiple `=` characters are removed during normalization.
- Tag tokens also cannot start with `-`, `+`, or `/`.
- Exact uppercase `OR` is reserved as the search disjunction operator and cannot
  be saved as a tag, including inside a wrapper. Lowercase `or` and mixed-case
  variants remain valid tags.

## Super Tags
A super tag is a tag carrying values, its properties, written in the tag bar as one token: `jogging:miles=3`, `jogging:miles=3:duration=30`, `drug:dosage=10mg`, `run:start=10:30pm:miles=3`. Call them super tags when explaining them; the values are its properties. Design and later steps: `docs/design/tag-properties.md`.
- The tag is everything before the first `:`; each `:name=value` after it is a property. Property names start with a letter.
- A colon followed by a letter starts the next property; any other colon belongs to the value, so times and date-times work: `start=10:30pm`, `at=2026-10-23T10:30`.
- A value with spaces, or a colon before a letter, is quoted: `author="Ursula Le Guin"`, `book:title="Dune: Messiah"`, `title="The \"Best\" Book"`. A `"` straight after `=` opens the value, which runs to the closing quote; a quote anywhere else opens nothing (`author=O'Brien` needs none). Leaving the tag bar with a value still open closes it; an empty one (`author=""`) leaves `author`. Quotes never change a value: `foo="asdf-jkl"` is `foo=asdf-jkl`. Scopes and `@` tags take no quoted values. A unit, if any, is written after the number with no space (`10mg`, `10miles`).
- While typing, properties stay as typed. On leaving the tag bar, a property without a value (`jogging:miles=` or `jogging:mi`) is removed, and so is a property repeated in the same token (`jogging:miles=3:miles=5` keeps `miles=3`).
- A note carries a super tag once. Adding the same tag again (`jogging` beside `jogging:miles=3`) is refused: the tag bar says "jogging is already on this note" and the second one is not saved. Put all of a tag's properties in its one token instead. Plain tags are unaffected (`priority=high priority=low` stays).
- Meta tags (`@size=2`) and tags inside scopes (`{{...}}`) have no properties; their colons are removed as before.
- A super tag counts as its plain tag everywhere: searching `jogging` finds a note tagged `jogging:miles=3`; children inherit `jogging` (embedding notes don't), and in a search its values (the nearest wins); ontology rules about `jogging` apply; tag suggestions treat it as `jogging`. Right-clicking anywhere on the token opens the menu for `jogging`.
- Renaming a tag (Edit Tag Relationships) keeps its properties: `jogging:miles=3` becomes `running:miles=3`. Deleting the tag removes the whole token.
- The note list shows the token as written.
- Searching by values (`jogging:miles>2`, `jogging:miles?`, `date>=2024-01`) is described in `help-search` (Super Tag Searches).
- Searches also read values through implications: with `jogging => exercise`, `exercise:miles>2` finds `jogging:miles=3`.
- Suggestions: after `jogging:` the tag bar suggests property names used with `jogging` and with the tags it implies (`duration` from `exercise`), most used first, leaving out names the token already has; when none of those match what is typed (a new tag such as `salad:`), it suggests the names used with any tag, most used first, so names stay consistent; picking one adds it with its `=` (`jogging:miles=`). After `=` it suggests the values notes give the property, quoted when needed (`book:title="Dune: Messiah"`); after a value's number (`drug:dosage=10`), the units used with that property (`10mg`). The list shows only the name or unit; right-clicking a suggestion says how many notes use it with which tag.
- Ontology rules can test values: `jogging:miles>10 => long-run`, `task:due? => needs-date` (Edit Tag Relationships, the left column of the tag they give; `help-ontology`, Super tag atom). The tag a rule gives is the note's own, so its children inherit it.
- Stats: `@stats` on a note shows, under its text, each number property of the note and the notes under it: Total, Min, Max, Count. `@sum=calories` (and `@avg`, `@min`, `@max`, `@count`) shows one figure ("Total calories: 1,605"); `@sum` alone covers every property. Values count once, on the note writing them (not inherited, not via links or embeds); `calories=700` counts as `calories`; units stay apart; text values are left out (a line says how many). With nothing under the note, `@sum`/`@count` show 0 and the others a dash; a property used nowhere is a dash (a typo). Search them: `@sum:calories>2000`. Look: `Stats Style` in the command palette (Strip, Tiles, Ledger).

## Wrapper Tags
A tag token may be wrapped with matching brackets:
- `[]`, `{}`, or `()`
- Repeat count: **1–3**, and the opener/closer must match.

Examples (legal):
- `[tag]`
- `((tag))`
- `{{{tag}}}`

While typing an unfinished wrapper, `{{@` and `{{@foot` suggest meta tags without a warning. Ordinary tag prefixes work inside unfinished wrappers too. Accepting a suggestion preserves the opening brackets; close them to finish the scope. A space after the inner tag (for example `{{@footnote ` or `{{@footnote bar`) shows a subtle **Close scope with }}** reminder until the matching closers are entered. Suggestions remain available for additional tags inside that scope; the reminder is informational rather than an error. Fully closed multi-tag scopes remain supported, and incomplete scopes are still omitted when leaving the tag bar.

Examples (autocorrected while typing):
- `[tag)` → `[tag`
- `((tag))}` → `((tag))`

## Comments
You can include `/* ... */` comment segments in the tag bar:
- Comments may contain spaces.
- Comment text is preserved, in any script.

Comments also participate in server-side text search.

Unclosed comments behave like unclosed wrappers:
- A bare `/*` does not immediately warn.
- Once there is content (e.g. `/*comment`), the tag bar warns.
- Unclosed comments are omitted from the saved tag string and are removed when leaving the tag bar.

## Focus / Tab Behavior
- `Tab` toggles focus between the note content and the tag bar.
- Clicking the visible tag bar while editing focuses the tag input directly instead of treating the click as a note-shell selection.
- The tag bar expands into view when note editing starts and contracts out of view when editing ends, unless `Animated transitions` is off in the command palette.
- When leaving the tag bar (Tab or click-away), the tag string is sanitized so only valid, fully-formed tokens/comments remain.
- While the single-note tag bar is focused, note-level edit shortcuts still target the current note, including create sibling/child, delete, move up/down, move to top, indent/outdent, split, unformat, and note copy/cut/paste.
- `Cmd/Ctrl+U` removes formatting and inline imagery from the selected range, or from the entire note when no range is selected. Range removal deletes intersecting inline images and rewrites scoped delimiters around the selection so formatting outside it remains; whole-note removal removes rich HTML, all inline images, and Add Style tags while preserving links and semantic tags such as `@todo`.

## Add from Selected Text
- Selecting 1–25 characters inside a note adds **Add as Tag** to that note's context menu.
- The action always targets the note containing the selection, including when another note is being edited.
- Existing explicit vault tags are matched case-insensitively with spaces, `-`, `_`, `.`, and `/` treated as equivalent joiners. The most-used existing spelling and joiner style is reused.
- If the note already has an equivalent explicit tag, the action is a no-op and does not add a duplicate.
- If no equivalent tag exists, a new tag preserves the selection's capitalization, replaces whitespace with dashes, and removes characters disallowed by the tag-bar grammar. This preserves acronyms such as `GPT`.
- Selections longer than 25 characters, blank selections, selections with no usable tag characters, and exact uppercase `OR` do not show the action.
