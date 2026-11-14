from __future__ import annotations

from http import HTTPStatus
import re

from starlette.responses import Response


_CSP_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32}$")
# A static file's own answers, which set their own caching: the file, or "not modified". A
# missing file is answered by the error handler and is never stored.
_STATIC_FILE_ANSWERS = frozenset({HTTPStatus.OK, HTTPStatus.NOT_MODIFIED})
_PAGE_SCHEMES = frozenset({"http", "https"})
# A host a CSP source may name: letters, digits, hyphens and dots (CSP3 host-source). An IPv6
# literal cannot be named, so a page opened by one reaches only its own port.
_CSP_HOST_PATTERN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*$")


def own_host_on_any_port(*, scheme: str, hostname: str | None) -> tuple[str, ...]:
    """The page's own host on every port, for connect-src: after its vault moves to new ports
    (Manage Vault Ports), the page asks the new address whether the vault is back before it goes
    there (server-restart.js). Empty when the request named no host a CSP source can name; such
    a Host is refused anyway (request_boundary.py)."""
    if scheme not in _PAGE_SCHEMES or hostname is None:
        return ()
    normalized = hostname.casefold()
    if _CSP_HOST_PATTERN.fullmatch(normalized) is None:
        return ()
    return (f"{scheme}://{normalized}:*",)


def build_content_security_policy(*, nonce: str, extra_connect_sources: tuple[str, ...]) -> str:
    if not isinstance(nonce, str) or _CSP_NONCE_PATTERN.fullmatch(nonce) is None:
        raise ValueError("CSP nonce must be a 32-character URL-safe token")
    if not isinstance(extra_connect_sources, tuple):
        raise TypeError("extra_connect_sources must be a tuple")
    connect_sources = " ".join(("'self' data: blob:", *extra_connect_sources))
    directives = (
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "media-src 'self' data: blob:",
        "font-src 'self' data:",
        f"connect-src {connect_sources}",
        "object-src 'none'",
        # Only a blob: MetaList makes itself from a decrypted PDF, shown by the browser's own
        # viewer inside the file viewer (docs/ready-to-build/files-shown-not-copied.md §4).
        "frame-src blob:",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    )
    return "; ".join(directives)


# is_static_file: one of MetaList's own files (/static/), which sets its own caching
# (app/services/static_files_version.py): a versioned script is kept for good, so a later visit
# downloads none of them. Every other answer is never stored.
def apply_security_headers(
    *, response: Response, nonce: str, is_static_file: bool, extra_connect_sources: tuple[str, ...],
) -> None:
    if not isinstance(response, Response):
        raise TypeError("response must be a Starlette Response")
    response.headers["Content-Security-Policy"] = build_content_security_policy(
        nonce=nonce, extra_connect_sources=extra_connect_sources,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), geolocation=(), microphone=(), payment=(), usb=()"
    )
    if is_static_file and response.status_code in _STATIC_FILE_ANSWERS:
        if "cache-control" not in response.headers:
            raise RuntimeError("A static file's answer must set its own caching")
        return
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
