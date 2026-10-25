# Super tags: suggest the values you used last time

**Status:** Agreed with the maintainer 2026-10-25. Small; ready to build.
**Scope:** The tag bar's suggestions for a super tag that has been used with values before. This is the "value suggestions can come later" step in `docs/design/tag-properties.md` (Suggestions); update that document when it's built.

Written without running the code. Check every reference before relying on it; build only what's missing.

---

## 1. Behavior

When the user types a tag that has been used before **with property values**, the tag bar suggests:
1. **First: the tag with the values from the last note that used it,** in full, for example `breakfast-burrito:calories=800:fat=10g:carbs=60g`. The suggestion shows the whole token so the user sees what they're accepting.
2. **Second: the tag alone** (`breakfast-burrito`), as today.

Then today's suggestions continue as they are (property names after `tag:`, units after a number).

- **"Last" = the most recently created note** carrying that tag with at least one property value. (Created, not last edited: for logs, an entry's time is when it happened. Confirm with the maintainer if this is ambiguous in practice.)
- Use only values **written on that note itself**, never inherited ones (values are never inherited, per the existing design).
- Include units exactly as written (`10g`).
- Accepting inserts plain text into the tag bar, exactly as if typed. The user can edit any value before leaving the note. Nothing is applied invisibly, and past notes never change.
- If the tag has never had values, behave as today.
- Search box: unchanged for now (this is for entering tags on notes).

## 2. Why

- The maintainer tracks diet in his journal with a super tag per regular food (calories, fat, carbs…). With last-used values, logging a food after the first time takes a couple of keystrokes: low enough friction to keep tracking.
- Chosen over explicit default values in the tag editor: no setup, adapts by itself (enter a new value once and it becomes the suggestion), and history stays true because values are written on each note.
- Later, consistent values make aggregation and charts over super tags worthwhile (already anticipated in `docs/design/tag-properties.md`: "totals, charts and other aggregation come later"). Not part of this change.

## 3. Tests

- A tag used with values: the first suggestion is the full token from the most recently created such note; the second is the bare tag.
- A newer note with different values changes the first suggestion.
- Values inherited by children or references are never used.
- Units are preserved exactly.
- Accepting inserts text only; editing a value before leaving works; older notes are unchanged.
- A tag never used with values: suggestions as today.

## 4. Open (don't block on these)

- Whether to also offer the most often used values when they differ from the last ones (for example as a third suggestion).
