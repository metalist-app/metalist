# The same tag more than once in a note (might do)

**Status:** Planned, not scheduled: it will be done, when is undecided (the maintainer, 2026-10-27; recorded 2026-10-25, from `docs/ready-to-build/attribute-search-and-or-rules.md`, §3). Revisit when totals and charts over super-tag values are designed.

- **Use cases:** `breakfast-burrito:calories=800` twice for two burritos; `metalist:version=0.24.0 metalist:version=0.23.1` to compare versions.
- **The conflict:** "a note carries each tag at most once" is what search, rules and future totals rely on. Does a value search match once or twice; does a total count once or twice?
- **Until then:** a quantity property (`breakfast-burrito:count=2:calories=800`), or one child note per instance.
