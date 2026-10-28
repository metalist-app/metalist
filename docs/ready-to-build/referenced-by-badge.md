# Referenced-by badge: backlinks come back as a count

**Status:** Agreed with the maintainer 2026-10-27. Small; ready to build. §1 and §2 are agreed. The details marked *proposed* are suggestions, so adjust any that read badly.

Written from a read-only look at the code, without running it. Check every reference before relying on it; build only what's missing.

---

## 0. Background

- **The backlink index exists:** `app/services/backlinks.py` plus the memory-only backlink index in the note store. It holds source and target UUIDs with occurrence counts, is built at hydration, kept current on edits, and cleared on lock (`docs/ui/references.md`, the backlinks bullets under Rendering Rules).
- **The Referenced by view exists:** `reference_presentation.py` added a `↖` source button that opened a temporary, deduplicated `Referenced by` view of the referring notes in tree order. × or Escape returns to the previous context, as **Go to Source Note** does (`backlinks-navigation-service.js`; `docs/AI-SUMMARY.md`, References).
- **It's hidden today:** no note shows `↖`, because an arrow pointing back reads as "back to where I came from." The docs say the view returns once backlinks have a visual of their own. This note is that visual.
- **Already done, nothing to add:** deleting or cutting a referenced note asks first (*"N other notes reference this note…"*).

## 1. The badge (agreed)

- **A count, not an arrow.** The question a reader has is "is this note used elsewhere, and how much?" A number answers it and implies no direction.
- **It looks clickable, not like a label:** the number inside a circle with a light tint.
  - **Shape:** a circle for 1–9 that stretches into a pill for 10 and up, capped at `99+`.
  - **Colour: the note-link blue,** so it suggests what it does. The number is in that blue (`.note-reference-link-mode .note-reference-link`, `#1d5fb8`, and `#8fbcf0` in the dark theme) on a light tint of it. Hovering deepens the tint and shows the hand pointer; keyboard focus shows a focus ring.
  - **Size:** about the height of a small line of text. It should stand out without competing with the note.
- **Where:** at the top right of any note that other notes reference, where `↖` sat. A note nothing references shows no badge.
- **The count** is the number of notes the Referenced by view lists (deduplicated), not the number of references: one note linking twice counts once.
- **Tooltip:** `Referenced by 3 notes` (`Referenced by 1 note`).

## 2. What it does (agreed)

- **Click or Enter:** opens the existing **Referenced by** view, unchanged.
- **Touch:** a tap opens the view directly.

## 3. Details (proposed)

- **Hover:** after the usual 0.3 s, a card like the link preview card lists the referring notes' first lines. None on touch.
- **Where else it shows:** wherever the old `↖` showed (while editing, inside embeds, full screen, floating windows). Prints and downloaded exports show none, as before.
- **Descendants:** the count matches what the view lists, whatever that is today.
- **Docs:** replace the "backlinks are off for now" bullet in `docs/ui/references.md`.

## 4. Not wanted

- **No unlinked mentions** (notes containing a title as plain text without a link). The `[[` suggestions already make linking quick, and scanning every note for every title would be expensive and noisy.

## 5. Acceptance checks

- A note referenced by three other notes shows a blue `3` badge at its top right. The tooltip reads `Referenced by 3 notes`.
- A note one other note links to twice shows `1`.
- A note nothing references shows no badge. Removing the last reference removes the badge, and adding one brings it back, without a reload.
- 12 referring notes show a pill `12`; 150 show `99+`.
- Clicking the badge, or Enter when it's focused, opens Referenced by listing exactly those notes. × and Escape return to the previous view.
- Light and dark theme: the badge is link blue on its tint, and the tint deepens on hover.
- Touch: a tap opens the view.

## 6. Checked 2026-10-27 (filed from the inbox)

- **Confirmed:** `app/services/backlinks.py` and the note store's backlink index (`note_store.has_backlinks`, `get_backlink_counts`); the hidden button in `app/services/reference_presentation.py` (`note-backlinks-link note-source-arrow`, `↖`); the Referenced by view (`backlinks-navigation-service.js`, `reference-source-navigation-service.js`); the link blue `#1d5fb8` and dark `#8fbcf0` (`.note-reference-link-mode .note-reference-link`, `main.css`); the 0.3 s hover delay (`HOVER_DELAY_MS`, `reference-hover-preview-service.js`); the delete and cut warning (`referenced-note-removal-service.js`).
- **How it's hidden:** `SHOWS_BACKLINKS_BUTTON = False` in `app/services/snapshot.py`. The click path (`note-backlinks-link` in `mouse-events.js`) and the view are still wired.
- **The count is cheap:** the index keeps, per target note, a count per referring note, so the badge's number is how many referring notes it has. `list_backlinks_for_note` returns one entry per occurrence and the browser deduplicates them (`buildBacklinksQuery`), so the view lists exactly that many notes. The index holds direct references to the note only, not to its descendants, so the badge counts what the view lists (§3).
- **Watch when building:** `.note-source-arrow` is shared with the embed's Go to Source Note arrow (`.note-embed-with-source > .note-source-arrow`). Give the badge its own class so restyling it leaves that arrow alone.
- **Layout (decided with the maintainer 2026-10-27):** the badge takes room on the note's first line, as the old button did (`padding-right: 1.6em`). When a reference is added or removed, the first line may rewrap and the badge may change width (`12` to `9`); that's fine. It follows from the user's own edit, so "only the user's action changes the screen" isn't at stake, and avoiding it isn't worth the cost.
- **Open (§3, marked proposed):** the hover card, where else it shows, and the descendants rule.
- **When built:** update `app/services/agent/skills/help-references.md` and replace the "backlinks are off for now" bullet in `docs/ui/references.md`.
