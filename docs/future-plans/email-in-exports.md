# Emails in exports and prints

**Status:** Agreed with the maintainer 2026-10-29, not scheduled ("we can fix that gap later").

## The gap
An embedded email file (`![[UUID]]` of a `.eml`, `docs/ui/references.md`, "Email files") shows in MetaList as a card: subject, From/To/Cc/Date, the sanitized body, the attachments. An exported or printed note shows it as its file card instead (`EML` and the file's name): the card is filled in by the browser from `GET /files/{id}/email`, and an export has no server to ask.

## What fixing it means
- `embedded_references._render_static_file_body` draws the card itself for an email, as it inlines a picture's data URL: the export reads the email (`email_files.read_email`) while it renders, and writes the headers and the sanitized body into the page.
- Exports mirror how notes look in MetaList (maintainer, 2026-10-29): a folded note shows the one-line form (`EML`, subject, sender), an open one the card; a long body cut with Show all as in the app, or shown whole in print (to decide: paper can't click Show all).
- Remote pictures: an export page has no image proxy. To decide: leave them out, or inline them as exports inline attached pictures.
- Attachments: listed by name and size; to decide whether an export carries them (as data URLs, which can make an export large) or only lists them.
- Tests: a downloaded export and a print of a note holding an email show its subject, headers and body; a folded one shows its line.
