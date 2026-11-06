# Hosted account states

**Status:** Future plan. Written 2026-11-06 at the maintainer's request: read-only mode is app work, so the states are written down here, while the control plane that decides them gets its own private repository (`free-accounts.md` §8). Periods marked *proposed* are for the maintainer to set.

Vocabulary as in `docs/AI-SUMMARY.md`: users see **vault**; code, APIs and backup archives say **namespace**. Names match `hosted-own-copy.md` ("trial, active, lapsed, cancelled during the grace period").

---

## 1. Why

Three notes lean on these states and none defines them:

- `hosted-own-copy.md`: the one-time "Download your own copy" prompt (trial ends, cancel, lapse, account deletion) and the download never being gated.
- `free-accounts.md`: a revoked or ended grant behaves "as a lapsed subscription".
- `docs/ready-to-build/folder-import-and-file-previews.md`: the import's total bar measures against the hosted plan's storage.

## 2. The states

| State | Starts when | In the app | Ends |
|---|---|---|---|
| **Trial** | Sign-up | Everything, within the plan's storage | Subscribing → Active. Trial end → Lapsed |
| **Active** | A subscription, or an operator's grant (`free-accounts.md`) | Everything | Cancelling → Cancelled. A payment that fails after the provider's retries, or a revoked or ended grant → Lapsed |
| **Cancelled** | The user cancels | Everything, until the paid period ends | Resubscribing → Active. Period end → Lapsed |
| **Lapsed** | See the rows above | **Read-only:** read, search, export, download your own copy, lock and unlock, change the password. No edits, uploads, imports or restores | Subscribing → Active, everything intact. After 30 days (*proposed*) → Closed |
| **Closed** | Lapsed ran out | The vault doesn't open. The user can sign in to subscribe (→ Active, everything intact) or download their own copy | After 90 days (*proposed*) → Deleted |
| **Deleted** | Closed ran out, or the user deletes the account | Nothing; the account is gone | — |

- **Account deletion** by the user shows the own-copy prompt first (`hosted-own-copy.md` §4), then deletes. Retained snapshots go as the privacy policy says (`docs/ready-to-build/file-storage-per-file.md` §10.2).
- **Emails** (*proposed*): 14 days before a trial ends, a grant ends (`free-accounts.md` §4), and Closed ends; one when an account becomes Lapsed.

## 3. What this repository does

- **The state comes from the deployment,** in the `hosted` profile (`docs/ready-to-build/deployment-profiles.md`): the control plane sets it and the app reads it. Never a user setting, as hosted mode itself (`hosted-own-copy.md`, invariant 6).
- **The server enforces read-only.** In Lapsed every write route refuses with a polite rejection (as `InputRejected`); hiding controls is not enough, as with hosted backup folders (`hosted-own-copy.md`, "Problems", 3).
- **The screen:** editing controls dim and inapplicable menu items are hidden; one floating card says the vault is read-only, with Subscribe and Download Your Own Copy. Minimal text.
- **State changes never touch data.** The vault stays encrypted and unchanged through Trial, Active, Cancelled, Lapsed and Closed.

## 4. Invariants

1. Only the end of Closed, or the user deleting the account, deletes data. No other state change alters a vault.
2. Export and the own-copy download work in every state while the account exists.
3. Read-only is enforced by the server, not by the screen.
4. Paid and granted accounts pass through the same states; only how they enter Active differs.
5. The control plane sets the state; the app never decides it.

## 5. Open

- The periods: Lapsed (30 days *proposed*), Closed (90 days *proposed*), the warning emails (14 days *proposed*).
- Does a trial ask for a card?
- How many failed payment retries before Lapsed (the payment provider's settings).
- Whether AI features work while Lapsed (they may cost the service money).

## 6. Done when

1. A test per state checks what the app allows and refuses, at the server.
2. Export and the own-copy download, then a restore of that copy, work in every state (as `hosted-own-copy.md` §5 already requires).
3. Subscribing from Lapsed or Closed returns the vault exactly as it was.
4. `docs/security/README.md` lists the account state as account data held by the control plane.
