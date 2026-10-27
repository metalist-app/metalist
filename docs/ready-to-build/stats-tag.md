# `@stats`: a small summary of a note's subtree

**Status:** Agreed with the maintainer 2026-10-27. Small; ready to build.
**Scope:** a new meta tag, `@stats`, that shows totals of the super-tag values in a note and everything under it, as a footer of that note. Document it beside the other rendering tags (`docs/ui/content-formatting.md`) and in `docs/design/tag-properties.md`.

Written without running the code. Check every reference before relying on it; build only what's missing.

---

## 1. The idea

Put `@stats` on a note, for example `diet`, whose children are meals with `…:calories=…` values. The `diet` note shows a short summary of every `calories` value in it and under it. A lightweight first way to total super-tag values, with no new screen: an `@` tag that changes how its note renders, like `@csv`. Meta tags aren't inherited, so it applies to that note only.

## 2. What it counts

- **The note's own values plus every descendant's own values.** Values belong to the note they're written on and children inherit tags, never values, so each value is counted once.
- **References and embeds inside the subtree don't count:** their values belong to the source note, which may be counted elsewhere.
- **Grouped by property name** (`calories`, `fat`, …), whatever tag carries it. Keeping meanings apart is the user's job (calories eaten and calories burned under one `@stats` note would add together).
- **One line per property: sum, min, max, and the count of notes holding it,** for example `calories Σ 12,600 · min 210 · max 1,450 · 18 notes`.
  - **Per note:** first add up each note's values for that property (a meal note may hold several foods), then take the sum, min and max across those note totals. So min and max are the lightest and heaviest meal, not the smallest ingredient.
  - **Units:** don't add mixed units blindly (`fat=10g` and `fat=500mg`): sum per unit (`Σ fat 42g, 1,500mg`) or flag the mix; no conversions.
  - **Non-numeric values** (`genre=sci-fi`, `version=0.24.5`) are skipped, with a quiet note of how many.
  - **Negative numbers** count normally (`adjustment:calories=-200` lowers the sum).
- **Live:** it updates as notes in the subtree change.
- `@password` / `@username` notes contribute nothing beyond what they already expose (property names and numbers only, never protected values).

## 3. Where it shows: a footer of the note's own content

- **Directly under the note's own text, above its children,** as part of that note's block, in the smaller style of the footnote **References** section (`docs/ui/content-formatting.md`, Footnotes), which is the precedent.
- **Not after the children:** every note renders as its content with its children below, and nothing comes back after them. Don't introduce a closing element after a subtree.
- **Hidden while the note is collapsed,** like the footnote References section.
- **Not inline:** there is no wrapper form for placing it in the text.

## 4. Invariants

1. `@stats` changes only how its own note renders; it never changes values or other notes.
2. Each value is counted once: own values only, never inherited, never through references or embeds.
3. Rendering order is unchanged: the footer belongs to the note's own content, above its children.

## 5. Tests

- `diet @stats` with three child meals carrying `calories` 300, 500 and (two foods) 200 + 400: `calories Σ 1,400 · min 300 · max 600 · 3 notes`.
- A value on the `@stats` note itself is included; a grandchild's value is included.
- A child that only references or embeds a note with `calories` adds nothing.
- Mixed units are summed per unit; a non-numeric value is skipped and counted as skipped; a negative value lowers the sum.
- Collapsing the note hides the footer; expanding shows it; it sits above the children.
- Editing a child's value updates the footer live.

## 6. Addition (agreed 2026-10-27): `@sum`, `@avg`, `@min`, `@max`, `@count`

Folded in from its own inbox note, to be built with `@stats`.

### 6.1 The tags

- **`@sum=calories`** shows **only** the sum of `calories` over the note and its descendants: one line, nothing else.
- **`@avg=…`, `@min=…`, `@max=…`, `@count=…`** work the same way, each showing exactly one number for the named property. `@count` is the number of notes holding that property.
- **Same counting as `@stats`:** the note's own values plus every descendant's own values; never inherited; never through references or embeds. **Avg, min and max are per note** (each note's values for the property added up first, then calculated across notes). Same unit, non-numeric and negative-number rules.
- **They combine:** `@sum=calories @max=calories` shows exactly those two lines, in the order written, in the same footer above the children (hidden while collapsed).
- **`@stats` stays** as the shortcut for "every property, all four numbers."
- *Proposed:* on a note with both `@stats` and precise tags, show `@stats`'s lines and skip duplicates.

### 6.2 One property per tag, for now

- A note can't carry the same tag twice yet, so `@sum=calories @sum=fat` isn't possible. **That's accepted:** repeated tags are planned, and this works once they exist. Until then, `@sum=calories @max=fat` (different tags) works, and `@stats` covers everything.
- **No list values** (`@sum=calories,fat`): that would be value syntax found nowhere else.

### 6.3 Details (proposed, not discussed in depth; adjust if they read badly)

- **A bare tag without a property** (`@sum`): show nothing but a quiet hint to name a property (`@sum=calories`).
- **A property that no note in the subtree has:** show the line with a dash (`Σ calories —`), so a typo is visible rather than silent.
- These are system `@` tags like `@stats`; users still can't define their own `@` tags.
- Suggestions: after `@sum=` (and the others), suggest property names found in the note's subtree, most used first.

### 6.4 Tests

- `@sum=calories` on a `diet` note with meals 300, 500 and 200 + 400 shows only `Σ calories 1,400`.
- `@avg=calories` shows the per-note average 466.7; `@min=calories` 300; `@max=calories` 600; `@count=calories` 3 notes.
- `@sum=calories @max=calories` shows two lines in that order.
- `@sum` alone shows the hint; `@sum=calroies` shows a dash.
- A referenced or embedded note's values aren't counted.

## 7. Checked 2026-10-27 (filed from the inbox)

- Not built: no `@stats`, `@sum`, `@avg`, `@min`, `@max` or `@count` in the code.
- Confirmed: the footnote References section (`docs/ui/content-formatting.md`, Footnotes) is the precedent, hidden while its note is collapsed; `docs/design/tag-properties.md` lists totals under "Later".
- Repeated tags in one note (§6.2) are planned, not scheduled: they will come, when is undecided (maintainer, 2026-10-27; `docs/future-plans/same-tag-twice.md` now says so).
- Shares its calculation with the summaries beside the result count (`super-tag-summaries-and-date.md`): build one calculation for both.
- **Decided (maintainer, 2026-10-27), the "proposed" details of §6.1 and §6.3 all stand:** a note with both `@stats` and precise tags skips duplicate lines; a bare `@sum` shows a hint; a property no note has shows a dash; suggestions after `@sum=` come from the note's subtree.
