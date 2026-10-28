# Vault passwords: zxcvbn score 4, and five-word passphrase suggestions

**Status:** Agreed with the maintainer 2026-10-27. Small; ready to build. §1 and §2 are agreed. Wording and layout are proposed, so adjust any that read badly.

Written from a read-only look at the code, without running it. Check every reference before relying on it; build only what's missing.

---

## 0. Background

- **Today's rule** (`app/config.py`: `PASSWORD_MIN_LENGTH = 12`, `PASSWORD_MAX_LENGTH = 72`, `PASSWORD_MIN_ZXCVBN_SCORE = 3`; `docs/security/README.md`, "Password Requirements"): new and changed passwords need 12–72 characters and zxcvbn score ≥ 3. There are no character-class rules, and existing passwords are grandfathered at login.
- **Why raise it:**
  - The vault password is the only protection on encrypted backups and snapshots, and anyone holding those files can guess offline with no login limit.
  - Backups now leave the machine in every deployment: synced folders and S3 for personal and self-hosted, the hosted snapshot store.
  - zxcvbn's own guide rates score 3 as moderate protection against offline slow-hash guessing, and score 4 as strong.
  - Argon2id (64 MiB, 3 passes) slows each guess, but rented GPUs could still plausibly get through a score-3 password in hours to days.
- **`Generate Random Password…`** already exists: a character generator using browser `crypto.getRandomValues()` with rejection sampling, `Copy` and `Regenerate` (`app/static/js/modules/password-generator.js`; `docs/ui/command-palette.md`).

## 1. The rule (agreed)

- **New and changed vault passwords need zxcvbn score 4,** in every deployment (personal, self-hosted, hosted). Set `PASSWORD_MIN_ZXCVBN_SCORE = 4`, and check the browser meter (`password-strength.js`, `password-policy.js`) and its wording.
- **12–72 characters stays.**
- **Existing passwords always still unlock,** as today (login verifies against the stored Argon2id profile without the creation policy). **No prompt or nudge to change them.**
- **Out of scope:** the hosted account sign-in password, which is separate from the vault password and isn't built yet. It keeps its own rule.
- **Update `docs/security/README.md`** "Password Requirements".

## 2. Five-word passphrase suggestions (agreed)

- **Wherever a vault password is set:**
  - Add Password and Change Password
  - first-run setup's password step
  - later, the hosted sign-up's vault step
- **What it does (proposed):**
  - A **Suggest a passphrase** button fills the new-password field, and its confirmation, with five random words: `velvet-orbit-canyon-pickle-thaw`.
  - The field shows them in plain text while they're a suggestion.
  - `Regenerate` and `Copy` sit beside it.
  - One line underneath: `Save this in a password manager or write it down. It can't be recovered without your recovery key.` Adjust to what recovery actually offers.
- **The words:**
  - A published list of 7,776 short, common, distinct words: the EFF long wordlist is the usual choice. Check its license and add the credit to the app's third-party notices.
  - Bundle the list with the app; nothing is fetched at runtime.
  - Pick each word with `crypto.getRandomValues()` and rejection sampling, as the character generator does: no modulo bias.
  - Five words from 7,776 is about 64.6 bits.
  - Join with hyphens and keep it lowercase. The longest is about 50 characters, well inside 72.
- **Always passes:** score each suggestion with the same zxcvbn the form uses before showing it, and regenerate if it scores below 4 (rare).
- **`Generate Random Password…` gets a `Words` mode** beside the character mode: same list, same picker, a word count control (default 5). The clipboard handoff that adds `@password` works the same.
- **Privacy:** the suggestion stays in the browser until the person submits the form, exactly as a typed password does.

## 3. Acceptance checks

- Setting a new vault password that scores 3 is refused, with the meter explaining why. A score-4 password is accepted, in every deployment.
- A vault whose existing password scores below 4 still unlocks, and nothing asks to change it.
- **Suggest a passphrase** in Add Password fills five hyphenated lowercase words that score 4, and Regenerate gives a different set. Saving with it works, and the vault unlocks with it after a restart.
- 10,000 suggestions in a test all score 4, contain only list words, and show no word noticeably more often than chance.
- `Generate Random Password…` in Words mode gives five words by default and respects the word count.
- No network request is made while generating suggestions.

## 4. Invariants

1. A new or changed vault password scores 4 on zxcvbn, in every deployment.
2. A suggested passphrase comes from a cryptographic random source in the browser and always passes the rule.
3. An existing password always still unlocks.

## 5. Checked 2026-10-27 (filed from the inbox)

- **Confirmed:** `PASSWORD_MIN_LENGTH = 12`, `PASSWORD_MAX_LENGTH = 72`, `PASSWORD_MIN_ZXCVBN_SCORE = 3` (`app/config.py`); "Password Requirements" in `docs/security/README.md`; `password-generator.js`, `password-strength.js`, `password-policy.js`.
- **Two places hold the score:** the server checks with Python's `zxcvbn` (`app/services/auth_service.py`, `user_inputs=["metalist"]`), the browser meter with the vendored `zxcvbn-4.4.2.js` and its own `PASSWORD_MIN_ZXCVBN_SCORE` in `password-policy.js`. Raise both together. The server is the gate, so §3's 10,000-suggestion test should score with the server's `zxcvbn` too (same `user_inputs`): a suggestion the browser rates 4 must never be refused.
- **No recovery key exists:** the data key is wrapped once, by the password (`docs/security/README.md`, Vault Key; a recovery key needs the deferred `key_wrappers` table). So §2's line should read: `Save this in a password manager or write it down. It can't be recovered.`
- **No first-run setup flow exists** to add the button to. Today the first password is set with Add Password; the button goes there, and into any setup step built later.
- **The wordlist is a vendored file:** put it under `app/static/js/vendor/` with its license (that folder is already `-text` in `.gitattributes`) and register it with `scripts/check_supply_chain.py`, like the other vendored files.
- **Open (proposed):** the button's name, the plain-text display while it's a suggestion, the warning's wording, and the Words mode's controls.
