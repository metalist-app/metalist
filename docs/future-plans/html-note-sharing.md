# Sharing Notes as HTML (future feature idea)

Status: idea only, not planned. Brainstormed 2026-10-19. Nothing here is built.

## The idea

MetaList already exports a note subtree or the current view as HTML. A hidden, machine-readable copy of the exported notes could go inside that file. It would hold content, structure, tags, collapsed state and attachments. Anyone can open the file and read it in a browser, and another MetaList can import it and rebuild the notes exactly.

The file is then both a readable page and a lossless note package. draw.io and Excalidraw do the same thing: they put the full diagram data inside an exported PNG or SVG. Recipients on older MetaList versions, or with no MetaList at all, still get a normal readable page.

## What exists today

- **HTML export** (`app/services/html_export.py`, `build_notes_export_document`) already decides what goes out: view membership, notes the search excludes, embeds, collapsed state, the export title, and Hide/Include passwords.
- **Note clipboard**: Copy Note stores the subtree in server memory and marks its HTML with `data-metalist-note-clipboard="true"`. Paste rebuilds it with `paste_snapshot_as_sibling` / `_as_child`. That stored subtree is close to the format a gift file needs. Today it lives only in server memory and expires on restart.
- **Notes have `created_at` and `updated_at`** (`app/db/notes_sql.py`).

## Scope: one-way gifting, designed for round-trip later

The first version is **one-way**: a sender gives notes and the recipient imports them. Round-trip editing, where both sides send changes back and forth, would really be a sync feature and is out of scope.

Once files are sent they can't be migrated, while a database can. So the **file format** should carry, from day one, the cheap facts a future round-trip would need:

- each note's original UUID
- an ID for the export itself, plus the time it was made
- an install ID for the sending MetaList (random, not a name)
- each note's `updated_at`
- a content fingerprint for each note

One-way import may ignore most of these. Storing provenance in the recipient's database is deferred. That would be a schema change and needs a version bump, migration and encryption-audit update, as AGENTS.md requires.

## Principles

1. **The hidden data never contains more than the page shows.** "Hidden" only means a browser doesn't display it; anyone can view the page source. Notes hidden by Hide passwords and notes the search excluded are absent from the data too. Never add "a bit extra so the import is complete".
2. **Import reads only the hidden data, never the visible HTML.** The visible page and the data can disagree, for example after a hand edit or in a crafted file. The import preview shows what will actually be imported.
3. **The imported file is untrusted input.** Validate strictly, and refuse bad files with `InputRejected` and a message that says what's wrong. Content goes through the same cleaning as pasted external HTML. Apply size and nesting limits (256 levels).
4. **The sharing format has its own version number,** separate from the database version. An older MetaList says "this file was made by a newer MetaList" and refuses it; it doesn't guess.
5. **No silent duplicates and no silent overwrites.** Clashes are shown to the user, and the user decides.
6. **One gift is one step.** Import is all-or-nothing, and Undo reverses it in one step. A half-applied gift is the worst possible outcome.

## Note identity and clashes

**Keep original UUIDs by default.** Random clashes between unrelated notes are effectively impossible. Keeping the originals means:

- links between gifts work: a second gift that links to a note from the first resolves on the recipient's side
- links inside the file need no rewriting
- a future round-trip is natural, because both sides agree on which note is which

The clashes that do happen aren't random. They come from **the same note arriving twice**:

- the same gift imported twice, or an updated version of it
- importing your own export, for example on a second machine
- a recipient sending back notes they were originally given

So there must be a clash rule:

| Case | Behavior |
|---|---|
| No clash | Import with original UUIDs. |
| Clash, content identical | Nothing to decide. Skip them and report it: "4 already here, unchanged". |
| Clash, content differs | The user chooses: **keep mine**, **add theirs as copies** (all new UUIDs), or **skip**. |
| Overwrite | **Not offered.** It throws away the recipient's edits silently. A crafted file could also target existing notes: anyone who ever received a gift knows those UUIDs. |

Decide for the whole gift rather than note by note where possible. If some notes keep their old UUIDs and others get new ones, links inside the gift get messy. Changed clashes should show both versions side by side, or at least the first lines of each, so the user isn't guessing blind.

### What timestamps can and can't tell

`updated_at` says **which copy is newer**. It can't say **whether both sides changed**. Example: a note is gifted on the 1st, the sender edits it on the 5th, the recipient edits it on the 8th, and an updated gift goes out on the 10th. "Newest wins" keeps the recipient's version and silently loses the sender's edit.

Telling the cases apart needs the version the two copies last shared:

- recipient's copy unchanged since the last gift, sender's changed: safe to update
- recipient's changed, sender's unchanged: keep the recipient's
- both changed: a real conflict, so ask

One way: **on import, keep the sender's `updated_at` rather than stamping the import time.** If the recipient's copy still has exactly that timestamp, they haven't touched it. Linking it to a particular earlier gift also needs the gift ID or the per-note content fingerprint.

Caveats to check before relying on `updated_at`:

- **What bumps it.** `update_links` requires a new `updated_at`, so moving or reordering a note probably counts as an update, and maybe for its neighbors too, since their sibling links change. Collapse toggles appear to use `update_links_preserving_updated_at`. If moves bump the timestamp, "newer" can just mean "moved".
- **Clocks differ between machines.** That's fine for an exact "unchanged since import" match, but unreliable for "which is newer" across machines.

For one-way gifting, use timestamps as **information in the clash dialog**, for example "Yours: edited 8 Oct · Incoming: edited 10 Oct". Don't let them decide automatically.

## What the gift contains

| Included | Notes |
|---|---|
| Content | Same cleaning as external paste on import. |
| Structure | Parent and order, for the notes the export shows. |
| Tags | Merge into the recipient's tags with the same name, matched case-insensitively like paste. |
| Collapsed state | As exported. |
| Attachments | The actual file data (images, the Excalidraw scene source, not just its preview). This can make files large. |
| Provenance | Original UUIDs, export ID, install ID, `updated_at`, content fingerprint (see above). |

| Excluded / undecided | Notes |
|---|---|
| Suggested tags | These are the sender's AI's guesses about the sender's notes. The recipient's MetaList should make its own, or the imported ones arrive only as proposals. |
| Passwords and usernames hidden at export | They're absent from the data too, not just the page. |
| Behavior-changing tags (`@size`, `@password`, `@copyable`, ...) | Decide case by case whether each one is carried over. |
| A "from: sender" tag | Optional. Could help a recipient who finds things by topic. |

## References and embeds

- `[[UUID]]` links between notes inside the gift work as they are, with original UUIDs. When the user picks "add as copies", they have to be rewritten to the new UUIDs.
- Links to notes outside the gift dangle unless the recipient already has those notes, for example from an earlier gift.
- The export currently shows an embedded note's content inline. Decide whether the recipient gets the embedded note as a real note or only its displayed text.

## Import experience

- How it gets in: drag the `.html` file onto MetaList, an Import command, or both. A drop zone fits how attachments already work.
- Preview before anything changes, for example "12 notes, 3 images, tags: travel, japan", plus the clash summary.
- The preview is a dialog, so like every dialog it saves and leaves edit mode first.
- Where the notes land follows `docs/ui/interaction-principles.md`, as paste does: at the user's point of attention, visible, and not highlighted.

## Side benefit: one format for clipboard and gifts

If Copy Note and gift files use the same format, notes could be copied and pasted between MetaLists on different machines, and copied notes would survive a server restart. Today the clipboard lives in server memory and is lost on restart.

## Risks and open questions

- **Deleted notes and lingering UUIDs.** Do deleted notes keep their UUIDs anywhere, such as undo history or a restored backup? If so, "delete the gift, then re-import it" could clash with a note that's gone from view but still known underneath. Settle that rule.
- **Email filtering.** Some email systems and company filters strip or flag `.html` attachments, because they're common in phishing. Sharing through a link or cloud drive avoids this.
- **Encryption.** An export from an encrypted database is unencrypted, which is already true of HTML export. The hidden data just makes it easier to read by machine. Consider warning when exporting from an encrypted namespace.
- **File size** with many or large attachments: is there a limit, or a warning?
- **Where the data sits in the file**, for example `<script type="application/json" id="metalist-notes">`. Browsers don't run it, and it survives "Save page as".
- **Round-trip later**: a stored base version per imported note, conflict handling, deletions, and trust between senders. Out of scope until one-way exists and gets used.

## Addendum (2026-10-25): ontology fragments, recipes, and no code plugins

Principles agreed with the maintainer 2026-10-25; still not scheduled, like the rest of this document.

### A1. Ontology fragments in the exchange file

- **The exchange file can also carry the part of the sender's ontology related to the exported notes' tags:** implication rules, synonyms, and super-tag definitions. Example: exporting a note about transformers can include `transformer` implies `neural-network` implies `AI`.
- **Export: explicit opt-in.** Including ontology is a choice the sender sees and approves, listing exactly which tags, rules and synonyms go into the file. Never included silently.
- **Visible on the page too.** Consistent with this document's first principle (the hidden data never contains more than the page shows): included ontology also appears in the readable HTML, for example a closing section "Tags and rules included." Tag names and rules can reveal a lot about a person.
- **Import: offered, never applied.** The recipient sees each rule, synonym and definition on offer. **Anything that overlaps or conflicts** with their existing ontology is flagged, and they choose per item (add, skip, or merge). Accepting is one step reversed by one undo. Nothing changes the recipient's ontology silently.

### A2. Recipes: the same format without notes

- **A recipe is an exchange file with only ontology and setup, no notes:** tag structures with synonyms and rules, super-tag definitions, templates, possibly AI help prompts or a theme (for example "a reading-tracker setup," "a starter ontology for machine learning").
- One format for notes and recipes. People share files; no marketplace is needed.
- Recipes are data built from MetaList's own concepts, so importing one can do only what tags and rules already do: it can't send notes anywhere or run anything. Same explicit-consent import as §1.

### A3. Plugins: none that run code in the hosted service

- **Browser-side code plugins** would run in the page that shows decrypted notes; `docs/security/` already lists a privileged browser extension reading MetaList pages as a threat. Not planned.
- **Server-side code plugins** would run in the process holding the vault's key. **Never in the hosted service.** Possibly a self-hosted option at the operator's own risk, if ever requested.
- The community's way to extend MetaList is **recipes** (§2), plus contributions to this open-source repository.

### A4. Invariants to add

1. Ontology leaves a vault only with the sender's explicit, itemized approval, and is visible on the exported page.
2. Ontology enters a vault only with the recipient's explicit approval; overlaps and conflicts are shown and resolved by the recipient; one undo reverses the import.
3. Exchange files and recipes are data, never code.
4. The hosted service never runs third-party code.

### A5. Related idea, not part of this addendum

Typing `[[` could open a small search suggesting notes by their first line; choosing one inserts `[[UUID]]`, instead of copying a reference (⌘R) and pasting. To be designed separately.

## Addendum B (2026-10-27): knowledge packs, collisions, provenance, updates and sharing by QR

Direction only, not scheduled; principles agreed with the maintainer 2026-10-25. Filed from the inbox on 2026-10-27: no code exists for any of it (no exchange file, `@source` or QR drop box yet).

## B1. Knowledge packs

- **A pack is an exchange file of notes plus their tags and ontology,** shared as a body of knowledge: for example detailed notes from a whole course. The notes arrive **already organized and searchable** (`bayes`, `hypothesis-testing`), connect to the recipient's own notes through shared tags, and part of the ontology can change how they look (with user styles, a separate future plan).
- **What makes it distinctive:** other apps share notes; a MetaList pack shares **notes plus their meaning** (tags, how tags relate, how they look).
- **Licensing is the sender's responsibility:** one's own notes are theirs to share; where they summarize course material, that course's license applies (some allow non-commercial sharing with credit).

## B2. Tag collisions between people

Three strategies, **combined**, every step explicit:
1. **Namespace on arrival (the safe default).** Imported tags arrive prefixed with the source (for example `alex.bayes`), so nothing collides, nothing of the recipient's changes, and origin is visible. Prefix or suffix form: open.
2. **Merge afterward with synonyms, not renaming.** Declaring `alex.bayes` a synonym of the recipient's `bayesian` connects them without destroying either; reversible; provenance kept. The recipient may also choose which side's tag wins.
3. **AI-assisted merging, approved by the user.** The AI reads the recipient's ontology and the incoming fragment, **proposes** mappings and **asks** where unsure ("they put `regression` under `statistics`, you have it under `ML`; which?"). Nothing applies until approved. This sends tag names and rules to the AI provider only when the user asks, and **the existing AI tag allow and block lists apply.**

## B3. Packs in Git, improved by pull requests

- Packs are files, so they can live in a Git repository: versioned, published, and **improved like open-source code** (someone adds notes, sends a pull request; the maintainer reviews and releases a new version).
- **It's all data:** a pack holds only notes, tags and rules, so it can't break MetaList's logic.
- HTML with hidden data makes noisy diffs; a pack meant for a repository may also want a **plain data form** of the same content.

## B4. Provenance: the `@source` super tag

- **Every imported note gets `@source`,** a built-in super tag carrying the pack's **name and version**, its **author**, its **repository address**, and possibly its **license**. Same family as `@LLM` (and the web clipper's `@web`): content that came from outside the user.
- **What it gives, with nothing new built:** search `@source` (narrow by attribute to one pack); rules such as "`@source` implies a lighter background"; knowing which notes belong to which pack for updates (B5); and contributing back.
- **Open:** how a note the recipient adds becomes part of a pack for a pull request. First guess: **giving it the pack's `@source` tag is what opts it in,** with no separate "add to pack" feature.

## B5. Updating an imported pack

- Version 2 should arrive as **what changed,** not a second copy. Match by each note's original UUID, timestamps and content fingerprint (already planned in the exchange format), with `@source` naming the pack.
- **New notes:** offered. **Changed notes:** shown as changes. **Notes the recipient edited that the pack also changed:** side by side; they decide. Nothing overwritten silently; one undo reverses an update.

## B6. Sharing a pack in person by QR code

**The moment:** two phones; one shows a QR code, the other scans, and the pack is offered on the second phone. No email address, no account linking: good for someone just met.

1. The sender's device **encrypts the pack** with a new one-time key and uploads **only the ciphertext** to a temporary drop box on the server.
2. It shows a **QR code** holding where to fetch it and the one-time key (a QR code holds about 3 KB, so it carries the way to fetch the pack, not the pack).
3. The recipient's device fetches the ciphertext and **decrypts it locally.**
4. The drop box **deletes it on first download,** or after a few minutes.

- **The key never touches the server;** the server holds a sealed envelope, briefly, once. The sender vets the recipient by choosing to show them the code. **The same import review applies** on the recipient's side.
- **One mechanism used twice:** the same protocol is planned for moving a vault key to a new phone (QR device linking, a later phone item). Same code, different payload.
- **Channels, all with the same file and the same review:** QR in person; files (AirDrop, Messages, email); Git for packs that evolve.
- **Open:** the drop box's expiry and size limit; whether self-hosted instances run their own drop box; what the scanner sees if the pack expired or was already fetched.

## B7. Invariants to add

1. Imported notes carry `@source` provenance; imported tags arrive namespaced; any merge into the recipient's ontology (by hand or AI-assisted) happens only with their approval.
2. A pack update never overwrites anything silently; conflicts with the recipient's edits are shown for them to decide.
3. QR sharing: the one-time key travels only in the QR code; the drop box holds only ciphertext, deletes it on first download or expiry, and the import review still applies.
