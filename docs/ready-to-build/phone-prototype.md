# Phone prototype: a blocked-in phone layout on the local network

**Status:** Agreed with the maintainer 2026-10-24. Ready to build, not started; filed here from `docs/inbox/` on 2026-10-24 (see "Found when filed"). **Build now:** the goal is a rough version working on the maintainer's iPhone over the local Wi-Fi within a few hours. Not finished, just blocked in. Polish, passkeys, offline and the native app come later.
**Scope:** A phone layout of the existing web app on narrow screens: search on top, notes below, a bottom bar with a view menu and a capture button, read-only notes with tag pills, and a simple capture screen.

Written without running the code. Code references were read on 2026-10-24; check each before relying on it, and build only what's missing.

---

## 1. What the phone is for

- **A read-only view of existing notes plus capture of new ones.** The phone never edits an existing note. For the prototype, this is enforced in the client only; a server-side rule (edit routes refuse phone clients) comes later.
- **One screen: search and notes.** No tabs on the phone. Nothing new is added where an existing piece (tags, search, the view options) can do the job.

## 2. Layout on narrow screens

Apply on a narrow viewport (choose the breakpoint; a coarse pointer is another hint). The desktop layout is unchanged.

- **Top: the search bar, full width,** and nothing else. The result count stays at its right.
  - **Search terms appear as pills in the search bar, each with an ×,** rather than as one text string, so a term can be dropped with one tap. Exclusion terms (`-journal`) appear as pills too, marked as exclusions (for example struck through or with a minus). Typing still works as today, with the existing tag suggestions (`/notes/search-suggestions`).
  - **The existing view chips** (sort order, date range, files, untagged: see `docs/ui/command-palette.md`) appear inside the search bar as they do on desktop, each with its ×.
- **Notes as rows below,** looking like desktop rows, with the existing expand and collapse toggles. **No tag chips on rows.**
- **Bottom: a slim bar** with:
  - **a menu button at bottom left:** opens a sheet from the bottom with the desktop's view options, nothing new: Sort order (Normal, Created, Updated, A–Z, Size, plus Reverse), Date range, Notes with files, Untagged notes. Use the existing tab-state endpoints (`/notes/tab-state/sort-mode`, `/notes/tab-state/date-filter`, `/notes/tab-state/file-filter`). Also **Lock** and **Sign out**.
  - **a + button at bottom right:** opens capture (§4).
  - The middle of the bar can hold one quiet status line later (for example "Offline"); leave it empty for now.
- **Hidden on the phone:** tabs, the side rail, and any other desktop-only chrome.

### Wireframes (concept sketches, not pixel specs)

```
 Search                         View menu (sheet from bottom)    Capture
┌──────────────────────────┐   ┌──────────────────────────┐   ┌──────────────────────────┐
│[🔍 upcoming ×][Created↑×] 6│   │[🔍 upcoming ×][Created↑×] 6│   │ ×        Capture     Save│
├──────────────────────────┤   │ ▾ 2026  (dimmed)         │   │┌────────────────────────┐│
│ ▾ 2026                   │   │╭────────────────────────╮│   ││ Interesting thread on  ││
│   ▸ Nov 2: birthday 7pm  │   ││ Sort order             ││   ││ spaced repetition…     ││
│     Nov 14: car renewal  │   ││   Normal               ││   ││ x.com/…/status/1847…   ││
│   ▸ Nov 21: haircut 10am │   ││   Created            ✓ ││   │└────────────────────────┘│
│ ▾ 2027                   │   ││   Updated · A–Z · Size ›││   │ Tags (optional)          │
│     Jan 9: Mom visiting  │   ││   Reverse            ✓ ││   │ [memory] lear▏           │
│                          │   ││ Date range   All dates ›││   │  learning  learning/sci… │
│                          │   ││ Notes with files  All ›││   │                          │
│                          │   ││ Untagged notes         ││   │ (no tags → tagged inbox) │
├──────────────────────────┤   ││ [ Lock ]  [ Sign out ] ││   │                          │
│ ☰                     (+)│   │╰────────────────────────╯│   │ keyboard mic dictates    │
└──────────────────────────┘   └──────────────────────────┘   └──────────────────────────┘

 Tapped note (read-only), pills shown; tap again hides them
┌──────────────────────────┐
│[🔍 ramen ×]             3│
├──────────────────────────┤
│ Ramen experiments        │
│  Tonkotsu needs 12+ hours│
│  ┌ Tare: soy, mirin… ┐   │
│  └ Eggs: 6 min 30 s  ┘   │
│  (recipes) (japanese)    │  ← this note's own tags; tapping one searches
│ ▸ Ramen shop list        │
├──────────────────────────┤
│ ☰                     (+)│
└──────────────────────────┘
```

## 3. Tapping a note

- **Tapping a note expands it** (if it has children) **and shows that note's own tags as pills underneath it. Tapping again hides them.** A toggle, not press-and-hold. Tapping never enters edit mode on the phone.
  - **Only the note's own tags:** a parent doesn't list its children's tags, and inherited tags aren't shown.
- **Tapping a tag pill runs a search.** Whether it **replaces** the current search or **narrows** it (adds the tag as a new pill) is undecided. **Build both behind a temporary developer switch** (not a user setting) so the maintainer can try each; one will be kept and the switch removed.
- **Swipe back returns to the previous search:** keep a short history of searches made on the phone and restore the previous one on the back gesture (browser history entries are one way).

## 4. Capture

- **A capture screen** opened by the + button: one text box, the existing tag suggestions for an **optional** tag line, then **Save** and a close ×.
- **Saving creates a new root note** through the existing create path (`POST /notes/new`, then `PUT /notes/{note_id}/save`, or whatever the code's create flow actually is) with the typed text, the typed tags, and **`inbox`** if no tags were typed. *Check:* the exact tag syntax a note uses for its tags.
- **The keyboard's microphone handles dictation;** nothing to build.
- **Not in the prototype:** photos, presets ("send to" buttons), the offline queue.

## 5. Making it work on the iPhone (for the maintainer, not code)

- The app already serves HTTPS on the local network with a self-signed certificate (repo `certs/`) for `10.0.0.31`, `Thomass-MacBook-Air.local`, `localhost` and `127.0.0.1`.
- For a smooth test: send the **public** certificate (`.pem`, never the key) to the iPhone, install it as a profile, and turn on full trust under **Settings → General → About → Certificate Trust Settings**. Then open `https://Thomass-MacBook-Air.local:<port>` and use **Share → Add to Home Screen.**
- **Check the PWA manifest** (`app/templates/base.html` links `/static/manifest.json`): give it `display: standalone`, a name and an icon so the home-screen version opens full screen with its own icon.

## 6. Out of scope for now

Passkeys and Face ID, offline caching, a server-side phone client type, photos and audio, capture presets, password tap-to-reveal and clipboard clearing, push notifications, and the native (Capacitor) app.

## The decided mock

`docs/ready-to-build/phone-prototype-mocks.html` (filed from `docs/inbox/` on 2026-10-24, "v3, decided") shows the four screens. Where it differs from the text above, the mock is the later decision:
- **Capture:** **Cancel** and **Save** at the lower right (Save rightmost), not a × and Save at the top; typed tags become pills in the tag line, with suggestions as chips under it.
- **A tapped note:** a quiet "Read-only" label with an eye sits in the middle of the bottom bar while a note's tags show.
- **Search bar:** query pills (blue; an exclusion struck through) and view pills (grey, e.g. "Created ↑") share the field and wrap to a second line; the count sits at the right on the black header.
- **The menu sheet:** Sort order lists Normal and Created, with "Updated · A–Z · Size ›" folded into one row, then Reverse; Date Range › and Notes with Files › show their current value; Untagged Notes; **Lock** and **Sign Out** as two buttons at the bottom.

## Found when filed (2026-10-24)

- **The references hold:** `POST /notes/search-suggestions` (`notes.py:568`), the tab-state routes `sort-mode`, `date-filter`, `file-filter` (`notes.py:477`, `:504`, `:521`), `POST /notes/new` and `PUT /notes/{note_id}/save` (`notes.py:1057`, `:1128`). The certificate in `certs/metalist-cert.pem` names `localhost`, `Thomass-MacBook-Air.local`, `127.0.0.1` and `10.0.0.31`. `base.html` links `/static/manifest.json`.
- **Conflict, the manifest's display:** the brand-mark work (2026-10-24, `brand/README.md`) set `display: "browser"` on purpose, so desktop Chrome does not start offering to install MetaList as an app. §5 asks for `standalone`, which a home-screen web app needs to open full screen, and which also brings desktop Chrome's install offer.
- **There is no Lock action today.** "Session locked" (`/locked`, `docs/ui/login-screen.md`) happens to the session; nothing lets the user lock it. Sign out exists (`Log Out`). §2's Lock needs defining.
- **Note tags** are a separate field beside the content (`NotesAPI.saveNote(noteId, content, tags)`), a space-separated tag line as the tag bar writes it; capture writes `inbox` there when no tag is typed.
- **Narrow breakpoint:** MetaList's existing narrow rules use 640 px (`main.css`), the obvious choice here.

Decided with the maintainer (2026-10-24):
1. The manifest becomes `display: standalone`, accepting desktop Chrome's install offer.
2. Lock logs out but keeps the vault picked, so getting back in is just the password.
3. Built now on `feature/phone-prototype` from `main`; the dialog conventions work is paused.
4. A capture with no tags is tagged **`@inbox`**, not `inbox`: a reserved meta tag (2026-10-24). Meta tags are not inherited, so an inbox note's children are not inbox notes too; search `@inbox` for what to sort. There is no inbox view or sorting step yet.

## 7. Done when

- On a narrow screen: search alone on top with query and view pills, rows below, the bottom bar with the view menu and +.
- Tapping a note shows and hides its own tag pills; tapping a pill searches (both behaviors behind the developer switch); swipe back restores the previous search.
- The + creates a tagged (or `inbox`-tagged) note that shows up on the desktop.
- Desktop behavior is unchanged.
- It runs on the maintainer's iPhone from the home screen over the local Wi-Fi.
