# Web clipper: a bookmarklet that hands the clip to the open MetaList tab

**Status:** **Ready to build, through the clipboard** (maintainer, 2026-10-28): a "Copy for MetaList" bookmarklet copies the clip, and the user pastes it into MetaList where they want it. See "The clipboard instead" at the end, and settle its "To settle before building" first. Everything above that section describes the earlier helper-page design, which was put on hold the same day over its security hole; it is kept for its reasoning (what a clip contains, tags, plain untrusted text), not to be built. Earlier: agreed 2026-10-24 to 2026-10-26.
**Scope:** clipping a web page's title, address and selected text into MetaList from any desktop browser, with no extension, as a new root note, saved only after the user confirms it.

Written without running the code. Check every reference before relying on it; build only what's missing. Document the result in `docs/ui/` (a new page for the clipper) and in the help.

---

## 1. What it is

- A **bookmarklet**: a bookmark whose address is a few lines of JavaScript (`javascript:…`). Clicking it runs that code on the page being viewed.
- Why: no install, no store, works in Chrome, Firefox, Safari and Edge, and often on locked-down work computers where extensions are blocked. It acts only when clicked, on that page only.
- A clip is **an ordinary note**: a new root note at the top of the outline. No new note type.

## 2. The flow

1. On any page, the user optionally selects text and clicks **Clip to MetaList**.
2. **The bookmarklet reads only:** `document.title`, `location.href`, and the selection as **plain text** (`getSelection().toString()`). Nothing else: no page HTML, no cookies, no form fields.
3. **It opens the helper page** on the MetaList instance's own origin (for example `https://<instance>/clip`), inside the click so popup blockers allow it.
4. **Handshake, then hand-off with `postMessage`:**
   - The helper page loads and posts a **contentless "ready"** message to its opener.
   - The bookmarklet waits for "ready" **from the helper page's exact origin**, then sends the clip with `postMessage(clip, "<instance origin>")`.
   - **The clip never appears in any URL:** not in the query string, not after `#`. So it's never in server logs, browser history or synced history.
5. **The helper page is a MetaList view of its own** (decided 2026-10-28). It uses the browser's existing sign-in, which every MetaList tab in that browser shares (`multi-view-editing.md`), so it **never signs out or locks any open tab or device**. It doesn't hand the clip to an open tab: whatever an open tab shows has nothing to do with the page being clipped.
6. **It shows a preview and waits for the user** (decided 2026-10-28): the page title, the address, the selected text, and a **tag box** (§4). **Confirm** (or Enter) saves the clip; **Cancel** (or Escape) closes the window and saves nothing. The clip is held in memory until then, never on disk.
7. **On Confirm** the clip is saved as a new root note at the top of the outline, and the window closes. The note then behaves like any note: edited, deleted or undone as usual.
8. **Other views** show it like any note saved elsewhere: a view whose search the clip matches gets it at the top, without moving what the user is looking at (`docs/ui/interaction-principles.md`); scrolled down, it's out of sight until they scroll up. A view whose search it doesn't match doesn't show it.

### 2.1 Edge cases
- **This browser isn't signed in, or the vault is locked:** the helper page shows sign-in or unlock first, then the preview.
- **Open MetaList tabs, here or on other devices,** take no part; nothing in them is interrupted, and no edit in progress is touched.
- **Sites that block bookmarklets** (some security policies stop scripts they didn't load): nothing happens; the fallback is copy and paste. Check behavior on a handful of major sites in each browser.
- **Very long selections:** cap the clip (for example 100,000 characters) and say so in the note if it was cut.

## 3. What a clipped note contains

- **First line:** the page title.
- **Then:** the address, as a link (link titles and site icons then apply as for any link).
- **Then, if text was selected:** the selection as a quote.
- **Tags:** see §4.
- Plain text only: no fetched article content, images or screenshots.

## 4. Tags on a clip

- **The preview's tag box** (decided 2026-10-28) is an editable text box holding the fixed clip tags. The user can remove them and type in more. `@web` is always added and can't be removed there: it is shown beside the box, not in it.
- **Every clip gets the built-in `@web` tag** (provenance, like `@ai`): searching `@web` finds everything clipped, and rules can style it. Add `@web` to the reserved `@` tags if it doesn't exist.
- **Tagging happens in MetaList, never in the bookmarklet.** The bookmarklet's code runs inside the clipped page, so it must **never contain tag names** or anything else from the vault.
- **Two strategies, combinable:**
  1. **Fixed tags for every clip:** a setting where the user lists tags added to all clips (for example `to-read`).
  2. **AI suggestions:** when AI is set up and **AI tags for clips** is on (a menu setting, decided 2026-10-28), the AI reads the saved clip (title, address, selection) and proposes tags **from the user's own tags**, as **proposed tags** on the new note, accepted or rejected like any AI-proposed tags (never applied silently). Same privacy rules as the existing AI tag suggestions: excluded tags (whitelists/blacklists) never reach the AI. One small request per clip, on the user's key. Without it, clips get `@web` and the tags in the box only.
- **Not used (the maintainer rejected them):** matching tag names against the page text (generic tags misfire), and reusing tags from earlier clips of the same website (aggregator sites like Hacker News make it meaningless).

## 5. Security rules

1. **The bookmarklet reads only title, address and selection,** and sends them only to the instance's own origin. It never touches MetaList pages; MetaList pages never load anything from the clipped site.
2. **No clip data in any URL** (postMessage with exact target origin, after the "ready" handshake).
3. **Clipped text is untrusted:** stored and shown as plain text, HTML escaped, never rendered, using the existing paste sanitization.
4. **Nothing is saved without the user's Confirm** in the helper page (decided 2026-10-28). The helper page keeps the clip in memory only until then.
5. **Minimal message format, validated on arrival:** a version number plus title, URL and selection, all strings with length limits; anything else is dropped.
6. **A website can't add a note.** Any website can open the helper page and hand it a made-up clip (it can't tell a bookmarklet from a site's own script). That clip only reaches the vault if the user confirms its preview, so spam needs the user's own Confirm (maintainer, 2026-10-28: without that guarantee there is no clipper). The helper page accepts **one clip per opening**.

## 6. Installing it

- A settings page (and a command-palette action, "Install web clipper") shows a **"Clip to MetaList" link to drag onto the bookmarks bar**, with one sentence of explanation.
- **The bookmarklet is generated with the instance's own origin** (hosted, self-hosted or local, for example `https://<host>.local:<port>`). Never hard-coded.
- The message carries a version so older installed bookmarklets keep working or get a "please reinstall" note.

## 7. Not in scope

A real browser extension; the phone's Share menu (needs a native app); fetching full articles, images or screenshots.

## 8. Tests

- Clip with and without a selection: after Confirm, a new root note at the top with title, link and quote, tagged `@web` and the tag box's tags.
- Cancel or Escape saves nothing.
- With MetaList tabs open in this browser and on another device: nothing in them signs out, locks or is interrupted; a tab whose search matches gets the clip without moving what it shows.
- Not signed in, or locked: sign-in or unlock, then the preview.
- The tag box: fixed clip tags removable, new tags addable, `@web` always added.
- With AI tags for clips on, suggestions arrive as proposed tags and excluded tags never reach the AI; off or no AI, none.
- A page that opens the helper page itself with crafted data: nothing is saved unless the preview is confirmed; HTML stays inert.
- The clip appears in no URL, server log or history entry.
- Over-long selection is cut and labeled.
- Works in current Chrome, Firefox and Safari on desktop.

## 9. Invariants

1. The bookmarklet reads only title, address and selection, sends them only to the instance's origin, and never contains tag names.
2. Clip data never appears in a URL.
3. Nothing is saved without the user's Confirm; clipping never locks or logs out an open MetaList.
4. A clip is an ordinary note once saved: removed by delete or undo like any note.
5. Every clip carries `@web`; AI-suggested tags arrive as proposed tags, never applied silently.
6. Clipped text is plain, untrusted text.

## Found when filed (2026-10-26)

Checked against the code; nothing of the clipper exists yet (no `/clip` route, no `BroadcastChannel` anywhere in the app).

1. **Several signed-in views per vault** (corrected 2026-10-28; first filed as "one signed-in tab per vault", which looked only at today's code). Today signing in still clears every earlier session ("Multi-Client Support" in `docs/security/README.md`), but the agreed design is several tabs and devices signed in to one vault at once, with editing locked per root note (`docs/ready-to-build/multi-view-editing.md`). Settled by "Decided 2026-10-28": the helper page is a view of its own and saves the clip itself, so the clipper is built with or after multi-view-editing.
2. **"Exactly as Enter/+ creates a new note" contradicts "it inherits nothing from the current search":** a note made with Enter while a positive tag search is active takes that search's tags (`docs/ui/search-semantics.md`; `compute_initial_tags_for_new_note` in `app/usecases/create_note.py`). The phone's capture is the closer model: a new note at the top with only its text and tags, tagged `@inbox` when it has none (`docs/ui/phone.md`, `app/static/js/modules/phone/phone-mode.js`).
3. **`@ai` is not a provenance tag:** `@ai` marks a note holding a rendered AI chat answer (`app/presentation/render/note_renderer.py`). `@web` is new. **Open:** a built-in tag (listed in `KNOWN_META_TAGS` in `tag-syntax-service.js`, mirrored in `app/services/dictation_cleanup.py` with a unit test keeping them equal, and in `content_formatting.list_known_meta_tag_terms`; shown as "A built-in tag", dictated as "at web"), or an ordinary `@` tag as `@inbox` is (meta tags are never inherited either way).
4. **Sites that cut the popup off:** a page sending `Cross-Origin-Opener-Policy: same-origin` (common on large sites) severs the link to a window it opens on another site, so the helper page has no opener to post "ready" to and the handshake (§2.4) fails there. §2.1 covers pages whose script policy blocks bookmarklets, not this. **Open:** accept (copy and paste, as for blocked pages) or design a fallback that still keeps the clip out of every URL; check on major sites per browser.
5. MetaList's own pages send `frame-ancestors 'none'` and `X-Frame-Options: DENY` but no `Cross-Origin-Opener-Policy` (`app/security/http_headers.py`), so the helper page, opened as a window rather than a frame, keeps its opener from MetaList's side.
6. **Mid-edit** (§2.1) is still the note's own open choice: add once the edit ends, or at the top without taking focus. Per `docs/ui/interaction-principles.md` it needs a case list before building.
7. **Fixed clip tags** (§4): **open** where the setting lives; client preferences in the vault (encrypted, `docs/security/README.md`) fit.
8. **AI suggestions** (§4) can reuse Suggest Tags with AI's path and its cloud-privacy filtering (`app/services/agent/note_tag_suggestions.py`, `cloud_privacy.py`), which already keeps private notes and excluded tags from the AI.
9. **Install web clipper** in the command palette needs an entry in `app/static/config/agent-menu-actions.json` and the AI's help skills (`app/services/agent/skills/help-*.md`), as every palette action does.

## Decided 2026-10-28

- **The helper page saves the clip itself,** as a view of its own using the browser's shared sign-in; it never hands the clip to an open tab (the tab you happen to have open has nothing to do with what you clip). So it needs `multi-view-editing.md` first: today signing in would sign out the open tab, which must never happen.
- **A preview with Confirm before anything is saved,** replacing "no draft or Save/Discard step" (2026-10-24): any website could otherwise put spam in the vault. The maintainer: without that guarantee there should be no clipper.
- **The preview's tag box** holds the fixed clip tags, editable (remove them, add others); `@web` is always added and can't be removed.
- **AI-suggested tags become proposed tags** on the saved note, and only when the menu setting for AI tags on clips is on.
- **Other views** show a clip as any note saved elsewhere, without moving what the user is looking at.
- This settles "Found when filed" 1 (no tab is chosen), 2 (nothing comes from an open tab's search) and 6 (no edit in progress is touched).

## Open when put on hold (2026-10-28)

- **Tricking the user into Confirm.** A website can't press Confirm, but it can open the helper page (with its own made-up clip) right under the pointer as the user clicks on its page, or while they press Enter there, so that click or key lands on Confirm unread. Proposed, not agreed: Confirm counts only a click that starts inside the preview after it appears (the pointer has entered the window since), and the key is Cmd+Enter, not Enter; neither depends on timing. A half-second delay before Confirm works, as browsers do for their permission prompts, was considered weaker. The maintainer was not convinced the clipper can be made safe enough and put it on hold.
- **A browser extension instead** (discussed 2026-10-28): it would close the hole (a web page can't press the browser's own button, open an extension's window or message it), but costs a build per browser family (Safari needs an Apple developer account and an app wrapper), store review, its own sign-in as a device, a setting for the instance's address, blocked installs on locked-down computers, and a new risk in a compromised update. The maintainer turned that down too: **no clipper initially.**

## The clipboard instead (proposed 2026-10-28, the maintainer's idea)

- **A "Copy for MetaList" bookmarklet:** on a page, optionally select text and click it. It copies the page title, the address and the selection to the clipboard in two forms: **plain text** (title, address, quote on separate lines; readable pasted anywhere) and **marked-up HTML** that MetaList recognises as a clip.
- **The user pastes it into MetaList,** which turns it into a clip: the title, the address as a link, the selection as a quote, with `@web` and the fixed clip tags (§3, §4).
- **No helper page, no messages between sites, nothing sent to MetaList by the page:** a clip reaches the vault only through the user's own paste. A website can already put anything in the clipboard; it can't paste, and it can't reach the vault. So the hole that put the clipper on hold is gone.
- **Better control** (maintainer): the user decides where the clip lands, by where they paste it, instead of a new root note at the top.
- **No browser plugin needed,** so none of the extension costs. The maintainer's first version of the idea was a plugin adding the page's details to every Ctrl+C; a bookmarklet does the same with one click and changes no other copy.
- **Limits:** two steps (click the bookmark, then paste); sites that block bookmarklets fall back to copying by hand; a website could alter what lands in the clipboard (a fake title or link), seen in the note when pasted, as with any copied text.
- **To settle before building:** what a paste does where (into the text of a note being edited, or as a new note beside or under the selected one, as `Paste Sibling Note` and `Paste Child Note` do for copied notes); whether the AI-suggested tags (proposed tags, behind the menu setting) still apply, given that AI tag suggestions on every substantial paste were rejected the same day: a freshly pasted note has no tags yet, so excluded tags can't keep a private paste from the cloud AI; and how the bookmarklet writes both forms in each browser (the Clipboard API inside the click, or a copy of a hidden element where that is blocked).
