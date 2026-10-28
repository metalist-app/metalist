# Charts of super-tag values (future plan)

**Status:** **Direction only. Don't build yet.** Parts are decided (marked), parts are still being shaped with the maintainer. File it in `docs/future-plans/`. Sent now so nearby work (summaries, `@datetime`, `@stats`, the diagram code) doesn't close off this direction.
**Scope:** charts of super-tag values over time or as distributions, drawn from a search or from a CSV/JSON file. Builds on the summaries and `@datetime` note (`2026-10-27-super-tag-summaries-and-date.md`, arriving with this one).

Written without running the code. References are from reading it; verify before relying on them.

---

## 1. Charts work exactly like diagrams (decided)

Modeled on the existing Excalidraw diagrams (`docs/ui/excalidraw.md`), not on a separate modal:
- **A chart is a file attachment** (a new file kind, "chart"), referenced in a note as `![[UUID]]`, like a diagram. Its file holds the chart's recipe: source, properties, date range, chart type, grouping and gap-filling choices, and live or snapshot (with frozen data for a snapshot).
- **Created inside a note:** while editing, **Add Chart** (right-click menu and command palette) attaches a new chart to that note, starting from the current search.
- **View mode** shows the rendered chart in place, like a diagram's preview (light and dark previews stored encrypted); size controls, collapsed thumbnails and HTML export work as for diagrams. **Edit mode** shows only the raw `![[UUID]]` token.
- **To work with it:** double-click, or right-click → **Edit Chart**. It opens **full screen**, exactly as the diagram editor does: the same bar (save status, Discard Changes, Done), the same autosave, the same second-window rules.
- *Why:* no new concepts; a chart is another kind of embedded file, opened the way diagrams open.

## 2. A chart owns its source (decided)

- **Two kinds of source, one editor:** **a search** or **a data file attachment** (CSV, or JSON that's a list of records: an array of objects or one object per line; nested values by dotted path, `pace.avg`; anything not record-shaped refused with a clear message).
- **A search source is pre-filled** with a copy of the search context the user is in, then **belongs to the chart,** stored in its file and **not linked to where the chart lives.** A chart in a `Habits` list can chart `journal` notes because its search says so. Moving or referencing the chart never changes what it shows. The search is editable at the top of the chart editor and **shown as a caption** on the rendered chart (`journal :calories · last 30 days`).
- **Choosing the source:** two selectors (source type, then which file). **Smart default when a chart is added:** look for CSV and JSON files in the note itself, its descendants, and its ancestors; if any, default to the nearest; otherwise the search. Nearby files are listed by name; another file can be picked by pasting its reference or typing part of its name (fuzzy suggestions limited to data files, the `[[` suggestion pattern).
- **Files:** a header row is required; column types (number, date, text) are detected and shown for correction; columns play the role of properties (checkboxes for which to plot, one column as the x-axis). The file is untrusted input with size limits; if a CSV is ever exported back out, neutralize cells starting with `=`. A live chart redraws when the file is replaced.
- **Rejected:** importing a CSV's rows as notes (a big export would flood the vault).

## 3. Snapshot or live (decided; a setting of the chart)

- **Snapshot:** frozen and dated ("calories, Oct 19–26").
- **Live:** stores only the recipe and redraws on every view.
- **A live chart's date range reuses the search's date-range vocabulary:** sliding (`last 7 days`), growing (`since Oct 1`), fixed (`Oct 1–22`); the label says which.
- **Shared** in exchange files, a live chart carries only its recipe, never data, so it draws the recipient's own notes. **Exported to HTML,** a live chart is frozen as a snapshot of that moment.

## 4. Grouping and gaps (decided)

- **Group by day is an explicit option, never automatic,** labeled "grouped by day, using each note's date," with a small **"?"** explaining the edge cases (entries logged later land on the later day unless they carry `@datetime`; an empty day shows as zero whether it was a fast or a forgotten log). Dates come from `@datetime` when present. The summaries beside the result count stay per note.
- **How a line connects points, labeled on the chart:** **Linear**, **Step** (holds until the next value: weight, a setting), **None** (points only, gaps visible). With group by day, also: **empty days as zero** or **empty days skipped**, chosen by the user who knows which it was.
- *Possible later:* smoothing (a moving average over a chosen window).

## 5. Still being shaped

- **Chart types that need no hidden grouping:** each note as a point over time; a running total; a distribution of note totals; counts per value for text values.
- **Several properties at once:** a checkbox per property, each its own series; a toggle between **normalized** (common scale: compare shapes) and **stacked panels sharing one time axis** (real units each).
- **The summaries appear inside the chart editor,** updating with its range.
- Whether changing the range in the editor also changes anything outside the chart (it shouldn't, since the chart owns its source; to confirm).

## 6. Invariants (decided)

1. A chart is an embedded file like a diagram; it never changes notes.
2. A chart's source is its own; where the chart sits never changes what it shows.
3. Nothing is grouped by day unless the user chose it, and the label says so.
4. A shared or exported live chart carries a recipe, never someone else's data; an HTML export freezes it.

## 7. Checked 2026-10-27 (filed from the inbox)

- Filed as a future plan, as its status asks. Confirmed: diagrams are embedded Excalidraw files opened full screen (`docs/ui/excalidraw.md`), the model this follows.
- Builds on `docs/ready-to-build/super-tag-summaries-and-date.md` (summaries, `@datetime`) and `@stats` (built 2026-10-27; `docs/ui/content-formatting.md`, Stats of a subtree).
