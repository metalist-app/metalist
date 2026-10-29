# No repeated site icon and domain under a link to the same site

**Status:** Agreed with the maintainer 2026-10-28. Ready to build. Small. Filed here from `docs/inbox/` on 2026-10-28 (see "Found when filed").

Written from a read-only look at the repo. Check the code references before relying on them.

---

## 1. Today

Every web link shows the site's icon, its text, then ` · domain` (`docs/ui/content-formatting.md`, "Links In View Mode"; `_decorate_web_link()` in `app/services/content_formatting.py`). The only exception: text that already is the domain isn't followed by it again.

Example: a note links a YouTube video; its one child holds the video's chapters as nine timestamp links (`0:00 Intro`, `0:57 …`). Every chapter repeats the YouTube icon and `· youtube.com`, nine copies of what the line above already says, burying the part that differs.

## 2. The rule

**A web link whose site is also linked from any of its note's ancestors shows no icon and no ` · domain`, only its text.**

- **Any ancestor,** not just the parent: a note per chapter under the chapter list works the same.
- **Any web link anywhere in the ancestor's text counts,** not only its first line.
- **What stays:** the link's text (its own text, or the fetched title of a bare address), underlined in link color. A bare address without a title shows as it does today.
- **Same site:** the same domain, any subdomain (`www.`, `m.`, `music.youtube.com` and `old.reddit.com` count as `youtube.com` and `reddit.com`; decided 2026-10-28); `youtu.be` counts as `youtube.com`. If the code already has a notion of one site across hosts (the oEmbed list treats `youtu.be` as YouTube; the polite per-site lookups key on the host without `www.`), reuse it.

## 3. Where the ancestors aren't shown

A note is only ever shown with its ancestors above it, except in a **reference**: a link's preview, or an embed. There the note's links **keep their icon and domain**, since nothing on screen says which site they go to.

In an embed, the embedded note's own ancestors aren't shown, so its links keep icon and domain; its children shown inside the embed have it above them, so the rule applies among them. The note holding the embed and that holder's ancestors don't count: they aren't the source's ancestors.

## 4. Implementation notes (your call)

- Decoration happens per note on the server (`format_note_content_for_view` gets the note's own HTML and tags, no tree context). Either pass the sites linked from the note's ancestors into the render, or mark each decorated link with its site and hide the icon and domain in the browser when an ancestor on screen links to the same site. The second keeps references simple (no ancestors on screen, nothing hidden), but it must not flicker on refresh.
- A note's links can change because of another note: an ancestor gains or loses a link, or the note moves under a different parent. Make sure any cached rendering refreshes then.

## 5. Done when

1. Under a note linking a YouTube video, a child's timestamp links show only their text (`0:57`), no icon, no `· youtube.com`; a grandchild's too.
2. A link to a different site in that child keeps its icon and domain.
3. A `youtu.be` link under a `youtube.com` link (and the reverse) loses its icon and domain; `www.` and `m.` don't matter.
4. The same child shown as a link preview or in an embed, without its ancestors, keeps icon and domain on its links.
5. Removing the ancestor's link, or moving the child elsewhere, brings the icon and domain back on the next view.
6. Tests cover 1–5; `docs/ui/content-formatting.md` ("Links In View Mode") and `docs/ui/references.md` describe the rule.

## Found when filed (2026-10-28)

- The code references hold: `_decorate_web_link()` and `format_note_content_for_view(*, content_html, tags, redact_credentials)` in `app/services/content_formatting.py`; the render gets no tree context, as §4 says. Not built: nothing in the decoration looks at ancestors.
- There is no shared notion of "one site across hosts" to reuse. Two helpers strip only `www.` (`_bare_host` in `content_formatting.py`, the per-site key in `link_titles.py`); neither strips `m.`. `youtu.be` appears only in `_OEMBED_ENDPOINTS` (`link_titles.py`), which maps hosts to oEmbed URLs: `youtube.com`, `m.youtube.com`, `music.youtube.com` and `youtu.be` share YouTube's, `reddit.com` and `old.reddit.com` Reddit's. It groups hosts by endpoint, not by site, so "same site" is new code; one helper the decoration and that table could share. Decided 2026-10-28: the same domain counts as the same site, any subdomain included. `_site_domain_labels()` in `link_titles.py` already gives a host's own domain (`reddit.com` for `old.reddit.com`, `bbc.co.uk` for `news.bbc.co.uk`) and can be reused; `youtu.be` still needs mapping to `youtube.com`.
