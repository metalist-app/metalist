# Dropping a link from a browser

**Status:** Agreed with the maintainer 2026-11-02. Ready to build. Builds on the folder tree (`docs/ready-to-build/virtual-folders.md`) and dropping files and folders from the desktop (`docs/ready-to-build/desktop-drops-into-folders.md`).

Written from a read-only look at the repo; filed from `docs/inbox/` on 2026-11-03, with the references checked (§8).

---

## 0. Today (from the code)

- MetaList takes a drop only when it carries files: `handleDragOverEvent` and `handleDropEvent` in `keyboard-events.js` both return early unless `transferHasFiles`. A link dragged from a web page carries no files, so dropped on the notes column it does nothing.
- Dropped into the text of a note being edited, the browser's own handling probably inserts it at the drop point. *Check.*
- The tree's `onDragOver` (`virtual-folders-service.js`) accepts `Files` from the desktop and its own folders; not links.
- A bare address in a note already shows as the site's icon, the fetched page title and ` · domain` (`docs/ui/content-formatting.md`, "Every web link looks the same").
- Pasted and dropped URLs already lose their tracking parameters (`docs/ui/paste-sanitization.md`).

## 1. The feature

Drag a link from any browser window, the same browser or a different one, onto MetaList, and it becomes a note holding that link. The link can be one on a page, or the current page itself, dragged from the site icon at the left of the address bar.

Every browser hands a dragged link over as `text/uri-list` (with `text/plain` and often `text/html`; Firefox adds `text/x-moz-url`). A drag from another browser comes through the operating system. *Check* Chrome, Safari and Firefox, each dragged into the others, and the address-bar icon in each.

## 2. What the note holds: the link alone

- **Only the address,** not a title line. The note already shows the page's title through the existing link display, so a title line would repeat it. The maintainer: a title line is redundant.
- (Bookmark import keeps a title line only because it never fetches: thousands of fetches at once to every site in the user's history. One dropped link is one fetch, as for any typed or pasted link.)
- Tracking parameters come off, as for a pasted link.
- **Only `http` and `https`.** Any other scheme (`javascript:`, `file:`, `data:`, …) never becomes a note; the drop is ignored.

## 3. Where it lands

| Dropped on | What happens |
|---|---|
| **The notes column** | A new note at the top holding the link, where a dropped file's note goes today |
| **A folder in the tree** | The same note, also given that folder's tag; the folder's count updates at once, as for dropped files |
| **The text of a note being edited** | The link is inserted at the drop point |

- **No confirm step.** A web page can't fake a drag into another page or window: only the user's own drag carries the link, as with a paste. Undo covers a mistake.
- **A drag that also carries files** (some browsers attach the image when an image is dragged from a page) stays a file drop, as today.
- The new note stays in view, so the user sees it arrived (`docs/ui/interaction-principles.md`).

## 4. Not covered

- **Selected text dragged from a page** carries no address for the page, so it stays plain text, as today. A quote with its source belongs to the web clipper (`docs/future-plans/web-clipper.md`).

## 5. Invariants

1. A dropped link becomes a note with the link alone; the existing title fetch shows its title.
2. Only `http` and `https` addresses become notes.
3. Only the user's own drop creates the note.
4. A link dropped on a folder ends up in exactly that folder.

## 6. Done when

1. A link dragged from a page, or from the address bar's site icon, in Chrome, Safari and Firefox, makes a top note on the column, a note in the folder on a tree folder, and goes in at the drop point in a note being edited.
2. Several links make one note each, in order; a link dragged from within MetaList makes no note; other schemes are ignored; drags carrying files behave as today.
3. `docs/ui/` (the drop rules in `paste-sanitization.md`, the tree in `virtual-folders.md`) and the help describe it; tests cover a link on the column, on a folder, into an edited note, several links at once, a link dragged from within MetaList, a `javascript:` link, and a link with tracking parameters.

## 7. Also decided

- **Several links in one drop** (Firefox can drag several tabs at once): one note per link, in the order given.
- **A link dragged from inside MetaList** (a link in a note, dropped on the column): today's behavior, no new note.

Nothing is open.

## 8. Checked against the code (2026-11-03, when filed)

Every reference in §0 holds: `handleDragOverEvent` and `handleDropEvent` (`keyboard-events.js`) return early unless `transferHasFiles`; the tree's `onDragOver` (`virtual-folders-service.js`) takes files and its own folders; "Every web link looks the same" (`docs/ui/content-formatting.md`); tracking parameters come off pasted and dropped URLs (`docs/ui/paste-sanitization.md`, `url-tracking-cleaner.js`); `docs/future-plans/web-clipper.md` exists.

- Not checked yet: what a link dropped into the text of a note being edited does today (§0, second point), and how each browser hands over a link dragged from another browser or from the address bar (§1). Both are for the first step of building.
- The drop routing in `keyboard-events.js` changed on this branch (`feature/virtual-folders`, uncommitted on 2026-11-03: folders dropped from the desktop, files dropped on a tree folder): a link drop joins that routing.
