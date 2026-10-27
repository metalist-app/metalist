# Workflow: try UI changes yourself, then get the maintainer's early look

**Status:** Agreed with the maintainer 2026-10-27. A change to this repo's working rules, not a feature: fold it into `AGENTS.md` (the FEATURE and BUG flows and "Testing and Commits") and anything it points to.

Written without checking every part of the current workflow. Check `AGENTS.md` and `docs/testing/harness.md` before relying on the references here; keep what already does the job.

---

## 1. Why

- **Today:** code is written, then the tests (unit, server, browser), then the suites run, and only then is the maintainer asked to try it. The maintainer is the first one who actually *looks* at the change, so obvious breakage (a blank panel, a broken layout, a button that does nothing) turns up last, after a full round of tests and suites.
- **Two changes:**
  1. **You look first.** For a change to what the user sees, drive a throwaway MetaList yourself while building it. That catches obvious breakage in minutes.
  2. **The maintainer looks early.** Hand the change over as soon as it works in your own check, **before** writing the full test set or running the suites. The maintainer decides what's right, and wants to be in the loop early, not handed something polished in a wrong direction.
- The maintainer stays the gate on what is correct. Your own check filters out the obvious; it never replaces their look.

## 2. The loop, for changes that affect what the user sees

1. **Acceptance checks first.** Before the code, write short, concrete statements of what the user should see, taken from the note or the request: "the header 'State' stays on one line", "`<br>` gives two lines in a cell", "the menu follows the dark theme". Put them in `PLAN.md` or the reply.
2. **Write the code.**
3. **Check it yourself** in a throwaway MetaList (§4), in a real browser. Go through each acceptance check and take a screenshot of each. Try the edges too: a narrow window, dark theme, a collapsed note, long content, phone width.
4. **Early look.** Hand it to the maintainer now, with:
   - each acceptance check, pass or fail, with its screenshot
   - what you fixed along the way
   - **what you couldn't judge**: timing, scrolling feel, focus and keyboard flow, a real phone. Say so; don't claim it.

   Before the early look: **no full test set, no full suites, no checkpoint.** Only the quick checks that the app starts and the page loads.
5. **Iterate.** Each problem you or the maintainer find becomes **a failing test first, then the fix**, as in the BUG flow.
6. **Once the maintainer confirms the direction:** write the remaining tests, checkpoint as the rules already say (quick suites only), and run the full suites only where they're already required (COMMIT FEATURE, before a push).

Changes that don't affect what the user sees (server-only, storage, sync) don't need the self-check. Their flow stays as it is.

## 3. Rules to adjust

- **"If Testing Fails"** currently suggests `git reset --hard HEAD`. With early looks, a problem found at the early look is expected and normal: **iterate, don't reset.** Offer a reset only when the maintainer says the whole approach is wrong.
- **Don't polish before the first look.** Getting to the early look quickly matters more than arriving complete.
- **Write the acceptance checks before looking.** Tests written from what you saw lock in what the code does, not what it should do. A short column breaking "State" into "Stat" / "e" looks like "a table, fine" if nothing says it shouldn't.

## 4. A throwaway MetaList

- **Never the maintainer's own vault.** A temporary data folder, a free port, torn down afterwards.
- **Seeded with fixture notes** that exercise rendering: Markdown tables, `@csv`, Mermaid, LaTeX, code blocks, a deep tree, references and embeds, long notes, collapsed notes. Made-up content only.
- **One command to start it.** Check first whether the browser harness already starts an isolated instance and seeds notes (it seems to); reuse that rather than building a second one.

## 5. Done when

- `AGENTS.md` describes this loop for changes the user sees, including the early look and what comes before and after it.
- The reset rule is adjusted as in §3.
- One command starts a seeded, throwaway MetaList for the self-check.

## 6. Checked 2026-10-27 (filed from the inbox)

- **Done on filing:** `AGENTS.md` has "Early Look: Changes the User Sees" (the loop of §2, with §3's rules) and "If Testing Fails" now says iterate, offering a reset only when the whole approach is wrong (§3).
- **Left to build: §4, one command for a seeded throwaway MetaList.** The browser harness starts an isolated instance (its own temporary data folder and free HTTP and HTTPS ports, never 8443) and seeds notes for each suite (`scripts/browser-smoke.mjs`), but only for the length of a run; nothing starts one and leaves it running for a look. Reuse that start-up code (it is what `.venv/bin/python serve_namespace.py --namespace default --port <port>` with `METALIST_DATA_DIRECTORY`, `METALIST_PORT` and `METALIST_HTTPS_PORT` does, run by hand so far), add the fixture notes of §4, and print its address.
