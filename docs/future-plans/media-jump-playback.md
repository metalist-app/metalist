# Jumping inside audio and video

**Status:** Left for later by the maintainer, 2026-11-08. Nothing built beyond the server's side.

Today a Play button loads the whole file into the browser, then plays it (`media-player-service.js`), which is slow for a long video. The server already answers `Range` requests (`app/api/byte_ranges.py`). The blocker is that every file request needs the tab's session header, and a browser's own audio and video players can't send one.

**The options, as discussed:**

| Option | How it works | Downside |
|---|---|---|
| Playback link (recommended) | Play asks for a random, temporary address for that one file; the player uses it and can jump anywhere | A new way to authorize a request: anyone who got the address could read that file while it is valid |
| The page feeds the player | The page fetches pieces with the header and hands them to the player (Media Source Extensions) | Only some formats work; many ordinary MP4s don't |
| Leave it | As today | Painful for long videos |

If built, the link would be limited to one file, end when the vault locks or the person logs out, never be saved, and get its own security review.
