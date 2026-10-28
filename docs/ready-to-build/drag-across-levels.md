# Drag across levels: an experimental drag mode behind a setting

**Status:** Agreed with the maintainer 2026-10-28. Ready to build. **This becomes the default drag;** a menu setting turns it off (back to today's drag) while the maintainer experiments. One small point is still open (§8).

Written from a read-only look at the repo. Check the code references before relying on them.

---

## 1. Why

Today a drag is locked to one axis (`docs/ui/controls.md`, "Drag note body"): up and down reorders among visible siblings and never leaves the parent; sideways indents or outdents one level. Moving a note to another part of the outline takes several drags or keyboard moves. This mode moves a note to any level in one drag, without asking for precision.

## 2. The rule

**The target is the note you release on (the note under the pointer at mouse-up). Dragging up, the dragged note becomes a sibling directly above the target. Dragging down, it becomes a sibling directly below the target, after the target's whole subtree, never among its children. The same at every level of the outline.**

The target alone decides both the place and the depth; where the pointer is within the target makes no difference. It's the same rule as reordering tabs by dragging (`docs/ui/state-handling.md`: the dropped tab takes the hovered tab's slot); tabs just have no children.

```
A
    B
C
    D
    E
```
| Drag | Result |
|---|---|
| E up onto D | E and D swap |
| E up onto C | E becomes a root note between A and C |
| E up onto B | E becomes A's child, above B |
| E up onto A | E becomes a root note above A |
| B down onto A | B becomes a root note between A and C |
| B down onto C | B becomes the last root note, after D and E |

Consequences, all intended:
- First child of a note: drag up onto its first child. Last child: drag down onto its last child.
- **Into a note with no children takes two motions:** drop just below it, then Indent. There are deliberately no "drop inside" zones: on a one-line note they'd be a few pixels apart, hard to hit and hard to indicate.
- A collapsed note is never entered.
- Dropping onto the dragged note itself, or anywhere inside its own subtree, does nothing.
- **Sorted views: only within the same root note.** In a view sorted by anything other than manual order, the existing policy stands (`docs/ui/controls.md`, non-normal sort order): a note can't leave the root note it's under, and root notes can't be moved. So this mode works there only inside one root note's tree: a drop onto a note in another root's tree, or onto a root note itself (which would make the dragged note a root), does nothing, and dragging a root note does nothing.
- **A redacted line is never a target:** releasing on a grey bar standing for a note the search leaves out does nothing (no outline while hovering it either). **Nor is a revealed note** (one shown dimmed after clicking a redacted line, still excluded by the search): a note dropped among them could inherit the excluded tag and vanish from the results.
- **Releasing on either says why,** in a short floating message (`docs/ui/floating-messages.md`; it takes no space and never takes focus), for example: `Can't drop here: the current search leaves this note out.` Nothing moves.
- In a filtered view, the place is defined relative to the target alone (directly above it, or directly after its subtree, in the full outline), so notes hidden by the search don't make it ambiguous.

## 3. Which note is the target

**The innermost note whose box is under the pointer at mouse-up.** A parent's box includes its left margin beside its children: released in that margin, the parent is the target; only released inside a child's own box is the child the target. This is the same note a left click at that point would open for editing, so the same hit test can serve both.

So beside a deep subtree, moving the pointer left picks a shallower target, through full-height margins rather than a few pixels.

**Up or down:** the target is above or below the dragged note in the list. This also covers a pointer moved sideways into a parent's margin (the parent is above).

## 4. What's shown

- **The main cue is the target's outline,** following the pointer. The ghost, the drop line and the direction cursor work as today and stay switchable in `Visual Cues…`; the drop line shows the landing place.
- **No sideways indent/outdent drag in this mode:** a pointer moved left is over the parent's margin, which targets the parent. Indent and outdent stay on `⌘→`/`⌘←` and the note menu.

## 5. Scrolling

The result is always brought into view, by the minimum, as the interaction principles already require (`docs/ui/interaction-principles.md`):
- In view: nothing scrolls.
- Below the window (likely when dragging down onto a note with a large open subtree): after the drop, scroll just enough to show the moved note's first line at the window's bottom.
- Behind the search controls: scroll just enough to put it right below them, as today.

Add a row for this mode to the principles' "Derived behavior" table.

## 6. A moved note never disappears from the current search

Children inherit their ancestors' non-meta tags, so a note that matched the search only through its old ancestors would vanish when moved under a different parent. **It always gets, as its own tags, the tags it needs to keep matching the current search.** Its children inherit them as usual.

- Applies to **every move that changes a note's parent**: this mode, today's drag, indent and outdent. Check what those do now.
- **No message** about tags gained or lost. Inherited tags changing when a note moves is how the outline works.
- Don't add tags the note already carries or still inherits at its new place.

## 7. The setting

- One menu setting turns this mode on and off. **On by default,** so it's what everyone gets rather than a hidden option. Stored like the other menu preferences (namespace preferences, as `Backup Reminder` is). A suggested name: `Drag Across Levels`.
- The setting exists for a trial period. If this mode stays, today's drag and the setting are removed rather than kept as a second mode, so keep the two paths easy to separate.

## 8. Still open (build around them)

1. Whether the note menu gets `Cut Note` beside `Copy Note`. Cut already exists on `⌘X` with nothing selected.

Not a case: a search that excludes a tag the new parent would pass down. A note carrying the excluded tag isn't shown, and every shown note's parent lacks it too (or the shown note would inherit it), so no drop can land under it.

## 9. Done when

1. A new or existing vault has the setting on; with it off, drag behaves exactly as today.
2. With it on, every row of the table in §2 gives the result shown, including a release in a parent's left margin targeting the parent.
3. Drops onto the dragged note or its subtree, onto a redacted line or a revealed (dimmed) note, and onto a collapsed note's hidden children, can't happen or do nothing; a release on a redacted or revealed note shows the floating message. In a sorted view, a drop outside the dragged note's own root note, or onto a root note, does nothing.
4. A note that matched the search only through its old parent stays in the results after a move, with the needed tags added (this mode, today's drag, indent, outdent).
5. A drop landing below the window scrolls just enough to show the moved note's first line; one landing behind the search controls scrolls just enough to show it below them; one in view scrolls nothing.
6. Browser tests cover 2–5; `docs/ui/controls.md` describes the mode and the setting.

## Found when filed (2026-10-28)

- §6 is partly built: outdent already adds the tags a moved note needs (`app/usecases/outdent.py` calls `ensure_tags_match_search_query`, as `paste_sibling.py` does). Indent and the drag reorder don't yet.
- The setting can sit beside `Backup Reminder` (`endpoint-registry.js`, a `pref.*` key in `app/services/client_state_service.py`).
- `Cut` with nothing selected is `keyboard.cut_note` in `keyboard-events.js`; the note menu has `Copy Note` (`context-menu-registry.js`) but no `Cut Note`. Still open (§8).
- Revealed notes come from `search-redaction-reveal-service.js`.
