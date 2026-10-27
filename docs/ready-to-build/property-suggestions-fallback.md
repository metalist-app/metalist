# Super tags: suggest popular properties for a tag that has none yet

**Status:** Agreed with the maintainer 2026-10-26. Small; ready to build.
**Scope:** the tag bar's property-name suggestions after `tag:` when that tag has no properties of its own yet. Update `docs/design/tag-properties.md` (Suggestions) with the result.

Written without running the code. Check every reference before relying on it; build only what's missing.

---

## 1. Today

After `jogging:`, the tag bar suggests property names used with `jogging` and with the tags `jogging` implies (for example `exercise`), most used first. A tag with no properties of its own and none on the tags it implies gets **no** property suggestions.

## 2. The change

- When that list would be **empty** (a new tag, or one never used with properties, with nothing to inherit through implications), **suggest property names used on any other tag in the vault, most used first** (by how many notes carry that property on any tag).
- Example: the vault uses `calories` on many food tags. Typing `new-food:` suggests `calories` first, then the next most popular properties.
- When the tag (or a tag it implies) already has properties, behavior is unchanged: those come first, as today. *(Whether vault-wide properties should also follow them, lower in the list, is not decided; don't add that now.)*
- After a property is chosen, everything continues as today (units after a number; last-used values once the tag has been used with values).
- Never suggest the `tag=value:prop=…` form (unchanged rule).

## 3. Why

Consistent property names are what make search, rules and future sums work. A brand-new tag is exactly where a user would otherwise invent a new spelling (`kcal`, `Calories`) instead of reusing `calories`. Suggesting the vault's popular properties keeps names consistent from the first use.

## 4. Tests

- A tag with no properties and no implied properties: after `tag:`, the vault's properties are suggested, most used first.
- A tag that has properties (or implies one that does): suggestions are exactly as today.
- Ties are ordered deterministically (for example alphabetically).
- `@password`/`@username` notes contribute nothing beyond what they already do to property counts (protected values never appear; property names only).

## 5. Checked 2026-10-27 (filed from the inbox)

- Not built: `SearchIndex.suggest_property_completions` (`app/services/search_index.py`) counts names only on the tag and the tags it implies (`_tags_implied_by_locked`, then `_property_name_counts_locked`); with none, it returns nothing. Ties already sort by name.
- **The trigger is after filtering by what is typed** (maintainer, 2026-10-27): own and implied properties come first; when none of them match what is typed, suggest from the vault, most used first. So `jogging:cal` offers `calories` when `jogging` only has `miles`; a tag with no properties is the case where that list starts empty. The fallback is there for the moment a new name is about to be invented.
- **The tag bar only, not the search box** (maintainer, 2026-10-27): in a search, a property never used with that tag (or the tags implying it) matches no notes, and search suggestions lead only to things that exist.
- Tests: in the tag bar, `jogging:` with `jogging` having `miles` suggests `miles` only, and `jogging:cal` suggests the vault's `calories`. In the search box, `jogging:cal` suggests nothing from outside `jogging` and the tags implying it.
