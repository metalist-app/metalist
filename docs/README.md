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
- Bringing in the old MetaList's notes (a fresh install offers them; the old file only read): `docs/ui/legacy-import.md`

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
- Ready to build, an experiment behind a setting (virtual folders: a tag ending in `/` is a folder, shown as a tree in the left margin; the import's folder tags get the slash): `docs/ready-to-build/virtual-folders.md`; files and folders dropped from the desktop (built 2026-11-02, resuming an interrupted upload not yet): `docs/ready-to-build/desktop-drops-into-folders.md`
- Ready to build (a prefix folder for every import, so a whole import is one folder): `docs/ready-to-build/import-prefix-folder.md`
- Ready to build (importing a folder of any files, with a size check and file-type checklist; previews for code, PDF, RTF/.docx, HTML, audio and video): `docs/ready-to-build/folder-import-and-file-previews.md`
- Ready to build, replacing that note's preview notes (files shown, not copied: kept text for every file with text, a viewer with Open and Download, audio and video players, dropped `.md`/`.txt` asked about, Convert to Note): `docs/ready-to-build/files-shown-not-copied.md`
- Ready to build (a link dragged from a browser becomes a note holding it, on the column, a tree folder or into an edited note): `docs/ready-to-build/dropped-links.md`
- Built 2026-11-02, Chrome's and Safari's exports still to check (browser bookmarks as an import source: one note per website address, its title linked, folders as folder tags, dated when bookmarked; a dropped export asks Import or Keep as File): `docs/ready-to-build/bookmark-import.md`
- Future plan (charts of super-tag values, embedded like diagrams): `docs/future-plans/charts.md`
- Future plan (one encrypted file per attachment, with a catalog): `docs/future-plans/file-storage-per-file.md`
- Future plan (backups to S3-compatible storage, uploaded by MetaList itself; manual or automatic): `docs/future-plans/backups-s3.md`
- Ready to build (nothing shown as Saved is ever lost: autosave, retries with change IDs, the graceful stop): `docs/ready-to-build/commit-and-shutdown-protocol.md`
- Future plan (model-checking the save, backup, lock and linked-list protocols with TLA+, with Hypothesis stateful tests on the real code): `docs/future-plans/model-checking-protocols.md`
- Future plan (user-named styles, `@style=name`, a safe subset of CSS): `docs/future-plans/user-styles.md`
- Being worked out, don't build yet (a bookmarklet that copies a page's title, address and selection for pasting into MetaList): `docs/future-plans/web-clipper.md`
- Tried and rejected (dragging a note to any level by the note released on; needs a different control system): `docs/future-plans/drag-across-levels.md`
- Future plan (a hover card on the Referenced by badge listing the referring notes): `docs/future-plans/referenced-by-hover-card.md`
- Future plan (an embedded email drawn as its card in exports and prints, not as its file card): `docs/future-plans/email-in-exports.md`
- Agreed designs ready to build, not started: `docs/ready-to-build/` (several views on one vault with editing locked per root note: `multi-view-editing.md`; the phone as the desktop app on a smaller screen, editing, with search contexts and the AI chat: `phone-same-app.md`; deployment profiles (personal, self-hosted, hosted) and hardening self-hosted for the internet: `deployment-profiles.md`; a short community-only self-hosting page, no packaging: `self-hosting-page.md`; Obsidian and Logseq imports with an import report, and the export as one ordered document in standard Markdown or HTML, for launch: `import-export-launch.md`; every Obsidian feature mapped into MetaList: `obsidian-mapping.md`)
- Incoming design notes, processed into the folders above as soon as they are seen: `docs/inbox/` (see AGENTS.md, "Design Inbox")

## Clients
- Electron packaging notes (planning doc): `docs/clients/electron.md`
