# Phone: what is left

The phone prototype is built ([docs/ui/phone.md](../ui/phone.md)); these were left for later
(agreed 2026-10-24 unless marked open).

- **Not checked on a real phone yet:** back in the home-screen app (iOS may give a standalone web
  app no back swipe; if so, a small ‹ in the search bar), and whether the keyboard covers Save in
  capture.
- **First load is slow on a phone:** before the password, the page fetches about 250 script files
  one at a time with caching off. Bundling or caching them would fix it.
- **The tag pill switch:** replace or narrow; one is kept and the developer switch removed.
- **Read-only is enforced in the client only;** a server rule that edit routes refuse phone
  clients comes later.
- **An inbox:** captures with no tags are tagged `@inbox`; there is no inbox view, count or step
  that clears the tag once a note is sorted (open: how it should work).
- **Lock vs Sign Out** do the same today; Lock becomes different with Face ID or passkeys.
- **Out of scope for the prototype:** passkeys and Face ID, offline caching, a server-side phone
  client type, photos and audio, capture presets, password tap-to-reveal and clipboard clearing,
  push notifications, and the native (Capacitor) app.
