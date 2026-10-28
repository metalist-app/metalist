# Quoted text search updates as you type; the closing quote is added for you

**Status:** Agreed with the maintainer 2026-10-28. Ready to build. Small.

Written from a read-only look at the repo. Check the code references before relying on them.

---

## 1. Today

- Searches already run as you type, `SEARCH_DEBOUNCE_MS` (300 ms) after typing stops (`app/static/js/modules/config.js`). Tag searches update live.
- An open quote stops that: `"neural net` is incomplete, incomplete queries are skipped (`executeSearchWhenIdle` in `app/static/js/modules/mode-manager/events/search-events.js`), and the field warns `Close quote with "` (`docs/ui/search-syntax.md`, "Completeness + Warnings"). Nothing changes until the closing quote is typed.
- `Cmd+F` (Find) already reacts as you type (`docs/ui/find.md`). Quoted search should feel the same.

## 2. The rule

1. **An open quote at the end of the query counts as closed** for running the search. `"neural net` searches for `neural net`; the results and the phrase highlights (`searchHighlightPhrases`) update as you type, after the usual pause. Excluded text too: `-"draft` hides notes as you type. Drop the `Close quote with "` warning for this case.
2. **Only the last term can be open.** An unclosed quote earlier in the query would swallow the rest, so it can't occur; leave that as is.
3. **The text is taken as typed, including a trailing space:** `"fat ` means the word "fat" (an edge space marks a word edge, `docs/ui/search-semantics.md`, Text Terms) until the next letter. Check that query normalization (trimming trailing whitespace) doesn't eat a space inside an open quote.
4. **No minimum length:** `"a` searches like anything else. Matching is a substring check against in-memory text (`app/services/search_index.py`, `_verify_note_matches_locked`), and the list draws only its band of root notes, so one letter matching everything costs about what the empty search does. Measure it once on a large vault (about 15,000 notes) to confirm.
5. **Close the quote automatically.** When the user does something else with a quote still open (Enter, leaving the search field, switching tabs, clicking or editing a note, any command that saves the tab's search), add the matching closing quote (`"` or `'`, whichever opened it) to the field and to the saved query. An open quote with nothing after it is removed rather than turned into `""`. A trailing backslash inside the open quote (an unfinished escape) is dropped before closing.

## 3. Done when

1. Typing `"neur` shows the notes containing "neur", and each further letter narrows them, without typing the closing quote; the phrase highlights follow.
2. `-"dra` hides notes containing "dra" as it's typed.
3. `"a` runs, and stays responsive on a large vault.
4. Pressing Enter, leaving the field, or switching tabs with `"neural net` open leaves `"neural net"` in the field and in the tab's saved search; with `'neural` open, `'neural'`; with a lone `"`, nothing.
5. `"fat ` (trailing space) matches "fat cat" but not "father".
6. Tests cover 1–5; `docs/ui/search-syntax.md` (Completeness) and `docs/ui/search-semantics.md` describe the open-quote rule and the automatic closing.

## Found when filed (2026-10-28)

- References check out: `SEARCH_DEBOUNCE_MS` (`config.js:13`), the incomplete-query skip in `search-events.js`, the `Close quote with` warning (`search-syntax-service.js:286`), `searchHighlightPhrases`, `_verify_note_matches_locked` (`search_index.py:1929`), `docs/ui/find.md`.
- §2.3 is a real conflict today: the browser trims the normalized query (`normalizedTerms.join(' ').trim()`, `search-syntax-service.js:400`) and the server trims it again (`parse_search_query`, `search_query.py:94`), so `"fat ` would lose its space on both sides. Both need to keep a space inside an open last quote.
- An open quote is left out of the sanitized query (`sanitizedTerms`), which is what runs while a query is incomplete; that is where the open last term has to be let through.
- No open questions.
