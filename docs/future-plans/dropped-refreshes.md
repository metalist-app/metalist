# Refreshes dropped while a view request is in flight

`actionRefreshAndMaybeSelect` (`app/static/js/modules/mode-manager/actions/ui-actions.js`) drops
a refresh, with only a logged no-op, while another `notes.view` request is in flight, unless the
caller passes `requireExecution: true`. The request in flight was built from the state before the
caller's change, so a dropped refresh leaves the screen showing the old state until something
else refreshes (agreed to fix later, 2026-10-25).

- **When it happens:** only while a view request is on its way: the infinite-scroll poll moving
  the band of loaded roots (scrolling a list longer than the band, about 75 roots each side) or a
  link-title refresh. Nothing is lost on the server; only the list is stale.
- **Already fixed:** sort order, date range, Files filter and Untagged view pass
  `requireExecution` (see [state-handling.md](../ui/state-handling.md)).
- **Still dropped:** about 45 other callers, among them search, delete, move, indent/outdent,
  undo/redo, collapse, paste, Reset View Filters and phone capture. A delete or undo can stay
  visible, and a search can show the previous results under the new query.
- **The complete fix:** make running the default (wait for the request in flight, then refresh)
  and let only the infinite-scroll poll skip. The poll repeats every 0.8 s, so a skip costs
  nothing, but it must return before its "Infinite scroll blocked" check, which assumes its own
  request ran. Waiting cannot hang: the render after the fetch is synchronous, and
  `waitForViewRequestIdle` fails loudly after 5 s.
- **Tests:** a deterministic browser case per kind of caller, holding a view response in the page
  as `sortWhileViewInFlightCase` in `scripts/browser-sorted-tab-regressions.mjs` does.
