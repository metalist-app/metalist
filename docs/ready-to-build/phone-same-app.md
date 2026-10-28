# Phone: the same app on a smaller screen

**Status:** Agreed with the maintainer 2026-10-24 to 2026-10-27. Ready to build. **Replaces "read-only plus capture"** (`docs/ui/phone.md`) and most of `docs/future-plans/phone-later.md`. Build it **with or after** `docs/ready-to-build/multi-view-editing.md`: the phone edits, so it needs every view signed in and one editor per root note. Please propose a build order before starting.
**Scope:** the phone web app (home-screen install, under 640 px) becomes the desktop app on a smaller screen: it edits, it has search contexts and the AI chat. Update `docs/ui/phone.md`, `docs/future-plans/phone-later.md`, `docs/ui/interaction-principles.md` (one exception, §5) and the tests.

Written without running the code. Every reference below came from reading it and must be checked before relying on it; build only what's missing.

---

## 0. The idea

The phone is **another view of the vault**, like a second browser tab. It does what the desktop does, with the desktop's pieces, trimmed where a phone has no room. Nothing phone-specific is invented where an existing piece (tags, search, search contexts, the menus) does the job. Why: one set of rules to remember, not a second app with its own ("you don't have to keep a separate set of logic and rules in your head").

## 1. Today (to verify)

From `docs/ui/phone.md`: read-only; a tap on a note shows its own tags as blue pills and never edits; tapping a tag pill searches (with a developer switch for replace or narrow); search terms show as pills; search contexts ("tabs") and the AI chat are hidden; the bottom bar is ☰ · "Read-only" · ＋; ＋ opens a full-screen capture sheet, and an untagged capture gets `@inbox`; back restores the previous search; read-only is enforced in the client only.

## 2. Editing, like the desktop

- **Tap a note to select it and enter edit mode,** with its tags showing, as on the desktop.
- **The menu (☰, bottom left) acts on the selected note,** like the desktop's right-click note menu, **trimmed:** add sibling, add child, copy, paste, move (top, up, down, bottom), delete, plus checkboxes and expand/collapse (shared with the desktop, as collapse is saved on the note).
- **Not on the phone:** editing tag relationships (the ontology editor), creating rules, creating or switching vaults, creating reminders, AI settings. The **server refuses these from phone clients** (by client type, not a different protocol; a guard against the phone app's own mistakes, not a security boundary, §10); today's client-only read-only rule goes.
- **The menu always also shows the desktop's view options,** nothing new: sort (Normal, Created, Updated, A–Z, Size, Reverse), date range, notes with files, untagged notes; and Lock, Sign Out. They behave as on the desktop.
- **No long-press menu.** The ☰ button is the menu.

## 3. Adding a note: no "capture"

- **＋ (bottom right) does what Enter does on the desktop:** a blank note at the top of the list, **already in edit mode**, with **the current search's tags** pre-filled and clearly visible (so a stale search is noticed before moving on). In no search, it's untagged. Exclusions and text terms aren't carried over (as on the desktop; verify).
- **Remove the capture sheet, the `@inbox` tag and any inbox plan.** No phone-specific tag either: a note typed on the phone is as ordinary as one typed in a second browser tab. To see recent additions on any device, sort by Created.
- **What a note holds is what it holds on the desktop:** text (the keyboard's dictation works for free); **photos attach the way files attach on the desktop** (the phone's file picker offers the camera or the photo library); links are pasted text.

## 4. Search bar and search contexts

- **Top: the search bar, full width,** with the **search-context icon (folder) at its left end;** the list drops down over the notes when opened. The set of search contexts is shared with the desktop; which one the phone shows is its own (multi-view note).
- **Tags in the search bar and in a note's tags are plain text, not pills.** **Tapping a tag selects the whole tag,** so one press of delete removes it; typing replaces it. Why: everyone knows how to edit text in a box; pills usually can't be edited directly.
- **View options (sort, date range, files, untagged) stay pills** inside the search box, each with ×, as now, so tags and view options never look alike.
- **Tapping a tag never runs a search.** Remove the tag-pill search and its developer switch. Searching is done in the search bar, with tag suggestions as on the desktop.
- **No back-to-previous-search history.** Horizontal swiping is kept for moving between the notes and the AI (§5). Search contexts are the saved searches, one tap away.
- **Note rows** look like desktop rows, without tag chips (as now).

## 5. The AI chat: a full screen that trades places with the notes

- **Bottom bar: ☰ (left) · AI (middle) · ＋ (right),** on every screen, in thumb reach. "Read-only" goes.
- **The AI button opens the chat as a full screen:** the notes slide off to the left and the chat slides in from the right, filling everything above the bottom bar. The AI button again, or a horizontal swipe, slides back. They never share the screen. (From the right because on the desktop the chat is the column to the right of the notes.)
- **The slide is animated, a deliberate exception** to MetaList's no-added-motion rule: it shows where the chat went, it's always caused by the user's tap or swipe, it's short, and **Reduce Motion makes it an instant switch.** Write it into `docs/ui/interaction-principles.md` as an exception, not a precedent.
- **Scope:** as on the desktop, the AI sees the search context the phone is showing. One conversation per vault, shared live with the desktop, one answer at a time (multi-view note).
- **Controls on the phone:** the conversation; the composer with Send/Stop and the model and thinking picker; Clear Chat. **Desktop only:** the developer eye toggle, Agent Debug, and AI settings (provider keys). No close button: the AI button or a swipe goes back.
- **Tapping an answer opens a small menu at the finger:** **Copy Response** and **Save as Note** (the answer as a new note at the top, with the current search's tags and `@markdown @ai`: what copying and pasting an answer does on the desktop, in one step). It's the phone's version of the desktop's right-click on an answer. A menu, not a dialog: no dimming; it closes on a tap elsewhere or on picking an action. A tap on a link inside an answer opens the link. No selection state, no checkboxes. *Why not long-press:* nothing on screen hints that it exists.

## 6. Passwords, as on the desktop

- An `@password` value shows blurred; **a tap copies it** (as a click does on the desktop, with the same green flash); **to see it, edit the note.** No new reveal gesture.
- **No clipboard clearing in the web app:** the password is pasted in another app, by which time MetaList is in the background and can't clear the clipboard (verify). It comes with the native app.

## 7. Coming later (don't build now; don't block)

- **Audio memos** in notes (keep the audio, transcribe it, or both: undecided).
- Face ID and passkeys (WebAuthn, PRF to unlock a stored key), and the biometric policy; app-switcher blur.
- Getting the vault key onto the phone by **QR linking** (the passphrase is never typed on a phone) for the hosted service.
- An encrypted **offline** cache and a pending-edit queue.
- **Reminders** reaching the phone (content-free push in the web app; local notifications in the native app).
- The **native app** (Capacitor wrapping this same web code): Share-menu extension, certificate pinning, password autofill, clipboard expiry; then the app stores.
- Still from `phone-later.md`: first-load speed (bundle or cache the ~250 scripts), and a back control if iOS gives standalone web apps no back swipe.

## 8. Invariants

1. The phone is the desktop app on a smaller screen: same rules, trimmed menu, nothing phone-specific where a desktop piece does the job.
2. Tap a note to edit it; ☰ acts on the selected note; ＋ is Enter.
3. A note added on the phone is an ordinary note with the current search's tags.
4. One screen of search and notes, and one AI screen that trades places with it.
5. The trimmed menu's exclusions are enforced by the server.

## 9. Tests (at least)

- Tap a note: it enters edit mode with its tags; ☰ shows its actions (trimmed) and the view options.
- ＋ in a `journal` search: a note at the top in edit mode, tagged `journal`, no other tag; it appears in the desktop's `journal` search live.
- A phone client calling an excluded route (ontology edit, rule creation, vault creation, reminder creation, AI settings) is refused by the server.
- Tags in the search bar are plain text; tapping one selects it whole; delete removes it; tapping a tag in a note never searches.
- The search-context icon lists the desktop's contexts; switching on the phone doesn't switch the desktop.
- AI button and swipe slide the chat in and out; with Reduce Motion the switch is instant; tapping an answer shows Copy Response and Save as Note, and Save as Note makes the expected note.
- A password taps to copy and stays blurred.
- Attaching a photo from the camera or library attaches it as a file, as on the desktop.

## 10. Checked 2026-10-27 (filed from the inbox)

- Confirmed against `docs/ui/phone.md`: the read-only list, tap shows the note's own tags as pills, tag pills search with the `metalist.dev.phoneTagPills` developer switch, back restores the previous search, the bottom bar ☰ · "Read-only" · ＋, the capture sheet and `@inbox`, read-only enforced in the client only. The ☰ sheet already holds the desktop's view options, Lock and Sign Out.
- Confirmed on the desktop: `Enter` outside edit mode adds a note at the top with the search's required tag terms in its tag bar (`docs/ui/controls.md`), so ＋ can reuse it. MetaList adds no motion of its own (`docs/ui/interaction-principles.md`, Principles), so §5's slide is the first exception. Reduce Motion, password copy with the green flash, and file attachments exist on the desktop. The chat's eye panel, Agent Debug, the model and thinking picker and Clear Chat exist (`docs/ui/ai-chat.md`).
- **Correction:** on the desktop, Copy Response tags the copy `@markdown @ai` (lowercase, and `@markdown` so the Markdown renders), not `@AI` (`docs/ui/controls.md`). Save as Note gives the same two tags (maintainer, 2026-10-27; §5 corrected): MetaList's AI is encouraged to answer in Markdown.
- **Not there yet:** the server knows no client type. `docs/future-plans/phone-later.md` listed "a server-side phone client type" as out of scope. The phone's view (`multi-view-editing.md`) would declare it.
- **The server's refusal of the trimmed routes is a guard against the phone app's own mistakes, not a security boundary** (maintainer, 2026-10-27). The client declares its own type, so it keeps the phone's interface out of those routes but stops nothing that claims to be a desktop. That is enough: anyone with the password can use those routes from a desktop anyway.
- `@inbox` goes entirely, with nothing done to notes already carrying it: no vault in use has any (maintainer, 2026-10-27).
- The phone sheets and capture follow the theme since 2026-10-27 (`docs/ui/modals.md`); capture goes away here.
