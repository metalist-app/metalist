# Dragging a note from the notes column into a folder

**Status:** Agreed with the maintainer 2026-11-02. Ready to build. Completes the second row of §4's drag table in `docs/ready-to-build/virtual-folders.md` ("a note from the notes column onto a folder: all its folder tags are replaced by the target"), which stands unchanged, and adds two rules.

Written from a read-only look at the repo. Check the code references before relying on them.

---

## 0. Today (from the code)

- The tree handles only a folder dragged onto another folder (`virtual-folders-service.js`, `DRAG_TYPE`, `dropTargetOf`). `docs/ready-to-build/virtual-folders.md` lists §4's note drags as not built.
- `docs/ui/interaction-principles.md`, rule 4: "When the user changed something, the result stays in view so they can see it took."

## 1. The drop

A note dragged from the notes column onto a folder in the tree ends up in exactly that folder: the target's folder tag is added and every other folder tag it has is removed (the existing §4 rule). One undo step.

## 2. The note leaves the view; the result stays visible

- Viewing one folder and dropping a note on another, the note no longer matches the folder filter and leaves the column. The maintainer expects this.
- To keep rule 4, the result stays visible elsewhere:
  - the target folder's count in the tree updates at once;
  - a floating message says "Moved to `Projects/Client-A/`" with **Undo**.

## 3. Only root notes

- **Only a root note can be dropped on a folder** (the maintainer, 2026-11-02).
- Why: a child inherits its parent's tags, folder tags included. Given another folder's tag, it would still inherit the old one, so it would be in both folders and wouldn't leave the view: not a move.
- While a child note is dragged, folders don't highlight as drop targets. Dropping it on one does nothing, and a floating message says "Only top-level notes can go in a folder."
- Not chosen: taking the child out of its parent and making it a root note in the folder.

## 4. Invariants

1. A note dropped from the notes column ends up in exactly the target folder.
2. A drag never gives a child note a folder tag.
3. Every drop that changes a note shows where it went and offers Undo.

## 5. Done when

1. Dragging a root note from the column onto a folder replaces its folder tags with the target's, as one undo step.
2. Under a folder filter, the moved note leaves the column; the target's count updates and the floating message with Undo appears; Undo puts it back.
3. A child note can't be dropped on a folder, and says why.
4. `docs/ready-to-build/virtual-folders.md` §4 records the two rules; tests cover a root note with no folder, one folder and two folders, a child note, and Undo.

## 6. Still open

- ~~Whether a folder tag typed on a child note in the tag bar should be refused too.~~ Decided: allowed (§7).

## 7. Checked against the code (2026-11-02, when filed)

- **References hold.** `virtual-folders-service.js` has `DRAG_TYPE` and `dropTargetOf`; the tree takes only a folder dragged onto a folder (an HTML drag, `application/x-metalist-folder`). `interaction-principles.md` rule 4 reads as quoted.
- **A note drag is not an HTML drag.** Notes in the column move with MetaList's own pointer drag (`mouse-events.js`, `moveDragContext`; overlays in `note-drag-indicator-service.js`). It locks to one axis: up and down reorder, left and right indent and outdent. A drag toward the tree, on the left, is today an outdent. Reaching the tree needs that drag to know the tree as a target, and how it gets there is open (below).
- **Floating messages have no action button yet.** `floating-messages.js` cards carry text, detail and a close button only; "Undo" on one is new.

### Open (ask the maintainer)

- ~~How a note drag reaches the tree.~~ **Decided 2026-11-02 (the maintainer): once the pointer is over the tree, the drag becomes a drop into the folder under it**: that folder highlights and the column's drop line goes; back over the column it is a note drag again. No conflict: a root note can't be outdented, so dragging one left changes nothing today (`resolveMoveDragDrop`, `mouse-events.js`). A child dragged over the tree highlights no folder (§3).
- ~~§6's question: a folder tag typed on a child note in the tag bar.~~ **Decided 2026-11-02 (the maintainer): allowed.** It is an ordinary tag; the child is then in both folders, its parent's (inherited) and the typed one, as `virtual-folders.md` §7 allows by hand. Only drags are limited to root notes.

