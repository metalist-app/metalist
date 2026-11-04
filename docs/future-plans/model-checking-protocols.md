# Model-checking the protocols with TLA+ (future plan: don't build yet)

**Status:** Direction agreed with the maintainer 2026-10-31. Not ready to build: tools, order and timing are open. Depends on the commit and shutdown protocol (`docs/ready-to-build/commit-and-shutdown-protocol.md`).

Written from a read-only look at the repo; filed 2026-10-31 (see Found when filed).

---

## 1. The idea

TLA+ describes a protocol step by step (who can do what, in which order, at the same time as whom), and its model checker (TLC) tries **every interleaving** of a small setup, such as two views, a phone, one server that can be killed, and three notes. It reports any sequence of events that breaks a stated rule. Small models find most concurrency bugs.

**It checks the design, not the code.** A model is a few pages written separately. Syntax options: TLA+, PlusCal (pseudocode that compiles to TLA+) or Quint (programmer-style syntax).

Use it only where a bug loses data or corrupts structure. Not for rendering, search, tags, the UI or import/export. Machine-checked proofs (Lean 4 and the like) are overkill here.

## 2. Candidates and the rules each model checks

1. **Commit and shutdown protocol, first, before the hosted launch:** an acknowledged change survives a kill at any step; a change ID applies at most once however often it's resent; "Saved" only for acknowledged content; a view without the lock can't write; two server processes never write one database. Model: two views, one server that can be killed and restarted, a network that drops, delays and duplicates requests.
2. **Backups:** a snapshot's catalog and notes are a consistent pair while edits continue; pruning and `Trim Unused Files…` never delete a file a kept snapshot, undo or paste still needs; a half-written backup (`.partial`, a crash mid-upload) never looks complete; every kept backup restores without depending on a graceful stop. Not covered: encryption correctness, whether cloud storage keeps the bytes, the human restore rehearsal, which stays the real proof.
3. **Multi-view root-note locks:** one editor per root at a time; takeover and disconnect never leave two editors or a lock nobody holds; a locked root can be moved, not deleted.
4. **Linked-list order:** under concurrent moves, indents and deletes, every note is reachable exactly once from its parent, with no cycles and consistent `prev`/`next`. (This checks the linked list; it doesn't reopen it.)

## 3. The partner: stateful tests on the real code

The model can't say the Python follows it. **Hypothesis stateful testing** closes that gap: random sequences of operations (type, save, move, kill, resend, back up, prune, restore) against the real server, shrunk to the shortest failing sequence. **The same rules** serve both; the crash tests in the commit protocol check the real disk.

## 4. Practice

- An AI agent drafts each model; the checker runs on small settings, ideally in CI.
- A protocol change updates its model in the same change, or the model rots.
- Cost: a learning curve, possible drift, some CI time. Worth it only for the protocols above.

## 5. Open

- TLA+/PlusCal or Quint.
- Whether Hypothesis stateful tests come before, with, or after the first model.
- CI on every change, or only when a protocol changes.
- The order after the commit protocol.
- Where models live in the repo.

## 6. Found when filed (2026-10-31)

- **Hypothesis is already a dependency** (`hypothesis==6.164.0` in `pyproject.toml`), but no test imports it yet. Stateful tests (§3) need no new dependency.
- No TLA+, PlusCal or Quint anywhere in the repo.
