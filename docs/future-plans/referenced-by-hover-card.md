# Referenced by badge: a hover card

**Status:** Proposed 2026-10-27 with the badge; left for later by the maintainer 2026-10-28, when the badge was built (`docs/ui/references.md`, Referenced by badge). Not scheduled.

- **Hover:** resting the pointer on a note's Referenced by badge, after the usual 0.3 s (`HOVER_DELAY_MS`, `reference-hover-preview-service.js`), shows a card like the link preview card that lists the referring notes' first lines, in tree order (the notes the Referenced by view lists).
- **None on touch.**
- Open when picked up: how many first lines the card shows before it cuts off (the badge counts up to `99+`), and whether a line in the card is itself a link.
