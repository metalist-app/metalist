# Attribute searches without a tag, and OR in ontology rules

**Status:** Agreed with the maintainer 2026-10-25. §1 and §2 ready to build, not started; filed here from `docs/inbox/` on 2026-10-25. §3 is a recorded future idea, filed in `docs/future-plans/same-tag-twice.md`; don't build it.

Written without running the code. Check every reference before relying on it; build only what's missing. Update `docs/ui/search-syntax.md`, `docs/ui/search-semantics.md`, `docs/design/tag-properties.md` and `docs/design/ontology-rules-v1.md` with the result.

---

## 1. Search: a property on any tag

- **`:version`**: notes where **any** tag carries a `version` property (any value).
- **`:version=0.24.5`**: notes where any tag has `version` equal to `0.24.5`.
- Comparisons and units as for existing super-tag terms: `:version>0.24`, `:miles<=5mi`, etc. A leading `-` or `+` works as for other terms.
- **No tagless `?` form.** `:version?` is not supported (the maintainer decided it matches too much). The incomplete-term warning should say so if typed.
- Upward search through implications doesn't apply here (there's no tag to start from); the term reads every tag's properties with that name.
- **Suggestions:** after a bare `:` in the search box, suggest property names used anywhere in the vault, most used first; after `:name=` or a comparison, the usual unit suggestions.

## 2. Ontology rules: OR on the left side

- **`a OR b => c`** is syntactic sugar for **`a => c`** plus **`b => c`**.
- **Same precedence as search:** adjacent terms are ANDed; uppercase `OR` separates groups. **`a b OR c d e => f`** means `(a AND b) OR (c AND d AND e) => f`, i.e. the rules `(a b) => f` and `(c d e) => f`. No parentheses needed or added.
- Example from the maintainer: `metalist:version OR metalist version => metalist-version`.
- Every existing atom type is allowed in any group. The existing `(a b c) => d` form stays valid (a single group).
- Treat an OR rule everywhere as its expanded set: validation and error messages, the explanation of why a tag was inferred (name the group that matched), and the recompute of the notes a saved rule can concern.

## 3. Future idea, not to build: the same tag more than once in a note

The maintainer now has use cases (`breakfast-burrito:calories=800` twice for two burritos; `metalist:version=0.24.0 metalist:version=0.23.1` to compare versions), but it conflicts with "a note carries each tag at most once," which search, rules and future totals rely on (does a value search match once or twice; does a total count once or twice). Record it in `docs/future-plans/` as "might do," to revisit when totals and charts over super-tag values are designed. Until then, the patterns are a quantity property (`breakfast-burrito:count=2:calories=800`) or one child note per instance.

## 4. Tests

- `:version` and `:version=0.24.5` match across different tags; comparisons and `-`/`+` work.
- `:version?` is rejected with a clear message.
- `a OR b => c` infers `c` from either side; `a b OR c d e => f` infers `f` only when all of one group is present.
- The inference explanation names the matching group.
- Existing rules and searches behave exactly as before.

## Found when filed (2026-10-25)

- Neither is built: `docs/ui/search-syntax.md` says "The tag comes first" (no `:name` term without a tag), and `docs/design/ontology-rules-v1.md` has no `OR` on the left side (only the `(a b c) => d` group form).
- The four documents named above exist and point here now.
