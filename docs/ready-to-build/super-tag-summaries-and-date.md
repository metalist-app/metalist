# Super-tag summaries beside the result count, and the `@datetime` tag

**Status:** Agreed with the maintainer 2026-10-26. Ready to build. (Charts, the next step, are a separate future-plans note: `2026-10-27-charts.md`, which arrives with this one.)
**Scope:** (1) a view option that summarizes a numeric (or text) property over the notes a search finds, shown beside the result count; (2) a reserved `@datetime` tag that says which date a note belongs to. Update `docs/design/tag-properties.md` ("Later" lists totals beside the result count), `docs/ui/search-semantics.md` and the view-option docs.

Written without running the code. Every reference below came from reading it and must be checked before relying on it; build only what's missing.

---

## 1. Today (to verify)

- `docs/design/tag-properties.md`, "Later": "Totals, averages and sorting by a property (for example 'miles this month' beside the result count…)."
- `=MAX` / `=MIN` exist as search keywords that **find** the notes holding the largest or smallest value (`docs/ui/search-semantics.md`).
- Values belong to the note they're written on; children and references inherit tags, never values.
- A separate `@stats` tag (a footer summarizing a note's subtree) was handed off on 2026-10-27; this is its search-based counterpart. Share the calculation code.

## 2. Summaries: a view option, shown beside the result count

- **The search picks the notes,** as always, for example `:calories` plus the date range "Created · last 7 days."
- **A view option picks a calculation and a property:** **Sum, Average, Median, Min, Max** (numbers) or **Mode** (any values): "Sum of `calories`," "Median of `pages`." It shows as a chip in the search bar like other view options, with × to remove it.
- **The result appears beside the result count,** labeled for exactly what it is: `18 notes · Σ calories 12,600`, `18 notes · median per note 640 cal`. No panel, no new screen.
- **Through implications:** `food:calories` sums every food's calories via `breakfast-burrito => food`, using the existing upward search.
- **Per note:** Average, Median, Min and Max first add up each note's values for the property (one meal note may hold several foods), then calculate across notes, and the label says **"per note."** Sum is the same either way.
- **Mode** = the most common value, for text values (`book:genre=sci-fi`): each note counts once per distinct value; always shown with its count (`mode genre: sci-fi (12 of 30 notes)`); ties show all tied values.
- **Negative numbers count normally** (`adjustment:calories=-200` lowers the sum).
- **Units:** don't add mixed units blindly (`fat=10g`, `fat=500mg`): sum per unit (`Σ fat 42g, 1,500mg`) or flag the mix; no conversions.
- **Non-numeric values** are skipped by Sum, Average, Median, Min and Max, with a quiet note of how many.
- **No per-day or per-week calculation, on purpose:** notes aren't days (three meals on Tuesday, none on a fasting Wednesday), and an empty day can be a real zero or a forgotten log. Calculations are over notes, never over inferred groupings. Count stays labeled as notes.
- Min and Max complement `=MAX`/`=MIN`: those find the notes; these show the number.
- Repeated tags in one note aren't allowed yet; if that ever changes, decide then how they sum.

## 3. The `@datetime` tag: which date a note belongs to

**The problem:** date filters use created or last-updated time, so a back-filled entry (Saturday's food logged Monday) lands on Monday, and nothing can be dated into the future.

- **A reserved `@datetime` tag whose value is a date or date-time:** `@datetime=2026-10-24` or `@datetime=2026-10-24T08:30`.
- **It overrides created and last-updated wherever MetaList uses a note's date:** date-range filters, and later charts and grouping by day.
- **Date-only is fully valid** and means that whole day. Where an exact moment is needed (ordering within a day), **a date-only `@datetime` counts as noon, the user's local time** (noon survives a time-zone shift of a few hours; midnight could slip to the day before).
- **Stored as the user's local time.**
- **It inherits down, and the nearest `@datetime` wins.** One `@datetime` on a journal's day note dates every child; a child with its own `@datetime` (an appointment next Friday written in today's journal) overrules its parent. This is a **deliberate exception** to "values never inherit," which exists to prevent double counting; a date is never added up.
- **The suggestion is always now:** typing `@dat…` offers `@datetime=` with the current date and time **in the exact stored format**, so nothing has to be typed in full and the format teaches itself; edit the day, or trim to a date. **No calendar picker** (a one-tag special widget) and **no other date suggestions** ("today," "yesterday" would need labels and a new suggestion display).
- **Separate from users' own `date` tags:** the docs use a plain `date=…` user tag as an example; the system's tag is `@datetime`.

**Not decided (propose):**
- Whether a note that references or embeds another inherits that note's `@datetime` (probably not: the holder keeps its own).
- Whether "Sort by Created" also uses `@datetime`, or only date filters (and later charts).

## 4. Invariants

1. A summary covers exactly the notes the search shows; nothing is inferred about time.
2. Values are counted only on the note they're written on.
3. Negative values subtract.
4. No calculation groups notes by day or any other inferred unit.
5. Average, Median, Min and Max are per note and labeled so.
6. Mode counts each note once per distinct value and always shows its count.
7. `@datetime` overrides created/updated for dating, inherits down, and the nearest wins.

## 5. Tests (at least)

- `:calories` with three notes (300; 500; 200 + 400): Sum 1,400; Average per note 466.7; Median per note 500; Min 300; Max 600.
- `food:calories` includes `breakfast-burrito` notes through `breakfast-burrito => food`.
- Mixed units sum per unit; a text value is skipped and counted as skipped; a negative value lowers the sum.
- Mode over `genre` shows the top value with its count; ties show all.
- A note created today with `@datetime=2026-10-20` falls in "last 7 days" according to the 20th, not today; a child with no `@datetime` inherits its parent's; a child's own `@datetime` wins.
- A date-only `@datetime` orders as noon local time.
- Typing `@dat` suggests `@datetime=` with now, in the stored format.

## 6. Checked 2026-10-27 (filed from the inbox)

- Confirmed: `docs/design/tag-properties.md`, "Later", lists totals and averages beside the result count; `=MAX` / `=MIN` find notes (`docs/ui/search-semantics.md`).
- Not built: no summary view option and no `@datetime` tag.
- Users already have a `date` valued tag in the docs' search examples (`date>=2024-01`, `docs/ui/search-semantics.md`), so the system's tag being `@datetime` keeps them apart, as §3 says.
- Shares its calculation with `@stats` (`docs/ready-to-build/stats-tag.md`).
- **Named `@datetime`, not `@date`** (maintainer, 2026-10-27): it records a date and a time; a date alone stays valid (§3).
- **A note that links to or embeds another never takes that note's `@datetime`** (maintainer, 2026-10-27): dates inherit down from parents only.
- **Sort by Created keeps meaning when a note was typed** (maintainer, 2026-10-27), so sorting by Created still shows recent additions (`docs/ready-to-build/phone-same-app.md`, §3, relies on it). `@datetime` overrides the date for date-range filters and charts only. A separate Sort by Date, by `@datetime`, can come later if wanted.
