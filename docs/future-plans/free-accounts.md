# Free accounts by operator grant

**Status:** Agreed with the maintainer 2026-11-04. **Future plan: build with the hosted control plane's entitlement record,** which doesn't exist yet. Sent now so the entitlement design allows for it. Details marked *proposed* are suggestions.

Written without the control plane to look at.

---

## 1. What

Hosted plans at no charge for people the operator chooses (friends, family, first testers, reviewers), permanently or until a date.

## 2. A grant, not a discount

- A free account is an entitlement the operator grants by hand, marked as a grant (source `grant`, beside the payment provider's source). The payment provider is never involved: no checkout, no card, no billing email.
- Not a 100%-off discount through checkout: that would ask for a card and tie the account to billing.

## 3. A grant holds

- **Plan** (any hosted plan), chosen per grant.
- **End date:** none, or a date.
- **Reason:** a short note only the operator sees.
- **Email:** the person's sign-up email.

## 4. Behavior

- **Granted before sign-up:** signing up with that email lands on the plan, with no checkout.
- **Already paying:** the grant replaces the subscription; it is cancelled at the provider and not charged again (verify cancellation and proration).
- **Revoked:** the account goes to the unpaid state, exactly as a lapsed subscription (read-only, then retention; export always available).
- **Ending:** an email before the end date (14 days, *proposed*) offering to subscribe; at the end, as a lapsed subscription.

## 5. Who can grant

- Only the operator, from the operator's control-plane tool. Never from inside the app; no user can grant or invite.
- Every grant, change and revocation is logged.
- The grant's fields are account data in the control plane, like the entitlement. No note contents or keys are involved. Document them in the security docs' account-data list.

## 6. Invariants

1. A granted account never touches the payment provider.
2. Only the operator grants.
3. Granted accounts follow the same terms and limits as paid ones on the same plan; only billing differs.
4. Revoking or ending a grant never loses data; export always works.

## 7. Done when

1. The operator grants a plan to an email; that person signs up and lands on it without checkout.
2. A grant with an end date warns, then lapses like a subscription.
3. Granting to a paying user stops their billing.
4. Revoking drops to the unpaid state with export working.
5. Every grant action is in the log.

## 8. Checked 2026-11-06 (filed from the inbox)

- Filed as a future plan, as its status asks. Nothing built: this repo has no control plane, entitlement record, payment provider or operator tool yet. Hosted subscription states (trial, cancel, lapse) appear only in `docs/future-plans/hosted-own-copy.md`, which now points here.
- `docs/security/README.md` has no account-data list yet (§5); one is needed when the control plane is designed.
- **Decided with the maintainer 2026-11-06:**
  1. **The control plane gets its own private repository.** MetaList is public on PyPI; billing code, payment-provider secrets and operator tools must not ship to self-hosters, and the hosted side deploys on its own schedule. This note moves there when that repository exists. This repository keeps only what the app reads: the account's plan and state.
  2. **The unpaid state is written down** in `docs/future-plans/hosted-account-states.md` ("Lapsed"); revoking or ending a grant enters it exactly as a lapsed subscription does.
