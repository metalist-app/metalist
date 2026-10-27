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
- AI chat: `docs/ui/ai-chat.md`; AI providers (OpenAI, Anthropic, Google): `docs/design/ai-providers.md`
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
- Future plan (sharing notes as HTML, with ontology fragments, recipes and no code plugins): `docs/future-plans/html-note-sharing.md`
- Future plan (Obsidian import and export, aliases and image widths mapped both ways): `docs/future-plans/obsidian-import-export.md`
- Might do (the same tag more than once in a note): `docs/future-plans/same-tag-twice.md`
- Agreed designs ready to build, not started: `docs/ready-to-build/` (property search on any tag and OR in rules: `attribute-search-and-or-rules.md`; AI conversation compaction with a readable summary: `ai-conversation-compaction.md`; a bookmarklet that clips a page into the open MetaList tab: `web-clipper.md`; custom link text for references, `[[UUID|shown text]]`: `reference-link-text.md`; menus and modals following the Light/Dark theme: `menus-follow-theme.md`; several views on one vault with editing locked per root note: `multi-view-editing.md`; the vault's property names in the tag bar when none of a tag's own match: `property-suggestions-fallback.md`; the phone as the desktop app on a smaller screen, editing, with search contexts and the AI chat: `phone-same-app.md`)
- Incoming design notes, processed into the folders above as soon as they are seen: `docs/inbox/` (see AGENTS.md, "Design Inbox")

## Clients
- Electron packaging notes (planning doc): `docs/clients/electron.md`
