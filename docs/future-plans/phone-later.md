# Phone: what is left

The phone prototype is built ([docs/ui/phone.md](../ui/phone.md)); these were left for later
(agreed 2026-10-24 unless marked open). Most of this list is replaced by
[phone-same-app.md](../ready-to-build/phone-same-app.md) (2026-10-27): the phone becomes the desktop
app on a smaller screen, and its §7 keeps what is still for later.

- **Not checked on a real phone yet:** back in the home-screen app (iOS may give a standalone web
  app no back swipe; if so, a small ‹ in the search bar), and whether the keyboard covers Save in
  capture.
- **First load is slow on a phone:** before the password, the page fetches about 250 script files
  one at a time with caching off. Bundling or caching them would fix it.
- **The tag pill switch:** replace or narrow; one is kept and the developer switch removed.
  Superseded (2026-10-27): tapping a tag never searches; the switch goes (`phone-same-app.md`, §4).
- **Read-only is enforced in the client only;** a server rule that edit routes refuse phone
  clients comes later. Superseded (2026-10-27): the phone edits, locked per root note like any
  view; the server refuses phone clients only the trimmed routes (`phone-same-app.md`, §2).
- **An inbox:** captures with no tags are tagged `@inbox`; there is no inbox view, count or step
  that clears the tag once a note is sorted (open: how it should work). Superseded (2026-10-27):
  capture, `@inbox` and the inbox plan go; sort by Created to see recent notes (`phone-same-app.md`, §3).
- **Lock vs Sign Out** do the same today; Lock becomes different with Face ID or passkeys.
- **Out of scope for the prototype:** passkeys and Face ID, offline caching, a server-side phone
  client type, photos and audio, capture presets, password tap-to-reveal and clipboard clearing,
  push notifications, and the native (Capacitor) app.
