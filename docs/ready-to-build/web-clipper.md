# Web clipper: a bookmarklet that hands the clip to the open MetaList tab

**Status:** Agreed with the maintainer 2026-10-24 to 2026-10-26. **Wanted by launch** (desktop browsers). Ready to build, not started; filed here from `docs/inbox/` on 2026-10-26 (see "Found when filed" for what to settle first).
**Scope:** clipping a web page's title, address and selected text into MetaList from any desktop browser, with no extension, as a new note in the MetaList tab that's already open.

Written without running the code. Check every reference before relying on it; build only what's missing. Document the result in `docs/ui/` (a new page for the clipper) and in the help.

---

## 1. What it is

- A **bookmarklet**: a bookmark whose address is a few lines of JavaScript (`javascript:…`). Clicking it runs that code on the page being viewed.
- Why: no install, no store, works in Chrome, Firefox, Safari and Edge, and often on locked-down work computers where extensions are blocked. It acts only when clicked, on that page only.
- A clip is **an ordinary note**, made the way Enter makes a new note. No new note type, no separate screen.

## 2. The flow

1. On any page, the user optionally selects text and clicks **Clip to MetaList**.
2. **The bookmarklet reads only:** `document.title`, `location.href`, and the selection as **plain text** (`getSelection().toString()`). Nothing else: no page HTML, no cookies, no form fields.
3. **It opens the relay page** on the MetaList instance's own origin (for example `https://<instance>/clip`), inside the click so popup blockers allow it.
4. **Handshake, then hand-off with `postMessage`:**
   - The relay loads and posts a **contentless "ready"** message to its opener.
   - The bookmarklet waits for "ready" **from the relay's exact origin**, then sends the clip with `postMessage(clip, "<instance origin>")`.
   - **The clip never appears in any URL:** not in the query string, not after `#`. So it's never in server logs, browser history or synced history.
5. **The relay passes the clip to the open MetaList tab** over a `BroadcastChannel` (same-origin only) and waits briefly for an acknowledgment.
   - **The relay never connects to the server, signs in or reads the vault.** It isn't a MetaList session and must not log out or lock any open tab. It keeps the clip in memory only.
6. **The open MetaList tab adds the clip as a new note at the top, in edit mode,** exactly as Enter/+ creates a new note (it inherits nothing from the current search; see §4 for tags). It acknowledges; **the relay closes itself.**
7. **The note saves like any note** (autosave as usual). There is **no draft or Save/Discard step** (maintainer's decision: a clip should "just work like anything else"). Unwanted clips are deleted or undone like any note.

### 2.1 Edge cases
- **No MetaList tab open:** no acknowledgment arrives, so the relay **becomes the MetaList tab**: it loads the app (sign-in or unlock as usual), then adds the clip as a new note. The clip is held in memory until then.
- **The open tab is locked:** unlock as usual first, then the clip is added. The clip waits in memory, never on disk.
- **Several MetaList tabs open:** only one handles the clip (the active one under the current session rules); others ignore it.
- **The user is mid-edit:** never interrupt or overwrite text being typed. Add the clip once the current edit ends (or at the top without taking focus; choose and document). Queue at most one pending clip.
- **Sites that block bookmarklets** (some security policies stop scripts they didn't load): nothing happens; the fallback is copy and paste. Check behavior on a handful of major sites in each browser.
- **Very long selections:** cap the clip (for example 100,000 characters) and say so in the note if it was cut.

## 3. What a clipped note contains

- **First line:** the page title.
- **Then:** the address, as a link (link titles and site icons then apply as for any link).
- **Then, if text was selected:** the selection as a quote.
- **Tags:** see §4.
- Plain text only: no fetched article content, images or screenshots.

## 4. Tags on a clip

- **Every clip gets the built-in `@web` tag** (provenance, like `@ai`): searching `@web` finds everything clipped, and rules can style it. Add `@web` to the reserved `@` tags if it doesn't exist.
- **Tagging happens in MetaList, never in the bookmarklet.** The bookmarklet's code runs inside the clipped page, so it must **never contain tag names** or anything else from the vault.
- **Two strategies, combinable:**
  1. **Fixed tags for every clip:** a setting where the user lists tags added to all clips (for example `to-read`).
  2. **AI suggestions:** if the user has AI set up, the AI reads the clip (title, address, selection) and proposes tags **from the user's own tags**. They're filled into the new note's tags, **visible in edit mode**, to keep or delete. Same privacy rules as the existing AI tag suggestions: excluded tags (whitelists/blacklists) never reach the AI. One small request per clip, on the user's key. Without AI set up, clips get fixed tags and `@web` only.
- **Not used (the maintainer rejected them):** matching tag names against the page text (generic tags misfire), and reusing tags from earlier clips of the same website (aggregator sites like Hacker News make it meaningless).

## 5. Security rules

1. **The bookmarklet reads only title, address and selection,** and sends them only to the instance's own origin. It never touches MetaList pages; MetaList pages never load anything from the clipped site.
2. **No clip data in any URL** (postMessage with exact target origin, after the "ready" handshake).
3. **Clipped text is untrusted:** stored and shown as plain text, HTML escaped, never rendered, using the existing paste sanitization.
4. **The relay holds nothing** and never connects to the server.
5. **Minimal message format, validated on arrival:** a version number plus title, URL and selection, all strings with length limits; anything else is dropped.
6. **Accepted risk, documented:** any website could open the relay with junk, which would become a saved note (no draft step). Mitigations: the note arrives visibly at the top in edit mode, tagged `@web`, removable with one undo; the relay accepts **one clip per opening**; nothing arrives without a relay window or MetaList tab visibly opening.

## 6. Installing it

- A settings page (and a command-palette action, "Install web clipper") shows a **"Clip to MetaList" link to drag onto the bookmarks bar**, with one sentence of explanation.
- **The bookmarklet is generated with the instance's own origin** (hosted, self-hosted or local, for example `https://<host>.local:<port>`). Never hard-coded.
- The message carries a version so older installed bookmarklets keep working or get a "please reinstall" note.

## 7. Not in scope

A real browser extension; the phone's Share menu (needs a native app); fetching full articles, images or screenshots.

## 8. Tests

- Clip with and without a selection: a new note at the top with title, link and quote, tagged `@web`.
- MetaList tab open and unlocked: the clip appears there; nothing locks or logs out; the relay closes.
- No MetaList tab open: the relay becomes MetaList and adds the clip after sign-in/unlock.
- Locked tab: unlock, then the clip.
- Mid-edit: typed text is never interrupted or overwritten; the clip follows.
- Fixed clip tags are added; with AI configured, suggested tags appear in edit mode and excluded tags never reach the AI; without AI, only fixed tags and `@web`.
- A page that opens the relay itself with crafted data: at most one note, visible, tagged `@web`, removable with one undo; HTML stays inert.
- The clip appears in no URL, server log or history entry.
- Over-long selection is cut and labeled.
- Works in current Chrome, Firefox and Safari on desktop.

## 9. Invariants

1. The bookmarklet reads only title, address and selection, sends them only to the instance's origin, and never contains tag names.
2. Clip data never appears in a URL.
3. The relay never connects to the server; clipping never locks or logs out an open MetaList.
4. A clip is an ordinary note: it saves like any note and is removed by delete or undo.
5. Every clip carries `@web`; AI-suggested tags are visible in edit mode, never applied silently.
6. Clipped text is plain, untrusted text.

## Found when filed (2026-10-26)

Checked against the code; nothing of the clipper exists yet (no `/clip` route, no `BroadcastChannel` anywhere in the app).

1. **One signed-in tab per vault.** Signing in clears every earlier session ("Multi-Client Support" in `docs/security/README.md`: one active browser tab/session per namespace, tokens bound to `X-Metalist-Tab-Id`). So §2.1 "several MetaList tabs open" cannot happen as written: only one tab is ever signed in. More important, "no MetaList tab open → the relay becomes the MetaList tab" signs in, which signs out a tab that is open but slow to acknowledge (busy, or throttled in the background), against invariant 3 ("clipping never locks or logs out an open MetaList"). **Open:** how long the relay waits, and whether it asks before signing in.
2. **"Exactly as Enter/+ creates a new note" contradicts "it inherits nothing from the current search":** a note made with Enter while a positive tag search is active takes that search's tags (`docs/ui/search-semantics.md`; `compute_initial_tags_for_new_note` in `app/usecases/create_note.py`). The phone's capture is the closer model: a new note at the top with only its text and tags, tagged `@inbox` when it has none (`docs/ui/phone.md`, `app/static/js/modules/phone/phone-mode.js`).
3. **`@ai` is not a provenance tag:** `@ai` marks a note holding a rendered AI chat answer (`app/presentation/render/note_renderer.py`). `@web` is new. **Open:** a built-in tag (listed in `KNOWN_META_TAGS` in `tag-syntax-service.js`, mirrored in `app/services/dictation_cleanup.py` with a unit test keeping them equal, and in `content_formatting.list_known_meta_tag_terms`; shown as "A built-in tag", dictated as "at web"), or an ordinary `@` tag as `@inbox` is (meta tags are never inherited either way).
4. **Sites that cut the popup off:** a page sending `Cross-Origin-Opener-Policy: same-origin` (common on large sites) severs the link to a window it opens on another site, so the relay has no opener to post "ready" to and the handshake (§2.4) fails there. §2.1 covers pages whose script policy blocks bookmarklets, not this. **Open:** accept (copy and paste, as for blocked pages) or design a fallback that still keeps the clip out of every URL; check on major sites per browser.
5. MetaList's own pages send `frame-ancestors 'none'` and `X-Frame-Options: DENY` but no `Cross-Origin-Opener-Policy` (`app/security/http_headers.py`), so the relay, opened as a window rather than a frame, keeps its opener from MetaList's side.
6. **Mid-edit** (§2.1) is still the note's own open choice: add once the edit ends, or at the top without taking focus. Per `docs/ui/interaction-principles.md` it needs a case list before building.
7. **Fixed clip tags** (§4): **open** where the setting lives; client preferences in the vault (encrypted, `docs/security/README.md`) fit.
8. **AI suggestions** (§4) can reuse Suggest Tags with AI's path and its cloud-privacy filtering (`app/services/agent/note_tag_suggestions.py`, `cloud_privacy.py`), which already keeps private notes and excluded tags from the AI.
9. **Install web clipper** in the command palette needs an entry in `app/static/config/agent-menu-actions.json` and the AI's help skills (`app/services/agent/skills/help-*.md`), as every palette action does.

