# Making the page easier to keep right: one owner for the search contexts, and what follows from it

Proposals from 2026-11-16, after two days of getting `main` green and releasing 0.30.1. Nothing here is agreed or scheduled. The maintainer asked for the ideas to be written down, then for a second pass through the code to look for better ones. This is the version after that second pass: the plan now starts on the server, not in the browser.

## Why these ideas

Between 2026-10-09 and 2026-11-15, GitHub's release gate on `main` failed 39 times in 79 runs, and the "Browser suites" run passed once in 38. Most of that was not broken features. Reading the failures one by one showed three causes behind nearly all of them.

1. **Two owners for the same thing, and many actors with no order between them.** The search contexts live both in the page and on the server (see "What the second pass found"). Around them, commands, server answers, changes from other views, scroll saving and once-a-second checks all act on their own schedule and coordinate through flags and timers: in `mode-manager` there are 47 `setTimeout` calls, 7 intervals, 14 observers and about 53 flag-like fields. Twenty-six commits in five weeks each fixed one meeting of two of them.
2. **The riskiest browser code cannot be run by a unit test.** 155 of 339 modules are never imported by one, among them `keyboard-events.js` (4,735 lines), `mouse-events.js` (3,133) and the command palette controller (3,298), the three most changed files. Only browser suites cover them, and those are slow and sensitive to timing.
3. **The checks run after the merge, on machines unlike the maintainer's Mac.** Windows, Linux and Firefox first see a change on `main`.

### What the two days showed

Each of these was a real bug, found only because a browser suite happened to hit the timing:

| Bug | What met what |
| --- | --- |
| A search typed after an AI answer was thrown away | The user's typing and a re-read of the contexts already under way |
| The page redrew itself a second after a click into or out of the search box | The view's own search lock, counted as a change made elsewhere |
| "tab ids mismatch", refused by the server (ended 2026-11-17: a copy that leaves a tab out keeps it) | A whole-copy save read before the view made a new tab |
| The Untagged view turned itself off (`tab-switching`; fixed 2026-11-17, idea 4's first part) | A setting just changed and a re-read of the contexts begun before it |
| A tap on a sort option did nothing | A command arriving while another ran is dropped |
| The first characters typed after a click in the tag bar were lost | Typing and a tidy-up scheduled by the click |

The first four are the same fault: the page's copy of the contexts and the server's disagreeing. Every fix so far was one guard for one meeting. The class is still there.

## What the second pass found

The server and the page share ownership of the search contexts, half one way and half the other.

- **The notes list has one owner already, the server.** It keeps the last view it sent each tab (the warm view, `docs/design/differential-view-protocol.md`) and sends only differences. The page holds no copy that can disagree. This part has been stable.
- **The newer context settings have one owner too.** Sort, date range, file filter, Untagged view, new tab and delete tab each have their own request (`/notes/tab-state/sort-mode` and its siblings): the page says what the user did, and the server answers with the result.
- **The older ones have two.** The search text, which tab is active, the tab order, scroll positions and reference pages are kept in the page (`mode-context.js`). The page sends the server its whole copy (`persistTabStateSnapshot`, 15 call sites, 13 of them in `keyboard-events.js`), the server merges it in an 89-line function that compares versions (`TabStateStore.update`), and the page reads the whole thing back (`reloadTabStateFromServer` and `hydrateTabState`, 15 call sites).

So the code is midway through a move it already started, and the unmoved half is where the bugs are.

Not traced yet: each of the 15 save sites, one by one. Some may be harder to convert than they look.

## The ideas, in the order to do them

None is a rewrite. Each can be done in pieces while MetaList keeps shipping.

### 1. The server owns the search contexts

Finish the move. For each thing still saved as part of the whole copy, the page sends one small request naming what the user did, and gets back exactly what changed:

- set this context's search (**built 2026-11-17**: `POST /notes/tab-state/search`, `TabStateStore.set_search`; the whole-copy save no longer takes a search, and the record of "what each view was last told" is gone; tests in `tests/unit/test_search_text_request.py`);
- show this context in this view (**built 2026-11-17**: `POST /notes/tab-state/shown`, `TabStateStore.show_tab`; the whole-copy save no longer takes the tab shown; tests in `tests/unit/test_shown_context_request.py`);
- move this context in the order (**built 2026-11-17**: `POST /notes/tab-state/move`, `TabStateStore.move_tab`; the whole-copy save no longer takes an order, so a copy saved before a view heard of another view's move cannot undo it; tests in `tests/unit/test_move_context_request.py`);
- this context is scrolled to here (per view) (**built 2026-11-17**: `POST /notes/tab-state/scroll`, `TabStateStore.set_scroll`, one request for each tab whose scroll changed, naming the version the page holds so a scroll measured before the tab's notes changed is not taken; the whole-copy save no longer takes a scroll and now carries only the reference pages; tests in `tests/unit/test_scroll_request.py`);
- open, go back from and close a reference page (**built 2026-11-18**: `POST /notes/tab-state/reference-page`, `TabStateStore.set_reference_page`, for a page opened, a page showing something else and a tab of note IDs the view takes as a page; it sets the page's search with its record. Closing is the tab's deletion, and another search in a page ends it on the server. The page now sends no whole copy at all (`persistTabStateSnapshot` sends only requests by name); tests in `tests/unit/test_reference_page_request.py`).

**Removed 2026-11-18:** the server's side of the whole-copy save (`TabStateStore.update`, `POST /notes/tab-state`, its request type). Tests save a view's place as the page does (`tests/unit/tab_place_saving.py`). A released page (0.30) left open after the update, which still posts a copy, gets a 405 and a brief error banner until it is reloaded. The whole-copy re-read stays.

Then the whole-copy save and the whole-copy re-read are removed, with the merge function and its version comparisons.

Why this comes first:

- **It removes the conflict instead of refereeing it.** With one owner there is no second copy to overwrite the user's.
- **It is in Python,** where there are 5,500 tests and one lock that already makes changes take turns (`track_mutation`). The browser is where testing is weakest.
- **Half of it is built** and has been the reliable half, so the pattern is known.
- **A change from another view becomes a small fact** ("view B set context X's search to Y") that a view applies to what its user has not touched. A view's own change never comes back to it as news, because each change names its author. The per-view revision added on 2026-11-15 (`tab_state.py`, `shared_revision(view_id)`) is a patch on the present design, and this removes the need for it.

How to get there: one kind of change at a time, the search text first (it is the one users lose), each with its request, its tests, and the removal of that field from the whole copy. The whole-copy save goes when its last field has moved.

Cost: the code is days of work. Until it is all on `main`, tried by the maintainer and trusted: two to three weeks of calendar time, mostly waiting on checks and on hands-on trying, with MetaList usable throughout.

### 2. Test the server's state by simulation

With the contexts owned in one place, a unit test can throw thousands of random orderings of requests from two or three views at `TabStateStore`, and check rules that must always hold:

- a view's own change is never undone by an older request of its own;
- what a view is told always matches what the server holds;
- a change one view makes reaches every other view, once;
- no ordering of requests is refused that a person could cause by clicking.

`hypothesis` is already installed and unused, and it shrinks a failing ordering to the shortest one that still fails. This would have found the "tab ids mismatch" refusal, the typed-search bug and the self-redraw without a browser. It can start as soon as the first field has moved.

**Built 2026-11-18:** `tests/unit/test_tab_state_simulation.py`, a `hypothesis` state machine. Three views (the third opens part-way) each act on the tabs they were last told of, so stale requests come up by themselves: a tab made, deleted, shown, moved, scrolled, searched, sorted, filtered, made a reference page, the search box left, a re-read, a server restart. After every request it checks eight rules: only calm refusals; a view's own change holds; a request changes only what it names, in every view; the answer matches the server; each view's shared revision rises exactly when what it shares changed; the version rises with every visible change; the state is well formed; a restart loses nothing. The unit run plays 200 fixed orderings of 30 requests in about 3 seconds; `TAB_STATE_SIMULATION_EXAMPLES=N` on the same test plays more, of 50 requests and different each time (20,000 orderings of 50 requests passed on 2026-11-18). The test was checked against five deliberately broken stores (a move that changes the tab shown, a stale scroll taken, a change that keeps the version, a search not saved, a search that resets the sort order): it catches each.

**Found by it, 2026-11-18: three fixed, one left as a known limit.**

1. **Left as a known limit (the maintainer, 2026-11-18): a vault's first tabs are not saved until their first change.** A server restarted before any change makes a new first tab with a new id, and a page still open asks about the old one and is refused once; a reload shows the new one. Only a new vault, before its first search, new tab or scroll. Saving them when first read would put a write in the request that loads the page, which also runs before a protected vault is unlocked, when nothing can be saved. The simulation restarts the server only after a first change: the one thing it leaves out.
2. **Fixed 2026-11-18: a search context never becomes a reference page.** `set_reference_page` took a search context of note ids as the view's page, even while pages were opened from it: those pages were then opened from a page, and in another view from a tab that view no longer saw (`adoptOrphanReferenceTabs` asked for this by itself on load). Now only a tab made as a page is one: the request is refused for a search context, every answer names the view's own pages (`pageTabIds`), and the page takes back only those. A context whose search is a note id is a search like any other. Cases in `tests/unit/test_reference_page_request.py`; the simulation asks for it and expects the refusal.
3. **Fixed 2026-11-18: every reference page leads back to a search.** `set_reference_page` took a page whose search context was a page, or the page itself, and two pages each opened from the other, so going back would never reach a search. The page never sends these; anything else that posts could. Both are refused now (`_tabs_gone_back_through`), after the rule for a tab deleted a moment ago; tabs already saved that way load as they are. Cases in `tests/unit/test_reference_page_request.py`; the simulation sends them and expects the refusal, and checks that no page's way back comes round.
4. **Fixed 2026-11-18: a request about a tab deleted a moment ago changes nothing and is no error, whatever it asks.** Search, tab shown, move, scroll and reference page were answered "no change"; sort order, date range, Files filter, Untagged view, a folder chosen, a delete and a new tab made from it were refused, which showed an error for a context the user no longer had. All now answer "no change" (`tab_state.py`, `_is_deleted_meanwhile_locked`; a new tab is not made and the answer has no `newTabId`), the page does nothing more (`wasTabDeletedElsewhere`, `keyboard-events.js`) and takes the list as it hears of any delete. A tab the server never had is still refused, and so is another view's reference page, whose sort and filters a view could change until now. The server forgets which tabs are gone when it restarts, and then refuses: left as it is. Cases in `tests/unit/test_requests_on_a_deleted_tab.py` and the `live-changes` browser suite; the simulation holds every request to the one rule.

### 3. Check before merging

**Adopted 2026-11-18** (the maintainer, after 0.31.0's push to main went red in two suites the changes had not touched): COMMIT FEATURE pushes the branch and runs both workflows on it (`scripts/check_branch.py`); "Publish to PyPI" runs its matrix by hand on any branch and still publishes only for a version tag. At COMMIT FEATURE, not at each checkpoint. Rules in `AGENTS.md`, "Check Before Merging".

Run both GitHub workflows on the branch at each checkpoint, before it merges. They take about ten minutes when machines are free, and the repository is public. `main` then confirms what the branch already showed. This is process, not refactoring, and the cheapest item here: about an afternoon. It reverses the rule "the full matrix runs once, on main" in `AGENTS.md`. Worth doing before idea 1 begins, so each step of that move is checked on Windows and in Firefox before it lands.

### 4. In the browser: apply the server's answers in order

What is left for the page once the server owns the contexts is a thin rule: answers are applied in the order the server made them, and one that is older than what the page already shows is dropped. Commands wait their turn instead of being dropped when another is running; which commands should not run late (a click meant for a list that has since changed) is decided once, in that rule.

**Built 2026-11-17, for the re-read of the tabs:** a re-read (`reloadTabStateFromServer`) that a change of the page's own overtook, or that is older than an answer the page took meanwhile, is not applied; the tabs are read again once the page's changes are answered (`tab-state-service.js`, `fetchTabStateNotOvertaken`). The server's side of it: every change a view can see raises the version (`tests/unit/test_tab_state_version_rises.py`). Checked in `tests/unit/tab_state_service.test.mjs` and, with the re-read's answer held back, in the `live-changes` browser suite (Untagged, sort order, a context opened, a context deleted). Not yet: the answers to the page's own actions, applied in about ten places, and commands waiting their turn.

**Built 2026-11-22, its first step: turns.** Commands, background work (the infinite scroll, a change made elsewhere, link titles, the scroll saver, the floating windows) and what the server sends (a reference page it closed) take turns in the order asked, and every list refresh runs in one (`turns.js`, `CommandGate.runBackground` and `queueBackground`; `docs/ui/command-gate.md`, "Turns"). It was left unbuilt from 2026-11-18, when the whole-copy save went and this became possible, until a race of exactly this kind failed the 0.35.0 branch check. **Still to build:** the controls that work outside the gate become commands (listed in `command-gate.md`, "Known gap"), commands wait instead of being dropped, and idea 5.

Before the second pass this was the main proposal: a queue in the browser through which every change to the page's state passes, with one function applying them. That is still the right shape, but it is now a small piece, days of work, because the conflicts it was meant to referee are gone. The store that refuses a value set twice (`application-state.js`) keeps its purpose for commands; values observed from outside (a clock reading, a server answer) are simply applied.

### 5. Let the app say when it has finished

Browser suites guess that MetaList is done by waiting for 300 ms of quiet (598 calls) or by sleeping a fixed time (393 calls). With answers applied in order, "nothing is waiting to be applied and no request is in flight" is a fact the app can state, and every suite waits on that one thing. Nearly free after idea 4.

**Built 2026-11-22, in the suites' harness (`scripts/browser-app-idle.mjs`), not in the app.** MetaList has finished when all of this holds, and still holds once the browser has drawn two more frames:

- no command or background work has the turn (`turns.js`), and nothing is loading;
- no request is in flight;
- MetaList has put off no work: the harness counts every timer of at most 750 ms and every animation frame the page asks for, by wrapping `setTimeout` and `requestAnimationFrame` before any page script runs, so a timer added later is counted without registering itself;
- no change made elsewhere is about to be shown (`isChangeAboutToBeShown`, live-changes-service.js, the one addition to the app);
- no image, font or stylesheet is loading.

No time is waited on top: the `quietMs` the suites pass is no longer read, and goes when their fixed pauses do.

What it took to get there, each found by a suite that then never became idle or failed:

- **A suite's own watcher is not MetaList's work.** Several suites run a frame loop in the page to sample positions. Only work put off by MetaList's own modules counts, told by where the call came from (`/static/` in its stack).
- **Work that waits for the user is not about to happen.** A change made elsewhere retries every 250 ms for as long as a dialog, a menu or the find bar is open. That timer is not counted; the app says whether a change is about to be shown.
- **A resized window is no work of MetaList's.** The layout follows in the next frames, hence the two drawn frames.
- **The harness must not watch with the page's timers.** `page.waitForFunction` does, and would count itself: the harness asks from outside, every 50 ms.
- **Measure on a quiet machine.** Two whole-suite runs were made while the Mac rendered something else (load above 100): the server stalled and eight suites failed for that alone. A run's failures mean nothing until the load has been looked at.

Not done: the 421 fixed pauses in the suite files, and removing the unread `quietMs` from 95 of them. Checked so far in Chrome, suite by suite; the first whole run in both browsers is GitHub's.

### 6. Move decisions out of the big event files

The event files mix "what key was pressed" with "what should happen". Moving the second part into small modules a test can import (as the many 20 to 130-line policy files already do) brings the most changed code under unit tests. It also retires the tests that read source files as text (71 files, 34 of which run nothing), which break on a rename and cannot catch wrong behavior. Done file by file, whenever an event file is being changed anyway; idea 1 already takes 13 of the whole-copy saves out of `keyboard-events.js`.

### 7. Decide how much multi-view to keep

Several views on one vault at the same moment is rare for the three people who use MetaList. A much simpler rule would be: one view is active; another view opened meanwhile shows "MetaList is in use on your Mac" with Take Over, and is read-only until then. That would remove search locks and live merging altogether, at the price of editing in two places at once.

Before the second pass this was the first decision to make. With the server owning the contexts, two views are far less fragile, so it is less urgent: decide it after idea 1, when it is clear how much trouble multi-view still causes.

### 8. Push, don't poll

The page asks the server several questions every second (status, the chat's live state, background work). One open stream from the server delivering changes in order (server-sent events, which browsers support without a library) would replace them and their timers. There is no server-to-page stream in the code today, so this is new machinery. Later, and only if full multi-view stays.

## More logic that could move to the server

Asked by the maintainer on 2026-11-16: Python is far quicker to test than several browsers on several systems, so what else that the page decides today could the server decide? Surveyed by size and by each module's opening comments, not read line by line; the sizes are lines of browser code.

The rule this suggests: **the browser does what needs eyes and hands (pixels, the caret, the pointer, the clipboard, focus, animation); the server does everything that is a decision about text or state.**

| What | In the browser today | Why it could move |
| --- | --- | --- |
| Is this search well-formed, and what does it mean | `search-syntax-service.js` (891) | Python has its own parser (`search_query.py`, 388), so the rules exist twice. Searching and suggestions already ask the server. |
| Is this tag string valid, and how is it tidied | `tag-syntax-service.js` (1,164), `tag-bar-service.js` (577) | The same rules twice again; a test exists only to check the browser lowercases as Python does. |
| Cleaning pasted HTML | `html-paste-sanitizer-service.js` (1,876), `note-html-sanitizer.js` (314) | The server already cleans every save with its own sanitizer. A paste could be sent, cleaned and returned in one request. |
| Guessing a paste's format (CSV, Markdown, code) | `paste-format-detection-service.js` (463), `paste-format-guess-service.js` (409) | A decision about text. The server already draws the preview of the guess (`/notes/format-preview`). |
| Removing formatting from a note or a selection | `selected-formatting-removal-service.js` (667), `remove-formatting-service.js` (502) | A rewrite of note HTML. The edit preview already sends the note with a mark at the caret; a selection can be marked the same way. |
| Which reminders are due and what to show | `reminder-surface-service.js` (1,290) | The server already holds the reminders and their schedule; the page keeps a mirror to decide when to show them. |
| Folders, reference pages and their navigation | `virtual-folders-service.js` (699), `reference-source-navigation-service.js` (692) | Part of the search contexts: covered by idea 1. |
| The list of commands, and when each applies | `command-palette-controller.js` (3,298), `endpoint-registry.js` (818) | The AI's help keeps a second catalog of the same commands. One list on the server would serve both. Filtering as you type can stay in the page. |
| The list of AI models | `ai-providers.js` | Written as a copy of `ai_catalog.py`. |

What stays in the browser, because it needs the page itself: holding the view still (`viewport-hold-service.js`), applying the server's differences to the list (`differential-view-service.js`), the caret and selection, dragging, typing in a note, animation, the clipboard.

Costs to weigh:

- **A request per decision.** A few milliseconds on the same computer, tens on the home network. If MetaList is ever hosted, decisions made at every keystroke (is this search well-formed) would lag, so those would need to stay local or be asked once typing pauses, as suggestions already are.
- **Typing must never wait.** Anything moved must leave what the user types on screen at once; the server's answer may then tidy or mark it. The tag bar fix of 2026-11-16 is the rule: an answer never rewrites text typed since it was asked for.
- **Each move deletes a second copy of some rules,** and with it the tests that only check the two copies agree.

Order, if this is taken up: the two with rules already on the server first (search and tag syntax), because they remove duplication; then paste cleaning and format guessing; then formatting removal. Reminders and the command list are independent and can go at any time.

## Looked for, and not proposed

- **A library to replace the list-update code** (the differences the server sends and how the page applies them). It is tied to the scroll-holding and animation rules in `docs/ui/interaction-principles.md`; swapping it would be a rewrite for no gain.
- **Having the server drive the whole page.** Editing a note has to stay in the browser, so server ownership stops at the contexts and the list.

## Suggested order

1. Idea 3, checks before merging: about an afternoon.
2. Idea 1, the search text first, then the active context, the order, scroll, reference pages.
3. Idea 2 from the first moved field on.
4. Ideas 4 and 5 once the whole-copy save is gone.
5. Idea 6 alongside, file by file.
6. Idea 7 as a decision after idea 1; idea 8 only if full multi-view stays.

## Open questions for the maintainer

- Scroll positions are per view and change often: one request per settled scroll, or kept in the page and sent only when the view leaves the context?
- While a field is being moved, old and new paths exist side by side. How long is acceptable, and should each field be released on its own?
- Should the pace of new features slow while idea 1 is under way, or run beside it?
- Idea 7: is editing in two views at the same moment worth keeping?

## Related

- The review these came from is in the session of 2026-11-15 (not kept as a file).
- `docs/design/differential-view-protocol.md`: how the server already owns the notes list.
- `docs/design/multi-view-editing.md`: what multi-view does today.
- `docs/ui/command-gate.md`: one command at a time, as built.
- `docs/ui/interaction-principles.md`: the rules any of this must keep.
- `docs/future-plans/model-checking-protocols.md`: checking the commit and shutdown protocols with TLA+; related in spirit to idea 2, a different thing.
