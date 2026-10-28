# Self-hosting is community-only: a short page, no packaging

**Status:** Agreed with the maintainer 2026-10-27. Small; ready to write once the internet-facing fixes in `deployment-profiles` §3 land. The page's wording is proposed, so adjust what reads badly.

Written from a read-only look at the repo. Adds to `docs/ready-to-build/deployment-profiles.md`.

## Found when filed (2026-10-28)

Filed from `docs/inbox/2026-10-27-self-hosting-community-only.md`.

- **Not there yet:** `METALIST_DEPLOYMENT` (proposed in `deployment-profiles` §1) and the public base URL setting (§3 item 8). Leave both off the page until they exist.
- **There:** `METALIST_DATA_DIRECTORY`, `METALIST_HOST` and `METALIST_ALLOWED_HOSTS` (both can also be saved in the data root's `network-settings.json`, `app/network_settings.py`), `METALIST_FORWARDED_ALLOW_IPS` and `METALIST_AUTO_GENERATE_TLS` (`app/server_runtime.py`).
- **`@shell` is already off by default:** it runs only when MetaList is started with `--enable-shell` (which sets `METALIST_SHELL_ENABLED=1`, `app/security/shell_execution.py`). The page can say "don't start it with `--enable-shell`."
- **No Docker or installer files exist,** and the README doesn't mention self-hosting.
- **`Back Up Now…`** is the palette's name for it. S3 is `docs/future-plans/backups-s3.md`.
- **Open:** where the page lives (proposed `docs/self-hosting.md`) and its wording.

---

## 0. The decision (agreed)

At launch, running MetaList on your own server (the `self-hosted` profile) is **community-only**:
- The code is public (MIT), plus **one short "Self-hosting" page** saying what it takes, with clear warnings.
- **No official Docker image, installer or setup scripts for self-hosting.** No promise that a release keeps any particular self-hosted setup working. No install support.
- **The safety fixes in `deployment-profiles` §3 still happen.** They protect anyone who self-hosts anyway: no first-visitor vault claim, no public vault list, no terminal prompts, the browser's time zone, proxies and certificates. Community-only means unsupported, not unsafe.

**Why:** every server setup is different, and supporting them would crowd out everything else. A misconfigured server that gets breached shouldn't read as "MetaList got hacked."

## 1. Don't build

- A Dockerfile, compose file, Helm chart or installer for self-hosting.
- Self-hosting install steps in the main README beyond one line pointing at the page.

If any of these already exist, leave them, but don't advertise them as supported.

## 2. The page (proposed)

**Where:** the code agent's choice, for example `docs/self-hosting.md`, with one line in the README pointing to it.

**Contents, short:**
1. **Unsupported, at the top:** `Self-hosting is community-supported. MetaList doesn't provide install help, an official image, or guarantees that an update keeps your setup working. If you want MetaList run for you, use the hosted service.`
2. **What you need:** a server you keep updated, a domain, TLS terminated at a reverse proxy (Caddy or nginx, for example), and Python 3.11 or newer with `uv`, as for a personal install.
3. **Settings that matter,** each with one line:
   - `METALIST_DEPLOYMENT=self-hosted`
   - `METALIST_DATA_DIRECTORY`
   - `METALIST_HOST`
   - `METALIST_ALLOWED_HOSTS`
   - `METALIST_FORWARDED_ALLOW_IPS` (the proxy)
   - `METALIST_AUTO_GENERATE_TLS=0`
   - the public base URL setting from `deployment-profiles` §3 item 8, once it exists
4. **Security:**
   - Set a vault password before exposing the server. `self-hosted` will require one.
   - Don't expose the server before first sign-in is set up.
   - `@shell` runs commands on the server for anyone who can sign in. Leave it off unless you understand that.
   - Keep the OS and MetaList updated.
5. **Backups:** use `Back Up Now…` to a folder on the server, or S3 when it exists. Test a restore.
6. **Where to ask:** GitHub Discussions on this repo. It's not enabled yet; the maintainer turns it on. Until then, leave the link out.

**Keep it to one screen or two.** It's a map, not a tutorial.

## 3. Acceptance checks

- The page exists, starts with the unsupported notice, and lists the settings above with one line each.
- The README points to it in one line.
- No new Docker or installer files.
- Every setting named on the page exists in the code; leave out any that don't yet.
