# Documentation Index

## Start Here
- Project overview: `docs/AI-SUMMARY.md`
- Repo README: `README.md`

## Design
- Differential view (diff/snapshot payload): `docs/design/differential-view-protocol.md`
- In-memory store + read guard: `docs/design/in_memory_store.md`
- Ontology (long-term reference): `docs/design/ontology.md`
- Ontology rules (implemented v1 DSL): `docs/design/ontology-rules-v1.md`

## UI
- Keyboard + mouse controls: `docs/ui/controls.md`
- Phone (under 640 px: read-only view and capture): `docs/ui/phone.md`; what is left: `docs/future-plans/phone-later.md`
- Login screen, loading progress and Session locked page: `docs/ui/login-screen.md`; the MetaList mark, its icons and usage rules: `brand/README.md`
- UUID note/file references (`![[UUID]]`, `[[UUID]]`): `docs/ui/references.md`
- External HTML paste sanitization: `docs/ui/paste-sanitization.md`
- Note content meta-tag formatting: `docs/ui/content-formatting.md`
- Search query syntax (verifier): `docs/ui/search-syntax.md`
- Search semantics (server behavior): `docs/ui/search-semantics.md`
- Tag bar grammar (tags/comments/wrappers): `docs/ui/tag-bar.md`
- Reminders: `docs/ui/reminders.md`
- AI chat: `docs/ui/ai-chat.md` (long chats: summaries of earlier turns and the history meter, its Long chats section); AI providers (OpenAI, Anthropic, Google): `docs/design/ai-providers.md`
- Modal architecture pattern, dialog and menu conventions, errors and status (error dialogs, messages under a field, the check): `docs/ui/modals.md`
- Floating messages (news, errors, the connection card) and Recent Messages: `docs/ui/floating-messages.md`
- Client state-handling philosophy: `docs/ui/state-handling.md`

## Security
- Auth + encryption design/notes: `docs/security/README.md`

- [Recovery runbook](security/recovery.md)
- [Supply-chain controls and audit](security/supply-chain.md)

## Testing
- [Mandatory refactor compatibility and automated release gates](testing/compatibility-gates.md)
- Current testing status: `docs/testing/harness.md`

- [Current implementation/test/doc map](testing/coverage-map.md)

## Diagrams
- Mermaid sources: `docs/diagrams/` (`.md` files with Mermaid blocks, or one diagram per `.mmd` file, rendered under its own name)
- Render to PNG: `npm run render-diagrams` (outputs to `docs/diagrams/png/`)

## Project Tracking
- Known bugs: `docs/BUGS.md`
- Refactor notes: `docs/REFACTORS.md`
- TODO list: `docs/TODO.md`
- Future UI plan (toolbar): `docs/future-plans/PLAN.toolbar.md`
- Future plan (hosted MetaList: downloading your own copy, the backup reminder): `docs/future-plans/hosted-own-copy.md`
- Future plan (AI providers, what is left: evals for Claude and Gemini, the demo vault, hosted questions): `docs/future-plans/ai-providers-remaining.md`
- Future plan (sharing notes as HTML, with ontology fragments, recipes and no code plugins; knowledge packs, provenance, updates and sharing by QR): `docs/future-plans/html-note-sharing.md`
- Future plan (Obsidian import and export, aliases and image widths mapped both ways): `docs/future-plans/obsidian-import-export.md`; scheduled for launch in `docs/ready-to-build/import-export-launch.md`, with every Obsidian feature mapped into MetaList in `docs/ready-to-build/obsidian-mapping.md`
- Planned, not scheduled (the same tag more than once in a note): `docs/future-plans/same-tag-twice.md`
- Future plan (charts of super-tag values, embedded like diagrams): `docs/future-plans/charts.md`
- Future plan (one encrypted file per attachment, with a catalog): `docs/future-plans/file-storage-per-file.md`
- Future plan (backups to S3-compatible storage, uploaded by MetaList itself; manual or automatic): `docs/future-plans/backups-s3.md`
- Future plan (user-named styles, `@style=name`, a safe subset of CSS): `docs/future-plans/user-styles.md`
- Being worked out, don't build yet (a bookmarklet that copies a page's title, address and selection for pasting into MetaList): `docs/future-plans/web-clipper.md`
- Tried and rejected (dragging a note to any level by the note released on; needs a different control system): `docs/future-plans/drag-across-levels.md`
- Future plan (a hover card on the Referenced by badge listing the referring notes): `docs/future-plans/referenced-by-hover-card.md`
- Future plan (an embedded email drawn as its card in exports and prints, not as its file card): `docs/future-plans/email-in-exports.md`
- Agreed designs ready to build, not started: `docs/ready-to-build/` (several views on one vault with editing locked per root note: `multi-view-editing.md`; the phone as the desktop app on a smaller screen, editing, with search contexts and the AI chat: `phone-same-app.md`; deployment profiles (personal, self-hosted, hosted) and hardening self-hosted for the internet: `deployment-profiles.md`; a short community-only self-hosting page, no packaging: `self-hosting-page.md`; tag values with spaces in quotes, before the import: `quoted-tag-values.md`; Obsidian and Logseq imports with an import report, and the export as one ordered document in standard Markdown or HTML, for launch: `import-export-launch.md`; every Obsidian feature mapped into MetaList: `obsidian-mapping.md`)
- Incoming design notes, processed into the folders above as soon as they are seen: `docs/inbox/` (see AGENTS.md, "Design Inbox")

## Clients
- Electron packaging notes (planning doc): `docs/clients/electron.md`
