# Rename four built-in `@` tags, with a one-time conversion

**Status:** Agreed with the maintainer 2026-10-28. Ready to build, as a conversion in an upcoming version. Small.

Written from a read-only look at the repo. Check the code references before relying on them.

## Found when filed (2026-10-28)

Filed from `docs/inbox/2026-10-28-meta-tag-renames.md`.

- **References hold:** the old names are in `KNOWN_META_TAGS` (`tag-syntax-service.js`), `content_formatting.py`, `dictation_cleanup.py`, `app/api/routes/ai.py`, `note_renderer.py`, `ai-chat-panel-controller.js`, `add-style-service.js`, the four help skills, the listed docs and both ready-to-build notes. `content_cache.py` and `app/db/content_migrations_sql.py` exist as described: the stored-HTML cleaning runs when the content cache is filled, after unlock, and records its pass in `namespace_content_migrations`.
- **No `@` names in the other files listed:** `code_rendering.py`, `html_export.py`, `note_fullscreen.py`, `rendered_html.py`, `differential-view-service.js`, `notes_list.html` and `main.css` don't contain the old `@` names; at most internal names (classes), which §4 item 5 leaves to the builder.
- **The new names are free:** no built-in `@ai`, `@highlight`, `@bullets` or `@numbered` exists. `@gray` exists nowhere yet (only `@grey`), so accepting it is new.
- **Tests and a browser suite name the old tags:** besides `tests/unit/`, `scripts/browser-ai-response-menu-regressions.mjs`.
- **Where searches are stored:** each tab's (search context's) search in `tab_state`, and past searches in `search_history`. In an encrypted vault both are encrypted, so the pass has to run after unlock, as the HTML cleaning does. The notes' `proposed_tags` column holds tags too; rewrite it in the same pass.
- **Unknown `@` tags are removed when a tag bar is saved** (`docs/ui/tag-bar.md`), so an old name left anywhere would be dropped at the next edit. The pass must cover every place before the new code runs.
- **No schema change,** so no database version bump: the pass is recorded in the existing `namespace_content_migrations` table.
- **`convert-from-legacy.py` writes none of these tags,** so legacy imports need nothing; a converted database is converted on its first unlock anyway.

---

## 1. Why now

Before launch, renaming a built-in tag costs only the existing vaults (two, both personal installs). After launch, every old name has to keep working forever. The rule for names: **name what the note is, in words people already know** from Markdown, code fences and other apps.

## 2. The renames

| Old | New | Why |
|---|---|---|
| `@highlighter` | `@highlight` | Names the effect, not the tool; Markdown and Obsidian call it a highlight (`==text==`) |
| `@llm` | `@ai` | Marks a note holding an AI chat answer; "AI" is the common word, "LLM" is jargon |
| `@list-bulleted` | `@bullets` | Shorter |
| `@list-numbered` | `@numbered` | Shorter |

**Also:** accept `@gray` as well as `@grey`. Both stay valid, and neither is converted.

**Not renamed: `@shell`.** `@cli` was considered and rejected: the note is a shell script, `shell` is the code-fence name, and "CLI" describes an interface, not a script.

## 3. Where the old names live (found 2026-10-28)

- The built-in list: `KNOWN_META_TAGS` in `app/static/js/modules/mode-manager/services/tag-syntax-service.js`; `list_known_meta_tag_terms()` and `_META_TAG_TO_CLASS` / `_LIST_STYLE_TAGS` in `app/services/content_formatting.py`; the dictation list in `app/services/dictation_cleanup.py`.
- `@llm` written and read: `app/api/routes/ai.py` (`tags = "@llm"` for a saved chat answer), `app/presentation/render/note_renderer.py`, and `app/static/js/modules/ai-chat/ai-chat-panel-controller.js` (the Copy Response clipboard, `@markdown @llm`).
- Also: `app/services/code_rendering.py`, `app/services/html_export.py`, `app/services/note_fullscreen.py`, `app/security/rendered_html.py`, `add-style-service.js`, `differential-view-service.js`, `app/templates/notes_list.html`, `app/static/css/main.css`.
- AI help skills: `app/services/agent/skills/help-formatting.md`, `help-tags.md`, `help-dictation.md`, `help-mouse.md`.
- Docs: `docs/ui/content-formatting.md`, `tag-bar.md`, `ai-chat.md`, `controls.md`, `dictation-paste.md`, `docs/AI-SUMMARY.md`, and two ready-to-build notes (`phone-same-app.md`, `web-clipper.md`). The web-clipper note's open question about a provenance tag mentions `@llm`: keep it consistent with `@ai`.
- Tests under `tests/unit/` that name the old tags.

## 4. The conversion

1. **A one-time content pass per database,** in the style of the stored-HTML cleaning (`app/services/content_cache.py`, recorded through `app/db/content_migrations_sql.py`). It rewrites every note's tags from old names to new, including inside scoped wrappers (`{@highlighter}`, `((@list-numbered))`) and on comment-free tag strings alike. Recorded, so it runs once. A restored older backup lacks the record, so it's converted too. Keep each note's updated time, as the cleaning does.
2. **No compatibility for the old names.** After the conversion they are simply unknown `@` tags, treated like any other unknown one. There are no users beyond the two existing vaults, so nothing should be kept for old habits or old files.
3. **Everything MetaList writes or suggests uses the new names:** saved chat answers (`@ai`), Copy Response (`@markdown @ai`), tag-bar and search suggestions, the AI's help skills and tagging, the docs.
4. **Saved searches and search contexts** that contain an old name are rewritten in the same pass. Find where they're stored first.
5. **Internal names** (CSS classes such as `meta-highlighter`, function names) are your call. Only the tag names users see must change.

## 5. Acceptance checks

- A vault with notes tagged `@highlighter`, `@llm`, `@list-bulleted` and `@list-numbered`, globally and inside scoped wrappers, reads `@highlight`, `@ai`, `@bullets` and `@numbered` after the upgrade, renders exactly as before, and keeps each note's updated time.
- The pass runs once. Restoring a backup made before the upgrade converts it again.
- The old names appear nowhere in the code, suggestions, help skills or docs (outside the conversion pass itself).
- `@gray` and `@grey` both make text gray.
- A new chat answer saved as a note is tagged `@ai`, and renders as chat answers do today.
- Suggestions, help skills and docs mention only the new names (and both spellings of gray).
- A saved search for `@llm` finds the same notes after the upgrade.
