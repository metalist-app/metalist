# Deployment profiles: personal, self-hosted, hosted

**Status:** Agreed with the maintainer 2026-10-27.
- **Ready to build:** §1, §2 and §3.
- **Direction only:** §4, the hosted list, which belongs with the hosted build.

Everything not marked *agreed* is proposed; adjust what reads badly.

Written from a read-only look at the code, without running it. A sweep found these items, and the ones marked ✓ were re-checked by hand. Check every reference before relying on it; build only what's missing.

---

## 0. Background

- **`METALIST_ENVIRONMENT`** (`development` / `production`, `app/startup_environment.py`) says how the server is run. It turns debugging aids on or off. Nothing says **where** the server runs, and several behaviours assume it's the person's own computer.
- **`@shell`** is off unless started with `--enable-shell` ✓ (`main.py`, `app/security/shell_execution.py`), and shell requests must come from loopback (`app/api/routes/notes.py`, around line 246).
- **`docs/future-plans/hosted-own-copy.md`** already describes a hosted mode for backups. This note makes it one general setting, and that plan uses it.

## 1. The setting (agreed)

| Profile | Where the server runs |
|---|---|
| `personal` | The person's own laptop or desktop. They sit at it; it may also serve their phone over Wi-Fi. |
| `self-hosted` | The person's own server in the cloud (a VPS), reached over the internet. No screen, no desktop apps, no terminal under systemd or Docker. |
| `hosted` | The hosted service: one container per user, run by the operator. |

- **One setting,** proposed as `METALIST_DEPLOYMENT=personal | self-hosted | hosted`, default `personal`. Validate it like `METALIST_ENVIRONMENT`, rejecting unknown values.
- **Set by whoever installs the server: environment or launch configuration, never a user setting** (agreed). Nothing in the UI can change it.
- **Don't infer it from the network.** A laptop serving its phone binds beyond loopback and is still `personal`.
- **Independent of `METALIST_ENVIRONMENT`:** a hosted test environment is `hosted` + `development`.
- Print it at startup next to the environment line.

## 2. Per profile (agreed)

| | personal | self-hosted | hosted |
|---|---|---|---|
| `@shell` | Opt-in with `--enable-shell`, as today | **Opt-in, with warnings** (§2.1) | **Never.** The flag is refused at startup and the shell routes refuse |
| Backup folder | Yes | Yes: a path typed on the server | **Refused by the server** (`hosted-own-copy.md`) |
| Native folder picker | Yes | No: hide it and type a path | No |
| Synced-folder suggestions (`ready-to-build/backups-synced-folders.md`) | Yes | No | No |
| Backup Reminder default | Weekly | Weekly | Off, per `hosted-own-copy.md`. The server supplies the default instead of the browser constant |

### 2.1 `@shell` on self-hosted (proposed)

- **At startup,** `--enable-shell` on `self-hosted` makes the person confirm that `@shell` runs commands on this server for anyone who can sign in. With no terminal, it needs an explicit second flag or variable.
- **A small indicator** shows in the app while `@shell` is on.
- **It needs a vault password.**
- **The loopback check won't work behind a reverse proxy on the same machine,** where every request looks local. Please verify. Self-hosted opt-in replaces the loopback requirement with "signed in to a vault with a password". Personal keeps the loopback check.

## 3. Before anyone runs `self-hosted` on the internet

In rough priority order:

1. **The first visitor can claim a vault** ✓. Startup creates a passwordless `default` vault (`_bootstrap_default_namespace_if_empty`, `main.py`). Setting the first password needs no sign-in while there is none (`app/api/middleware/auth.py`, the `password/create` exception).
   - On `self-hosted`, require a one-time setup code: printed at startup, or written to a file in the data directory, and needed to create the first password. Proposed.
   - Personal stays as today.
2. **Passwordless vaults hand out full sessions** (`POST /auth/session`; the no-login render in `app/main.py`).
   - On `self-hosted`, require a vault password. Proposed, not yet ruled on.
   - `hosted` never has plaintext vaults.
3. **Vault names and vault launching are public** ✓ (`/auth/login-namespaces`, `/auth/login-namespaces/open`, `/namespace-deleted/open` in `PUBLIC_EXACT_PATHS`).
   - On `self-hosted`, hide the list until signed in, or require the setup code.
   - On `hosted`, the account login sits in front of everything.
4. **Terminal prompts at startup** (`_prompt_for_missing_namespace_launch_profiles`, `input()` in `main.py`). Never prompt outside `personal`: assign or fail with a clear message.
5. **"Today" is the server's day** ✓. It's used by `local_today()` (`root_date_filter.py`), day groups (`root_sorting.py`), search-history dates (`search_history.py`) and export filenames (`html_export.py`). A cloud server runs in UTC.
   - Use the browser's time zone for everything a person sees, in **all** profiles; it helps personal users who travel too.
   - Reminders already take the client's offset.
6. **One session per vault** ✓: `create_token` clears every other token (`app/services/tokens.py`). This is already agreed in `ready-to-build/multi-view-editing.md` (several devices; sign-out per device). Mentioned here so it isn't fixed twice.
7. **Sessions never expire by default** (`DEFAULT_TOKEN_EXPIRY_MINUTES` = 0). Outside `personal`, default to an idle timeout.
8. **Certificates, proxies and URLs:**
   - Startup auto-generates a self-signed certificate (`ensure_default_tls_pair`).
   - Non-loopback HTTP redirects to `https://host:<https_port>` (`resolve_https_redirect_url`), which can loop behind a TLS-terminating proxy.
   - Vault URLs are built as `http://127.0.0.1:<port>` (`_build_browser_url`), and the startup "local URL" shows `127.0.0.1`.

   On `self-hosted`:
   - Default to no self-signed certificate.
   - Trust a configured proxy.
   - Take one public base URL setting and use it for redirects, vault links and the startup message.
9. **Login rate limits are per IP**, and behind a proxy everyone shares one. Use the forwarded client address from trusted proxies.
10. **Network settings persist in `network-settings.json`** and reapply silently on later starts (`app/network_settings.py`). Document it, and print the values in effect at startup.

## 4. Hosted (direction only; with the hosted build)

With one container per user, a signed-in user controlling "the server" controls only their own container, so managing their own vaults is fine. What the operator must own:
- **No self-update from the browser.** `POST /auth/app-update` stops every vault, downloads `uv` and reinstalls. Turn that off, and stop the public `/auth/app-update/check` calling PyPI on page load. Images are shipped; updates follow the hosted update plan.
- **No port picking, process launching or killing by port.** No `/namespaces/ports`, no `lsof`/`ps`-based eviction (`_evict_processes_listening_on_port`), no `os.execv` restart after a restore. The container supervisor restarts. (On `self-hosted`, fail with a message rather than kill a foreign process.)
- **Sizing:**
  - `PRAGMA cache_size=500000` ✓ (`app/models/database.py`) is roughly 2 GB per connection.
  - Every JSON block render spawns `python -m json.tool` (`structured_note_renderers.py`); parse in process, in every profile.
  - The memory-breakdown endpoint holds the write lock for seconds; hide it.
- **No server paths in errors** (`http_error_diagnostics.py`; backup route messages).
- **Quotas:** storage per account, a general request-body limit, and rate limits on link-title and favicon fetching.
- **Refuse to start with `TEST_MODE`,** which mounts `/dev/*` and a public `/test/reset`.

## 5. Already good, keep it

- **`resolve_public_http_target`** (`app/services/public_http.py`) refuses non-global addresses for every outside fetch (link titles, favicons, remote images, the AI web tool), pins the checked IPs and rechecks redirects. One question to verify: NAT64 `64:ff9b::/96` counts as global.
- **AI provider endpoints come from the catalog,** never typed in.
- **Host-header allowlist; no CORS.**

## 6. Small bugs noticed (any profile)

- The runtime folder falls back to the shared `$TMPDIR/metalist-runtime` unless `METALIST_DATA_DIRECTORY` is set (`server_runtime.py`).
- The encryption-audit CLI default ignores `METALIST_DATA_DIRECTORY` (`encryption_audit.py`).
- `CRASH_SERVER_ON_FAIL`, `DEV_ENFORCE_INTEGRITY_CHECKS` and `DISABLE_UNDO_SNAPSHOT` are read but never used (`config.py`).
- `_LOOPBACK_BIND_HOSTS` lists `0.0.0.0` and is unused (`server_runtime.py`).

## 7. Acceptance checks

- `METALIST_DEPLOYMENT` unset → `personal`. An unknown value refuses to start. The value prints at startup.
- `hosted` + `--enable-shell` refuses to start, and the shell routes refuse requests.
- `self-hosted` + `--enable-shell` asks for confirmation, the app shows the indicator, and a vault without a password can't use `@shell`.
- `self-hosted`, fresh data directory: a visitor can't create the first password without the setup code, and the vault list isn't shown before sign-in.
- `self-hosted` under a process with no terminal starts without prompting.
- A server in UTC and a browser at UTC−7 at 21:00 local: "today" and a new note's day group are the browser's day.
- `hosted`: the backup folder routes and the folder picker refuse, and the reminder defaults to off.

## 8. Invariants

1. The deployment profile comes from whoever installs the server, never from a user setting.
2. `hosted` never runs `@shell`, writes to a path a user supplies, updates itself or kills processes.
3. A server reachable from the internet never hands a vault to its first visitor.
4. Dates a person sees follow the person's time zone, not the server's.

## 9. Checked 2026-10-27 (filed from the inbox)

- **Confirmed** (each found in the code): `METALIST_ENVIRONMENT` (`app/startup_environment.py`); `--enable-shell` (`main.py`) and `app/security/shell_execution.py`; the loopback check for shell requests (`app/api/routes/notes.py`); `_bootstrap_default_namespace_if_empty` and `_prompt_for_missing_namespace_launch_profiles` (`main.py`); the `password/create`, `login-namespaces` and `namespace-deleted/open` exceptions (`app/api/middleware/auth.py`); `local_today` (`root_date_filter.py`), `root_sorting.py`, `search_history.py`; `create_token` clearing every other token (`app/services/tokens.py`); `DEFAULT_TOKEN_EXPIRY_MINUTES = 0`; `ensure_default_tls_pair`, `resolve_https_redirect_url`, `_build_browser_url`; `network-settings.json` (`app/network_settings.py`); `/auth/app-update`; `_evict_processes_listening_on_port`; `os.execv`; `PRAGMA cache_size=500000` (`app/models/database.py`); `json.tool` (`structured_note_renderers.py`); `/test/reset`; `resolve_public_http_target` (`app/services/public_http.py`); `metalist-runtime`, `_LOOPBACK_BIND_HOSTS`; `CRASH_SERVER_ON_FAIL` (`app/config.py`).
- **Wrong path:** `http_error_diagnostics.py` is `app/security/http_error_diagnostics.py`.
- **Already filed, so build them once:** the hosted backup mode (`docs/future-plans/hosted-own-copy.md`, which §4 belongs with) and several sessions per vault (`docs/ready-to-build/multi-view-editing.md`, §3 item 6). The synced-folder suggestions (§2) are `docs/ready-to-build/backups-synced-folders.md`.
- **When built:** a server-supplied Backup Reminder default (§2) and any new setting stored in a vault database are schema changes under AGENTS.md's "Database Schema Changes Require a Version Bump"; an environment variable is not.
- **Open (proposed, for the maintainer):** §2.1's confirmation, indicator and password rule for `@shell` on self-hosted; §3's one-time setup code (item 1), passwords required on self-hosted (item 2, "not yet ruled on"), hiding the vault list (item 3), the idle-timeout default (item 7) and the proxy and base-URL settings (items 8 and 9).
