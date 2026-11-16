# Making the page easier to keep right: one writer, and what follows from it

Proposals from 2026-11-16, after two days of getting `main` green and releasing 0.30.1. Nothing here is agreed or scheduled. The maintainer asked for the ideas to be written down before anything else is done with them.

## Why these ideas

Between 2026-10-09 and 2026-11-15, GitHub's release gate on `main` failed 39 times in 79 runs, and the "Browser suites" run passed once in 38. Most of that was not broken features. Reading the failures one by one showed three causes behind nearly all of them.

1. **Many things change the page at once, and none owns it.** Commands, server answers, changes from other views, scroll saving and once-a-second checks all touch the notes list and the search contexts. They coordinate through flags, timers and "is anyone busy" checks: in `mode-manager` there are 47 `setTimeout` calls, 7 intervals, 14 observers and about 53 flag-like fields. Twenty-six commits in five weeks each fixed one meeting of two of them ("a sort while a view request is in flight").
2. **The riskiest browser code cannot be run by a unit test.** 155 of 339 modules are never imported by one, among them `keyboard-events.js` (4,735 lines), `mouse-events.js` (3,133) and the command palette controller (3,298), the three most changed files. Only browser suites cover them, and those are slow and sensitive to timing.
3. **The checks run after the merge, on machines unlike the maintainer's Mac.** Windows, Linux and Firefox first see a change on `main`.

### What the two days showed

Each of these was a real bug, found only because a browser suite happened to hit the timing:

| Bug | What met what |
| --- | --- |
| A search typed after an AI answer was thrown away | The user's typing and a fetch of the search contexts already under way |
| The page redrew itself a second after a click into or out of the search box | The view's own search lock, counted as a change made elsewhere |
| A tap on a sort option did nothing | A command arriving while another ran is dropped |
| The first characters typed after a click in the tag bar were lost | Typing and a tidy-up scheduled by the click |
| The Untagged view turned itself off (`tab-switching`, not yet fixed) | A setting just changed and a fetch of the contexts begun before it |
| A red error while scrolling in Firefox | Two scroll events in one tick of the clock, in a state that refuses a value set twice |

Every fix was local: one guard for one meeting. The class is still there.

## The ideas, most leverage first

None is a rewrite. Each can be done in pieces while MetaList keeps shipping.

### 1. One writer for the page's state

Everything that wants to change state posts a message to one queue: "the user typed a search", "the server answered request 41", "another view changed context X". One function applies them in order: given the state and one message, it returns the next state and a list of things to do (send a request, draw the list). Nothing else writes.

- Two changes can no longer meet: they are applied one after the other, by construction.
- The function has no browser in it, so a unit test runs it in milliseconds.
- "A command is dropped while another runs" goes away: the second command waits in the queue. Which commands should not run late (a click meant for a list that has since changed) is decided once, in the function.
- The store that refuses a value set twice (`application-state.js`) keeps its purpose for commands; values observed from outside (a clock reading, a server answer) arrive as messages and are simply applied.

How to get there: start with the notes list and the search contexts only. Move one kind of change at a time into the queue (the view refresh, then the live changes, then scroll saving), with the old path removed as each moves. Old and new run side by side during the move.

Cost: weeks of careful work. It is the largest item here and the one the others lean on.

### 2. Test it by simulation

With the logic in one function, a test can feed it thousands of random orderings of messages, with a made-up clock and a made-up server, and check rules that must always hold:

- the search box and the list show the same search once things settle;
- nothing typed is ever lost;
- nothing is shown that the server did not send;
- a setting the user just changed is never undone by an older answer.

The orderings come from a seed, so a failure can be replayed exactly. `hypothesis` is already installed for the Python side and unused; the browser side needs a small generator of its own. This would have found the typed-search bug, the tab-state race and the self-redraw without a browser.

### 3. Send changes, not copies

When another view changes a search context, a view today saves its place, reads every context from the server and replaces its own (`adoptSharedSearchContexts`). That is why a view's newer edit keeps being overwritten. The server could send what changed and who changed it: "view B set context X's search to Y". A view applies that to what its user has not touched, and ignores a change it made itself, because each change names its author.

The per-view revision added on 2026-11-15 (`tab_state.py`, `shared_revision(view_id)`) is a patch on the present design. This removes the need for it.

### 4. Push, don't poll

The page asks the server several questions every second (status, the chat's live state, background work). Each poll is a timer, and some answers start redraws. One open stream from the server delivering changes in order (server-sent events, which browsers support without a library) would replace them. Ordering comes with it, which idea 3 needs.

Only worth doing if full multi-view stays (idea 5).

### 5. Make multi-view simpler as a product

Several views on one vault at the same moment is rare for the three people who use MetaList, and it is where most of these bugs live. A much simpler rule:

- one view is active;
- another view opened meanwhile shows "MetaList is in use on your Mac" with Take Over, and is read-only until then;
- taking over makes the other view read-only in turn.

What goes: search locks, live merging of changes, re-reading the contexts, the per-view revision. What is lost: editing in two places at the same time. Reading in two places still works.

This is a product decision before it is a technical one, and its answer changes how much of ideas 3 and 4 is needed at all. It should be decided first.

### 6. Let the app say when it has finished

Browser suites guess that MetaList is done by waiting for 300 ms of quiet (598 calls) or by sleeping a fixed time (393 calls). With one queue, "the queue is empty and no request is in flight" is a fact the app can state, and every suite waits on that one thing. Small on its own, and nearly free after idea 1.

### 7. Check before merging

Run both GitHub workflows on the branch at each checkpoint, before it merges. They take about ten minutes when machines are free, and the repository is public. `main` then confirms what the branch already showed. This is process, not refactoring, and the cheapest item here. It reverses the rule "the full matrix runs once, on main" in `AGENTS.md`.

### 8. Move decisions out of the big event files

Independently of the queue: the event files mix "what key was pressed" with "what should happen". Moving the second part into small modules a test can import (as the many 20 to 130-line policy files already do) brings the most changed code under unit tests. It also retires the tests that read source files as text (71 files, 34 of which run nothing), which break on a rename and cannot catch wrong behavior.

## Suggested order

1. Decide idea 5.
2. Idea 7, at once: about an afternoon.
3. Idea 1 for the notes list and the search contexts, one kind of change at a time; idea 6 comes with it.
4. Idea 2 as soon as the first changes are in the queue.
5. Idea 8 alongside, file by file, whenever one of the event files is being changed anyway.
6. Ideas 3 and 4 only if full multi-view stays.

## Open questions for the maintainer

- Idea 5: is simultaneous editing in two views worth keeping?
- Idea 1: should the queue live in the browser only, or should the server order the messages too (which idea 4 would make natural)?
- How much old-and-new side by side is acceptable during the move, and for how long?
- Should the pace of new features slow while idea 1 is under way, or run beside it?

## Related

- The review these came from is in the session of 2026-11-15 (not kept as a file).
- `docs/design/multi-view-editing.md`: what multi-view does today.
- `docs/ui/command-gate.md`: one command at a time, as built.
- `docs/ui/interaction-principles.md`: the rules any of this must keep.
- `docs/future-plans/model-checking-protocols.md`: checking protocols by exhaustive search, close in spirit to idea 2.
