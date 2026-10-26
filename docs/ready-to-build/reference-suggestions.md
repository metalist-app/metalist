# Typing `[[` suggests notes to reference

**Status:** Agreed with the maintainer 2026-10-26. Ready to build, not started; filed here from `docs/inbox/` on 2026-10-26 (see "Found when filed").
**Scope:** a faster way to enter a note reference: type `[[`, choose a note from suggestions, and get `[[UUID]]`. Update `docs/ui/references.md` with the result.

Written without running the code. Check every reference before relying on it; build only what's missing. Works with the link-text override (`[[UUID|text]]`, `docs/ready-to-build/reference-link-text.md`), if built.

---

## 1. Behavior

- In the note editor, typing **`[[`** opens a small suggestion list (the same style of list as tag suggestions). As the user keeps typing, the list updates. **Choosing a suggestion inserts `[[UUID]]`** for that note and closes the list.
- **It is an ordinary reference.** Nothing about references changes: a note whose only content is the reference becomes an embed, otherwise a link; `|text` overrides the shown text if that feature exists.
- **Any note can be suggested, child notes included.** The note being edited is not suggested.
- **No matches:** the list shows nothing; the typed `[[…` stays as plain text, as today.
- **Escape** closes the list and leaves the typed text.
- After choosing, typing **`|`** continues into link text (if the override is built), placed before the closing `]]`.

## 2. Matching and ranking

Four tiers, strictly in order (a lower tier never ranks above a higher one):
1. **Exact match on the note's first line**
2. **Fuzzy match on the first line** (tolerant of small typos and partial words; exact always wins over fuzzy)
3. **Exact match in the note's content** below the first line
4. **Fuzzy match in the content**

**Ties within a tier: most recently edited first.** Don't use "recently viewed" (the maintainer ruled it out as ill-defined).

Choose a sensible cap on the number shown (for example 8–10) and document it.

## 3. What each suggestion shows

- **The note's first line** (that's what the link will display by default).
- **For content matches (tiers 3–4): a short snippet** beneath it, greyed, with the matched text highlighted, for example `…the Bayes factor compares…`, so it's clear why the note appeared. First-line matches need no snippet.
- **`@password` notes:** suggested by first line only; **never show a content snippet** for them (and never match their protected values).
- Text in suggestions is plain text, escaped, never rendered as HTML.

## 3a. Reuse

Use the existing search and its normalization where possible rather than a separate index. Encrypted content is matched in the user's process as search does today; nothing new is sent anywhere.

## 4. Tests

- `[[` opens the list; choosing inserts `[[UUID]]`; the result renders as link or embed exactly as a pasted reference would.
- Ranking: an exact first-line match outranks a fuzzy first-line match, which outranks any content match; exact content outranks fuzzy content.
- Ties are ordered by most recent edit.
- A content match shows a snippet with the match highlighted; a first-line match shows none.
- Child notes are suggested; the note being edited is not.
- `@password` notes never show snippets; their protected values never match.
- No matches → no list, text unchanged; Escape closes the list.
- HTML in a first line or snippet is shown as text.

## Found when filed (2026-10-26)

1. **An `@password` note's first line is the password:** the note's content is the secret itself, shown blurred in view mode (`docs/ui/content-formatting.md`). "Suggested by first line only" (§3) would show passwords in plain text in the list, and typing a password would match it. Compact references to credential notes are already masked (`is_credential_preview` in `app/services/embedded_references.py`). **Open:** never suggest `@password` (and `@username`) notes, or suggest them masked (`••••••••`), matching only something else such as the parent's first line.
2. **Nothing of this exists:** no `[[` handling in the editor. The tag suggestion list (`docs/ui/tag-bar.md`) belongs to the tag bar's input field; a list anchored at the caret inside the note editor (`contenteditable`) is new.
3. **No fuzzy matching exists** to reuse: search matches every text term as a substring (`docs/ui/search-semantics.md`, "A note must contain every required text term as a substring"), with its normalization. Tiers 2 and 4 need new matching; §3a's "use the existing search" covers tiers 1 and 3.
4. **"Most recently edited"** is each note's `updated_at`, which `Repair: Reset Updated Time to Created Time` can rewrite (`docs/ui/command-palette.md`); fine as the tie-break.
5. Inserting `[[UUID]]` while editing changes what the note becomes on leaving edit mode (an embed when it is the note's only content, `docs/ui/references.md`); the note already says so (§1).

