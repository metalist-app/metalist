# Stats tags: empty figures, and searching the figures (`@sum:calories>2000`)

**Status:** Agreed with the maintainer 2026-10-28. Ready to build. Changes the built stats tags (`docs/ui/content-formatting.md`, "Stats of a subtree"; `app/services/subtree_stats.py`) and adds a search form (`docs/ui/search-semantics.md`, "Super Tag Searches"). One point in §3 is proposed; ask before deciding it.

Written from a read-only look at the repo. Check the code references before relying on them.

## Found when filed (2026-10-28)

Filed from `docs/inbox/2026-10-28-stats-empty-and-search.md`.

- **References hold:** `_MISSING` (`subtree_stats.py`), `isPropertyTerm` and `NAMED_PROPERTY_TERM_RE` (`search-syntax-service.js`), `parse_property_term` (`tag_properties.py`).
- **§3's proposal is how the code works now:** `@count` counts only notes with a number value for the property (`note_count` grows only from number values, `_add_note_values`), so the average is already total ÷ count.
- **§1 item 4, "only non-numbers", today:** `@sum=calories` shows a dash and **no** "not a number" line. That line is written only under `@stats` groups (`render_subtree_stats_footer`). So the change also has to add the line under the precise tags.
- **Under `@stats`, a property with only non-number values shows nothing at all,** neither a group nor the "not a number" line (`_footer_lines` lists only properties with `note_count > 0`). **Decided (2026-10-28):** under `@stats`, a property with only non-number values shows its "not a number" line (no group of figures).
- **Careful with the server change:** the `@` check sits in `has_property_syntax`, which the tag bar's own parsing also uses (meta tags have no properties; their colons are removed). Allow `@sum:` etc. in search without letting meta tags take properties in the tag bar.

---

## 1. Empty figures: 0 for sum and count, a dash for the rest

**Today:** a named property that no note under the tag's note has shows a dash for every tag (`Total calories: —`), so that a typo shows (`subtree_stats.py`, near `_MISSING`).

**Change:** when nothing under the note (the note itself included) has the named property:
1. **`@sum` and `@count` show 0:** `Total calories: 0`, `Notes with calories: 0`.
   - The sum of nothing is 0, so 0 is true, not a placeholder.
   - It's what a template or a new day needs. A food-log day created in the morning with `@sum=calories` reads 0 and counts up as meals are added. A dash there looks broken.
2. **`@avg`, `@min` and `@max` keep the dash.** An average, minimum or maximum of nothing doesn't exist, and "Average calories: 0" would claim meals of zero calories.
3. **A property used nowhere in the vault keeps the dash, for every tag,** so `@sum=calroies` still looks wrong. The property suggestions after `@sum=` already make typos rare, but this guard is cheap.
   - "Used in the vault" means some note anywhere has a value for that property name, whether a number or not.
   - Which index answers that is your call.
4. **Only non-numbers:** if the only values are not numbers (`snack:calories=lots`), `@sum` shows 0 together with the existing "not a number" count, so the 0 doesn't hide them. Check what the line shows today in this case.

**Unchanged:**
- `@stats` (every property) lists only properties that exist under the note. A property whose values are all non-numbers gets only its "not a number" line (decided 2026-10-28).
- A total that adds up to exactly 0 (+500 and −500) already shows 0. `@count` tells the two cases apart.

**Accepted:** with no values there's no unit, so the figure is a plain `0`.

## 2. Searching the figures

**Today:** the search box refuses a colon after an `@` word, because `@` words are never property terms (`app/static/js/modules/mode-manager/services/search-syntax-service.js`, `isPropertyTerm`, and the `[^:=<>?@]` start of `NAMED_PROPERTY_TERM_RE`). The server side needs the same change (`app/services/tag_properties.py`, `parse_property_term`, per the comment there).

**New:** the existing super-tag search form, `tag:property>value`, with one of the five stats tags as the tag:

- `@sum:calories>2000`: notes carrying `@sum=calories` whose total is over 2000.
- `@count:calories>3`, `@avg:calories<600`, `@min:calories<100`, `@max:calories>1000`: the same for the other four.
- **It matches only notes that carry that tag for that property,** comparing the figure the note shows. It never computes a figure for every note: then every parent of a food log (the month, the year, the log) would match.
- **Not through `@stats`:** a note whose `@stats` footer shows a calorie total doesn't match `@sum:calories>2000`. Notes with `@stats` stay findable with `@stats`.
- **`@sum:calories` with no comparison** finds the notes carrying `@sum=calories`, as `jogging:miles` does for super tags.
- **Operators and keywords as for super tags:** `>`, `<`, `>=`, `<=`, `=`, and `=MAX`/`=MIN` among the notes the rest of the clause finds (`@sum:calories=MAX` is the biggest day). `-` excludes; spaces and `OR` combine.
- **Units as today:** `@sum:fat>10g` compares the grams total only; `@sum:fat>10` compares every unit's total and matches if any one does.
- **A property is required:** `@sum>2000` and `@sum:calories?` are refused with how to write the term, like `jogging:miles>2:duration<40` today.
- **A dash never matches,** whatever the comparison. A day with no meals has no average, so it isn't `@avg:calories<600`. A 0 is a number: `@sum:calories=0` finds the days nothing was logged.
- **Counting is the footer's,** so search and footer always agree: the note's own values and its descendants', never inherited ones, never through references or embeds, avg/min/max per note.
- **Live:** an edit under a matching note changes its figure, so the search result can change. Refresh it the way other value searches refresh after an edit (*verify* how they do).
- **A note added while such a search is active gets nothing added.** The search names no value to give it.
- **Suggestions:** after `@sum:` suggest property names, as after `jogging:`.

## 3. The rules for all five, together

| | `@sum` | `@count` | `@avg` | `@min` / `@max` |
|---|---|---|---|---|
| Nothing under the note has the property | 0 | 0 | — | — |
| Name used nowhere in the vault | — | — | — | — |
| Only non-numbers | 0, plus the "not a number" count | 0 | — | — |
| In a search, a dash | never matches | never matches | never matches | never matches |

**Proposed, not discussed (ask):** `@count` counts notes with a **number** value for the property. Then the average is always total ÷ count, and non-numbers show only in the "not a number" line. The built label ("Notes with calories") doesn't settle which one the code does today.

## 4. Acceptance checks

**Footer:**
- `@sum=calories`, nothing under the note has calories, but calories is used elsewhere in the vault: `Total calories: 0`. `@count=calories`: `Notes with calories: 0`. `@avg`, `@min`, `@max`: dash.
- `@sum=calroies`, a name used nowhere: dash.
- Only `snack:calories=lots` under the note: `Total calories: 0` plus the "not a number" count.
- Adding a child with `calories=450` turns `0` into `450` live.

**Search:**
- Days carrying `@sum=calories` with totals 1,500, 2,400 and 0: `@sum:calories>2000` finds the 2,400 day; `@sum:calories=0` finds the empty day; `@sum:calories=MAX` finds the 2,400 day.
- The parent of those days, without `@sum=calories`, never matches.
- A day with `@stats` only, total 2,400, doesn't match `@sum:calories>2000`.
- `@avg:calories<600` doesn't find the empty day.
- `@sum>2000` is refused with a hint.
- Typing `@sum:` in the search box is accepted and suggests property names.

**Docs:** `docs/ui/content-formatting.md` and `docs/ui/search-semantics.md` describe the new rules.
