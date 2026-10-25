# Addendum to the HTML note-sharing idea: ontology fragments, recipes, and no code plugins

**Status:** Principles agreed with the maintainer 2026-10-25. **Not scheduled.** This is an addendum to `docs/future-plans/html-note-sharing.md` (2026-10-19): **merge it into that document** (it stays a future plan), rather than filing it separately.

Written without running the code. Check references before relying on them.

---

## 1. Ontology fragments in the exchange file

- **The exchange file can also carry the part of the sender's ontology related to the exported notes' tags:** implication rules, synonyms, and super-tag definitions. Example: exporting a note about transformers can include `transformer` implies `neural-network` implies `AI`.
- **Export: explicit opt-in.** Including ontology is a choice the sender sees and approves, listing exactly which tags, rules and synonyms go into the file. Never included silently.
- **Visible on the page too.** Consistent with this document's first principle (the hidden data never contains more than the page shows): included ontology also appears in the readable HTML, for example a closing section "Tags and rules included." Tag names and rules can reveal a lot about a person.
- **Import: offered, never applied.** The recipient sees each rule, synonym and definition on offer. **Anything that overlaps or conflicts** with their existing ontology is flagged, and they choose per item (add, skip, or merge). Accepting is one step reversed by one undo. Nothing changes the recipient's ontology silently.

## 2. Recipes: the same format without notes

- **A recipe is an exchange file with only ontology and setup, no notes:** tag structures with synonyms and rules, super-tag definitions, templates, possibly AI help prompts or a theme (for example "a reading-tracker setup," "a starter ontology for machine learning").
- One format for notes and recipes. People share files; no marketplace is needed.
- Recipes are data built from MetaList's own concepts, so importing one can do only what tags and rules already do: it can't send notes anywhere or run anything. Same explicit-consent import as §1.

## 3. Plugins: none that run code in the hosted service

- **Browser-side code plugins** would run in the page that shows decrypted notes; `docs/security/` already lists a privileged browser extension reading MetaList pages as a threat. Not planned.
- **Server-side code plugins** would run in the process holding the vault's key. **Never in the hosted service.** Possibly a self-hosted option at the operator's own risk, if ever requested.
- The community's way to extend MetaList is **recipes** (§2), plus contributions to this open-source repository.

## 4. Invariants to add

1. Ontology leaves a vault only with the sender's explicit, itemized approval, and is visible on the exported page.
2. Ontology enters a vault only with the recipient's explicit approval; overlaps and conflicts are shown and resolved by the recipient; one undo reverses the import.
3. Exchange files and recipes are data, never code.
4. The hosted service never runs third-party code.

## 5. Related idea, not part of this addendum

Typing `[[` could open a small search suggesting notes by their first line; choosing one inserts `[[UUID]]`, instead of copying a reference (⌘R) and pasting. To be designed separately.
